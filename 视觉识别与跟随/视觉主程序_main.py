"""阶段九视觉识别与视觉跟随主程序。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from vision.路径工具_path_utils import PROJECT_ROOT, VISION_ROOT as BASE_DIR, ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import env_int, env_value, read_structured  # noqa: E402


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else BASE_DIR / "视觉配置.yaml"
    config = read_structured(config_path)
    env_paths = (PROJECT_ROOT / ".env", BASE_DIR / "环境变量.env", PROJECT_ROOT / "系统集成" / "环境变量.env")
    service = config.setdefault("service", {})
    follow = config.setdefault("follow", {})
    service["host"] = env_value("ARM_VISION_HOST", service.get("host", "127.0.0.1"), env_paths=env_paths)
    service["port"] = env_int("ARM_VISION_PORT", int(service.get("port", 8000)), env_paths=env_paths)
    web_host = str(env_value("ARM_WEB_HOST", "127.0.0.1", env_paths=env_paths))
    web_port = env_int("ARM_WEB_PORT", 8010, env_paths=env_paths)
    default_api = f"http://127.0.0.1:{web_port}" if web_host == "0.0.0.0" else f"http://{web_host}:{web_port}"
    web_env_changed = any(env_value(name, "", env_paths=env_paths) for name in ("ARM_WEB_HOST", "ARM_WEB_PORT"))
    follow["robot_api_base"] = env_value(
        "ARM_ROBOT_API_BASE",
        default_api if web_env_changed else follow.get("robot_api_base", default_api),
        env_paths=env_paths,
    )
    return config


def run_preview(config: dict[str, Any]) -> None:
    from vision.摄像头_source import VideoSource

    try:
        import cv2  # type: ignore
    except Exception as exc:
        print("OpenCV 未安装，请先执行：pip install opencv-contrib-python")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    source = VideoSource(config.get("camera", {}), BASE_DIR)
    if not source.open():
        print(f"摄像头打开失败：{source.last_error}")
        raise SystemExit(1)
    print("摄像头预览已启动，按 q 退出。")
    try:
        while True:
            ok, frame, error = source.read()
            if not ok:
                print(f"读取画面失败：{error}")
                break
            cv2.imshow("Arm Vision Preview", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        cv2.destroyAllWindows()


def run_detect(config: dict[str, Any]) -> None:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        print("OpenCV 未安装，请先执行：pip install opencv-contrib-python")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    from vision.视觉引擎_vision_engine import VisionEngine

    engine = VisionEngine(config, BASE_DIR)
    print("人脸检测调试已启动，按 q 退出。")
    try:
        while True:
            result = engine.process_once()
            frame = engine.get_latest_frame()
            if frame is not None:
                cv2.imshow("Arm Face Detect", frame)
            if result.get("detector", {}).get("face_error"):
                print(result["detector"]["face_error"])
                time.sleep(1.0)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        engine.stop()
        cv2.destroyAllWindows()


def run_service(config: dict[str, Any], host: str | None, port: int | None) -> None:
    try:
        import uvicorn  # type: ignore
    except Exception as exc:
        print("FastAPI 服务依赖缺失，请先执行：pip install fastapi uvicorn")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    from vision.视觉服务_api import create_app

    service_cfg = config.get("service", {})
    bind_host = host or str(service_cfg.get("host", "127.0.0.1"))
    bind_port = int(port or service_cfg.get("port", 8000))
    shown_host = "127.0.0.1" if bind_host == "0.0.0.0" else bind_host
    print("视觉服务已启动：")
    print(f"http://{shown_host}:{bind_port}/health")
    print(f"http://{shown_host}:{bind_port}/latest")
    print(f"http://{shown_host}:{bind_port}/frame.jpg")
    app = create_app(config, BASE_DIR, auto_start=True)
    uvicorn.run(app, host=bind_host, port=bind_port)


def run_follow(config: dict[str, Any], execute_api: bool, latest_url: str | None) -> None:
    from vision.视觉引擎_vision_engine import VisionEngine
    from vision.视觉跟随_controller import VisionFollowController

    engine = None
    if latest_url:
        print(f"视觉跟随将读取远程视觉结果：{latest_url}")
    else:
        engine = VisionEngine(config, BASE_DIR)
        engine.start()
        print("已启动本地视觉引擎用于 follow。")

    controller = VisionFollowController(config, engine=engine, latest_url=latest_url, dry_run=not execute_api)
    controller.start()
    print("视觉跟随已启动。默认 dry-run；如使用 --execute-api，会调用阶段八 /api/v1/motion/joint-step。")
    try:
        while True:
            status = controller.get_status()
            last = status.get("last_command") or {}
            print(json.dumps({"running": status["running"], "dry_run": status["dry_run"], "last": last}, ensure_ascii=False))
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("正在停止视觉跟随...")
    finally:
        controller.stop()
        if engine is not None:
            engine.stop()


def run_gesture(config: dict[str, Any]) -> None:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        print("OpenCV 未安装，请先执行：pip install opencv-contrib-python")
        print(f"原始错误：{exc}")
        raise SystemExit(1) from exc

    from vision.手势识别_gesture_detector import GestureDetector
    from vision.摄像头_source import VideoSource

    detector = GestureDetector(config.get("gesture", {}), BASE_DIR)
    if not detector.available:
        print(detector.last_error)
        return
    source = VideoSource(config.get("camera", {}), BASE_DIR)
    if not source.open():
        print(f"摄像头打开失败：{source.last_error}")
        return
    print("手势识别调试已启动，按 q 退出。")
    try:
        while True:
            ok, frame, error = source.read()
            if not ok:
                print(error)
                break
            gesture = detector.detect(frame)
            text = f"raw={gesture.get('raw') or '-'} stable={gesture.get('stable') or '-'}"
            cv2.putText(frame, text, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Arm Gesture", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="阶段九：视觉识别与视觉跟随系统")
    parser.add_argument("command", nargs="?", choices=["preview", "detect", "service", "follow", "gesture"], help="运行模式")
    parser.add_argument("--config", default=str(BASE_DIR / "视觉配置.yaml"), help="视觉配置文件路径")
    parser.add_argument("--service", action="store_true", help="等价于 command=service，兼容旧启动方式")
    parser.add_argument("--host", default=None, help="服务监听地址")
    parser.add_argument("--port", type=int, default=None, help="服务端口")
    parser.add_argument("--latest-url", default=None, help="follow 模式读取的 /latest 地址")
    parser.add_argument("--execute-api", action="store_true", help="follow 模式实际调用阶段八 API；默认只 dry-run")
    args = parser.parse_args()

    command = "service" if args.service else (args.command or "service")
    config = load_config(args.config)

    if command == "preview":
        run_preview(config)
    elif command == "detect":
        run_detect(config)
    elif command == "service":
        run_service(config, args.host, args.port)
    elif command == "follow":
        run_follow(config, args.execute_api, args.latest_url)
    elif command == "gesture":
        run_gesture(config)


if __name__ == "__main__":
    main()
