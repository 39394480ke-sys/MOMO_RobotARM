"""MediaPipe 可用时打开手势识别，不可用时打印提示。"""

from __future__ import annotations

from 视觉测试路径_test_paths import VISION_ROOT as BASE_DIR

from vision.手势识别_gesture_detector import GestureDetector
from vision.摄像头_source import VideoSource
from 视觉主程序_main import load_config


def main() -> None:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        print("OpenCV 未安装，请先执行：pip install opencv-contrib-python")
        print(exc)
        return

    config = load_config(BASE_DIR / "视觉配置.yaml")
    detector = GestureDetector(config.get("gesture", {}), BASE_DIR)
    if not detector.available:
        print(detector.last_error)
        return

    source = VideoSource(config.get("camera", {}), BASE_DIR)
    if not source.open():
        print(f"摄像头打开失败：{source.last_error}")
        return
    print("手势识别测试已启动，按 q 退出。")
    try:
        while True:
            ok, frame, error = source.read()
            if not ok:
                print(error)
                break
            gesture = detector.detect(frame)
            print(gesture)
            cv2.imshow("gesture test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
