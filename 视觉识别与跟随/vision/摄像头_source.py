"""统一视频源：USB 摄像头、本地视频文件、RTSP。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - 依赖缺失时也要能导入模块
    cv2 = None  # type: ignore


class VideoSource:
    """对 cv2.VideoCapture 做一层安全封装。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.cap: Any | None = None
        self.last_error = ""
        self.source_description: dict[str, Any] = {}

    def open(self) -> bool:
        if cv2 is None:
            self.last_error = "OpenCV 未安装，请先执行：pip install opencv-contrib-python"
            return False

        self.close()
        source_type = str(self.config.get("source_type", "camera")).strip().lower()
        source: int | str

        if source_type in {"camera", "usb", "usb_camera"}:
            source = int(self.config.get("camera_index", 0))
            self.source_description = {"source_type": "camera", "camera_index": source}
        elif source_type in {"video", "file", "video_file"}:
            video_file = str(self.config.get("video_file", "")).strip()
            if not video_file:
                self.last_error = "视频源配置为本地文件，但 video_file 为空。"
                return False
            path = Path(video_file)
            if not path.is_absolute():
                path = self.base_dir / path
            if not path.exists():
                self.last_error = f"本地视频文件不存在：{path}"
                return False
            source = str(path)
            self.source_description = {"source_type": "video_file", "video_file": str(path)}
        elif source_type in {"rtsp", "rtsp_url", "stream"}:
            rtsp_url = str(self.config.get("rtsp_url", "")).strip()
            if not rtsp_url:
                self.last_error = "视频源配置为 RTSP，但 rtsp_url 为空。"
                return False
            source = rtsp_url
            self.source_description = {"source_type": "rtsp", "rtsp_url": rtsp_url}
        else:
            self.last_error = f"未知视频源类型：{source_type}"
            return False

        cap = cv2.VideoCapture(source)
        if source_type in {"camera", "usb", "usb_camera"}:
            width = int(self.config.get("width", 640))
            height = int(self.config.get("height", 480))
            fps = int(self.config.get("fps", 30))
            if width > 0:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            if height > 0:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if fps > 0:
                cap.set(cv2.CAP_PROP_FPS, fps)

        if not cap.isOpened():
            self.last_error = f"视频源打开失败：{self.source_description}"
            try:
                cap.release()
            except Exception:
                pass
            self.cap = None
            return False

        self.cap = cap
        self.last_error = ""
        return True

    def read(self) -> tuple[bool, Any | None, str]:
        if self.cap is None or not self.is_opened():
            message = self.last_error or "视频源未打开。"
            return False, None, message
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.last_error = "读取摄像头画面失败，可能是摄像头被占用、断开或视频已结束。"
            return False, None, self.last_error
        return True, frame, ""

    def close(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None

    def is_opened(self) -> bool:
        try:
            return bool(self.cap is not None and self.cap.isOpened())
        except Exception:
            return False
