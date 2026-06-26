"""打开摄像头，检测人脸，显示 bbox 和 center。"""

from __future__ import annotations

from 视觉测试路径_test_paths import VISION_ROOT as BASE_DIR

from vision.视觉引擎_vision_engine import VisionEngine
from 视觉主程序_main import load_config


def main() -> None:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        print("OpenCV 未安装，请先执行：pip install opencv-contrib-python")
        print(exc)
        return

    config = load_config(BASE_DIR / "视觉配置.yaml")
    engine = VisionEngine(config, BASE_DIR)
    print("人脸检测测试已启动，按 q 退出。")
    try:
        while True:
            result = engine.process_once()
            for face in result.get("faces", []):
                print(f"bbox={face.get('bbox')} center={face.get('center')} score={face.get('score')}")
            frame = engine.get_latest_frame()
            if frame is not None:
                cv2.imshow("face detect test", frame)
            if result.get("detector", {}).get("face_error"):
                print(result["detector"]["face_error"])
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        engine.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
