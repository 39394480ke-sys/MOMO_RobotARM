"""机械臂小宠物摄像头生活周报生成器。

这个脚本只读取阶段九视觉服务，不控制机械臂，也不调用阶段八运动接口。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal


DEFAULT_VISION_URL = "http://127.0.0.1:8000"
from 生活周报路径工具_life_report_path_utils import LIFE_REPORT_ROOT as BASE_DIR, ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_http import HTTPJsonError, fetch_bytes as fetch_url_bytes, request_json_object  # noqa: E402
from 通用_io import read_json_object, read_text, write_text  # noqa: E402


@dataclass(frozen=True)
class VisionSnapshot:
    health: dict[str, Any]
    latest: dict[str, Any]
    frame_path: Path | None
    captured_at: datetime
    source: str


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    return request_json_object(url, timeout=timeout)


def fetch_bytes(url: str, timeout: float) -> bytes:
    return fetch_url_bytes(url, timeout=timeout, headers={"Accept": "image/jpeg"})


def load_notes(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"备注文件不存在：{path}")
    lines = []
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if line:
            lines.append(line)
    return lines


def make_period_label(range_name: Literal["day", "week"], now: datetime) -> tuple[str, str]:
    if range_name == "day":
        return now.strftime("%Y-%m-%d"), now.strftime("%Y年%m月%d日")
    year, week, _weekday = now.isocalendar()
    start = now - timedelta(days=now.weekday())
    end = start + timedelta(days=6)
    slug = f"{year}-W{week:02d}"
    title = f"{year}年第{week:02d}周（{start:%m月%d日}-{end:%m月%d日}）"
    return slug, title


def copy_or_fetch_snapshot(
    *,
    vision_url: str,
    output_dir: Path,
    timeout: float,
    latest_file: Path | None,
    frame_file: Path | None,
    skip_frame: bool,
) -> VisionSnapshot:
    captured_at = datetime.now()
    source = vision_url.rstrip("/")
    health: dict[str, Any] = {}

    if latest_file is not None:
        latest = read_json_object(latest_file)
        source = f"file:{latest_file}"
    else:
        base = vision_url.rstrip("/")
        health = fetch_json(f"{base}/health", timeout)
        latest = fetch_json(f"{base}/latest", timeout)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    frame_path: Path | None = None
    if not skip_frame:
        frame_path = assets_dir / f"vision_{captured_at:%Y%m%d_%H%M%S}.jpg"
        if frame_file is not None:
            shutil.copyfile(frame_file, frame_path)
        else:
            frame_bytes = fetch_bytes(f"{vision_url.rstrip('/')}/frame.jpg", timeout)
            if not frame_bytes:
                raise RuntimeError("视觉服务返回了空画面。")
            frame_path.write_bytes(frame_bytes)

    return VisionSnapshot(
        health=health,
        latest=latest,
        frame_path=frame_path,
        captured_at=captured_at,
        source=source,
    )


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def summarize_snapshot(snapshot: VisionSnapshot) -> dict[str, str]:
    latest = snapshot.latest
    offset = latest.get("offset") if isinstance(latest.get("offset"), dict) else {}
    smoothed = latest.get("smoothed_offset") if isinstance(latest.get("smoothed_offset"), dict) else {}
    detector = latest.get("detector") if isinstance(latest.get("detector"), dict) else {}
    gesture = latest.get("gesture") if isinstance(latest.get("gesture"), dict) else {}

    detected = bool(latest.get("detected", False))
    camera = latest.get("camera") if isinstance(latest.get("camera"), dict) else {}
    camera_ok = bool(camera.get("available", snapshot.health.get("camera_available", False)))
    fps = safe_float(latest.get("fps"))
    ndx = safe_float(offset.get("ndx"))
    ndy = safe_float(offset.get("ndy"))
    sndx = safe_float(smoothed.get("ndx"))
    sndy = safe_float(smoothed.get("ndy"))
    direction = ""
    if isinstance(latest.get("direction"), dict):
        direction = str(latest["direction"].get("combined") or "")

    mood = "它今天看见你了，适合记录一些桌面陪伴瞬间。" if detected else "它今天主要保持观察，没有稳定检测到人脸。"
    if not camera_ok:
        mood = "摄像头当前不可用，优先检查供电、占用和 camera_index。"

    keywords = ["机械臂小宠物", "桌面摄像头", "本地周报"]
    if detected:
        keywords.append("人脸在画面中")
    if direction:
        keywords.append(f"视角偏移:{direction}")
    if gesture.get("stable"):
        keywords.append(f"手势:{gesture['stable']}")

    return {
        "detected": "是" if detected else "否",
        "camera": "可用" if camera_ok else "不可用",
        "fps": f"{fps:.1f}",
        "offset": f"ndx={ndx:.4f}, ndy={ndy:.4f}",
        "smoothed_offset": f"ndx={sndx:.4f}, ndy={sndy:.4f}",
        "direction": direction or "无",
        "detector": str(detector.get("backend") or detector.get("face_backend") or "未知"),
        "mood": mood,
        "keywords": "、".join(keywords),
    }


def relative_path(target: Path | None, base: Path) -> str:
    if target is None:
        return ""
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.as_posix()


def render_markdown(
    *,
    range_name: Literal["day", "week"],
    period_title: str,
    snapshot: VisionSnapshot,
    output_dir: Path,
    notes: list[str],
) -> str:
    summary = summarize_snapshot(snapshot)
    frame_rel = relative_path(snapshot.frame_path, output_dir)
    latest_json = json.dumps(snapshot.latest, ensure_ascii=False, indent=2)
    notes_block = "\n".join(f"- {item}" for item in notes) if notes else "- 暂无手动备注。"
    report_name = "生活日报" if range_name == "day" else "生活周报"

    cover = f"![机械臂摄像头快照]({frame_rel})\n\n" if frame_rel else ""
    return f"""# 机械臂小宠物{report_name}：{period_title}

生成时间：{snapshot.captured_at:%Y-%m-%d %H:%M:%S}

数据来源：`{snapshot.source}`

{cover}## 本期摘要

{summary["mood"]}

- 摄像头状态：{summary["camera"]}
- 是否检测到人脸：{summary["detected"]}
- 画面 FPS：{summary["fps"]}
- 目标偏移：{summary["offset"]}
- 平滑偏移：{summary["smoothed_offset"]}
- 方向判断：{summary["direction"]}
- 关键词：{summary["keywords"]}

## 手动备注

{notes_block}

## AI 周报草稿

这份周报把机械臂当作桌面上的常驻小伙伴：它负责安静地看见现场，电脑负责整理意义。
如果本期检测到人脸，可以把它理解为“你在桌面前出现过”；如果没有检测到，则优先把它当作环境、供电、摄像头占用或模型权重状态的记录。

## 待办回顾

- 确认视觉服务是否需要开机自启。
- 确认摄像头画面角度是否舒服，必要时调整 `视觉配置.yaml` 的 `rotate_180`、`center_x_norm`、`center_y_norm`。
- 真实跟随保持关闭，除非你明确要让机械臂通过阶段八安全 API 小幅移动。

## 原始视觉数据

```json
{latest_json}
```
"""


def write_report(
    *,
    range_name: Literal["day", "week"],
    output_dir: Path,
    snapshot: VisionSnapshot,
    notes: list[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug, period_title = make_period_label(range_name, snapshot.captured_at)
    report_path = output_dir / f"{slug}.md"
    write_text(
        report_path,
        render_markdown(
            range_name=range_name,
            period_title=period_title,
            snapshot=snapshot,
            output_dir=output_dir,
            notes=notes,
        ),
    )
    return report_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成机械臂小宠物摄像头生活日报/周报")
    parser.add_argument("--range", choices=["day", "week"], default="week", help="报告周期")
    parser.add_argument("--out", default=str(BASE_DIR / "reports"), help="报告输出目录")
    parser.add_argument("--vision-url", default=DEFAULT_VISION_URL, help="阶段九视觉服务地址")
    parser.add_argument("--notes", default="", help="可选备注文本文件，每行一条")
    parser.add_argument("--timeout", type=float, default=3.0, help="读取视觉服务超时秒数")
    parser.add_argument("--latest-file", default="", help="测试用：从本地 latest_result.json 读取视觉数据")
    parser.add_argument("--frame-file", default="", help="测试用：从本地 jpg 文件复制快照")
    parser.add_argument("--skip-frame", action="store_true", help="不读取 /frame.jpg，只生成文字报告")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = Path(args.out).expanduser().resolve()
    notes_path = Path(args.notes).expanduser().resolve() if args.notes else None
    latest_file = Path(args.latest_file).expanduser().resolve() if args.latest_file else None
    frame_file = Path(args.frame_file).expanduser().resolve() if args.frame_file else None

    try:
        snapshot = copy_or_fetch_snapshot(
            vision_url=str(args.vision_url),
            output_dir=output_dir,
            timeout=float(args.timeout),
            latest_file=latest_file,
            frame_file=frame_file,
            skip_frame=bool(args.skip_frame),
        )
        report_path = write_report(
            range_name=args.range,
            output_dir=output_dir,
            snapshot=snapshot,
            notes=load_notes(notes_path),
        )
    except (OSError, HTTPJsonError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"生成失败：{exc}")
        print("请确认阶段九视觉服务已启动：python 视觉主程序_main.py service")
        return 1

    print(f"已生成生活周报：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
