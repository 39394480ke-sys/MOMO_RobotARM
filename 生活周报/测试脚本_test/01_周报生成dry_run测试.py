"""离线生成生活周报，确认脚本不依赖真实机械臂和摄像头。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

from 生活周报测试路径_test_paths import generator_script_path


def load_generator():
    spec = importlib.util.spec_from_file_location("life_report_generator", generator_script_path())
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    generator = load_generator()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest_path = root / "latest_result.json"
        frame_path = root / "frame.jpg"
        notes_path = root / "notes.txt"
        out_dir = root / "reports"

        latest_path.write_text(
            json.dumps(
                {
                    "timestamp": 1780661997.0,
                    "detected": True,
                    "fps": 29.7,
                    "camera": {"available": True},
                    "offset": {"ndx": 0.0123, "ndy": -0.0456},
                    "smoothed_offset": {"ndx": 0.01, "ndy": -0.03},
                    "direction": {"combined": "center-left"},
                    "detector": {"backend": "opencv_yunet"},
                    "gesture": {"stable": ""},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        frame_path.write_bytes(b"\xff\xd8\xff\xd9")
        notes_path.write_text("今天它一直看着我。\n准备把周报做成小红书风格。\n", encoding="utf-8")

        code = generator.main(
            [
                "--range",
                "week",
                "--out",
                str(out_dir),
                "--latest-file",
                str(latest_path),
                "--frame-file",
                str(frame_path),
                "--notes",
                str(notes_path),
            ]
        )
        assert code == 0
        reports = list(out_dir.glob("*.md"))
        assert len(reports) == 1
        text = reports[0].read_text(encoding="utf-8")
        assert "机械臂小宠物生活周报" in text
        assert "今天它一直看着我。" in text
        assert "/api/v1/motion" not in text
        assert list((out_dir / "assets").glob("*.jpg"))

    print("生活周报 dry-run 测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
