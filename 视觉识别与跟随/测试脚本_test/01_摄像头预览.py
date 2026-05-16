"""打开摄像头并显示画面，按 q 退出。"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

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
    source = VideoSource(config.get("camera", {}), BASE_DIR)
    if not source.open():
        print(f"摄像头打开失败：{source.last_error}")
        return
    print("摄像头预览已启动，按 q 退出。")
    try:
        while True:
            ok, frame, error = source.read()
            if not ok:
                print(error)
                break
            cv2.imshow("camera preview", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
