"""统一视频源：USB 摄像头、本地视频文件、RTSP。"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - 依赖缺失时也要能导入模块
    cv2 = None  # type: ignore


class VideoSource:
    """对 cv2.VideoCapture 做一层安全封装。

    RTSP 由专用线程持续解码，并用一个单槽覆盖保存最新帧。慢速消费者只会
    跳过中间帧，不会读取解码队列中的旧画面。
    """

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.cap: Any | None = None
        self.last_error = ""
        self.source_description: dict[str, Any] = {}
        self.last_frame_metadata: dict[str, Any] = {}

        self._is_rtsp = False
        self._source: int | str | None = None
        self._condition = threading.Condition(threading.RLock())
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._latest_frame: Any | None = None
        self._latest_metadata: dict[str, Any] = {}
        self._source_frame_id = 0
        self._last_delivered_source_frame_id = 0
        self._dropped_source_frames = 0
        self._reader_error = ""

    def open(self) -> bool:
        if cv2 is None:
            self.last_error = "OpenCV 未安装，请先执行：pip install opencv-contrib-python"
            return False

        self.close()
        self.last_error = ""
        self.source_description = {}
        source_type = str(self.config.get("source_type", "camera")).strip().lower()
        source: int | str
        camera_source = source_type in {"camera", "device", "usb", "usb_camera"}
        rtsp_source = source_type in {"rtsp", "rtsp_url", "stream"}

        if camera_source:
            try:
                source = int(self.config.get("camera_index", 0))
            except (TypeError, ValueError):
                self.last_error = f"摄像头 camera_index 必须是整数：{self.config.get('camera_index')!r}"
                return False
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
        elif rtsp_source:
            rtsp_url = str(self.config.get("rtsp_url", "")).strip()
            if not rtsp_url:
                self.last_error = "视频源配置为 RTSP，但 rtsp_url 为空。"
                return False
            source = rtsp_url
            self.source_description = {"source_type": "rtsp", "rtsp_url": rtsp_url}
        else:
            self.last_error = f"未知视频源类型：{source_type}"
            return False

        cap = self._create_capture(source, rtsp_source)
        if cap is None:
            return False

        if camera_source:
            self._safe_set(cap, cv2.CAP_PROP_BUFFERSIZE, 1)
            try:
                width = int(self.config.get("width", 640))
                height = int(self.config.get("height", 480))
                fps = int(self.config.get("fps", 30))
            except (TypeError, ValueError) as exc:
                self.last_error = f"摄像头 width/height/fps 必须是整数：{exc}"
                self._release(cap)
                return False
            if width > 0:
                self._safe_set(cap, cv2.CAP_PROP_FRAME_WIDTH, width)
            if height > 0:
                self._safe_set(cap, cv2.CAP_PROP_FRAME_HEIGHT, height)
            if fps > 0:
                self._safe_set(cap, cv2.CAP_PROP_FPS, fps)
        elif rtsp_source:
            self._configure_rtsp_capture(cap)

        if not self._capture_is_opened(cap):
            if not self.last_error:
                self.last_error = f"视频源打开失败：{self.source_description}"
            self._release(cap)
            return False

        with self._condition:
            self.cap = cap
            self._source = source
            self._is_rtsp = rtsp_source
            self._latest_frame = None
            self._latest_metadata = {}
            self.last_frame_metadata = {}
            self._reader_error = ""
            self.last_error = ""
            self._reader_stop = threading.Event()
            reader_stop = self._reader_stop

        if rtsp_source:
            thread = threading.Thread(
                target=self._rtsp_reader_loop,
                args=(reader_stop,),
                name="rtsp-latest-frame",
                daemon=True,
            )
            with self._condition:
                self._reader_thread = thread
            thread.start()
        return True

    def read(self) -> tuple[bool, Any | None, str]:
        """读取一帧，保持原有三元组返回格式兼容。"""

        ok, frame, metadata, error = self.read_with_metadata()
        self.last_frame_metadata = dict(metadata)
        return ok, frame, error

    def read_with_metadata(self) -> tuple[bool, Any | None, dict[str, Any], str]:
        """读取画面及它在本机解码完成时生成的源帧元数据。"""

        if self._is_rtsp:
            return self._read_latest_rtsp_frame()
        if self.cap is None or not self.is_opened():
            message = self.last_error or "视频源未打开。"
            return False, None, {}, message
        try:
            ok, frame = self.cap.read()
        except Exception as exc:
            self.last_error = f"读取视频源画面异常：{exc}"
            return False, None, {}, self.last_error
        if not ok or frame is None:
            self.last_error = "读取视频源画面失败，可能是源被占用、断开或视频已结束。"
            return False, None, {}, self.last_error
        received_at = time.time()
        frame, error = self._rotate_frame(frame)
        if error:
            return False, None, {}, error
        with self._condition:
            self._source_frame_id += 1
            metadata = self._frame_metadata(received_at)
            self._last_delivered_source_frame_id = self._source_frame_id
            self.last_frame_metadata = dict(metadata)
        self.last_error = ""
        return True, frame, metadata, ""

    def close(self) -> None:
        with self._condition:
            reader_stop = self._reader_stop
            reader_stop.set()
            cap = self.cap
            thread = self._reader_thread
            self.cap = None
            self._condition.notify_all()
        self._release(cap)
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self._read_timeout_sec() + 0.5))
        with self._condition:
            trailing_cap = self.cap
            self.cap = None
            self._reader_thread = None
            self._latest_frame = None
            self._latest_metadata = {}
            self.last_frame_metadata = {}
            self._reader_error = ""
            self._is_rtsp = False
            self._source = None
            self._condition.notify_all()
        if trailing_cap is not cap:
            self._release(trailing_cap)

    def is_opened(self) -> bool:
        if self._is_rtsp:
            thread = self._reader_thread
            return bool(thread and thread.is_alive() and not self._reader_stop.is_set())
        return self._capture_is_opened(self.cap)

    def _read_latest_rtsp_frame(self) -> tuple[bool, Any | None, dict[str, Any], str]:
        deadline = time.monotonic() + self._read_timeout_sec()
        with self._condition:
            reader_stop = self._reader_stop
            while not reader_stop.is_set():
                metadata = self._latest_metadata
                source_frame_id = int(metadata.get("source_frame_id", 0) or 0)
                if self._latest_frame is not None and source_frame_id != self._last_delivered_source_frame_id:
                    frame = self._latest_frame
                    result_metadata = dict(metadata)
                    self._last_delivered_source_frame_id = source_frame_id
                    self.last_frame_metadata = dict(result_metadata)
                    return True, frame, result_metadata, ""
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            error = self._reader_error or self.last_error or "等待 RTSP 最新帧超时。"
        self.last_error = error
        return False, None, {}, error

    def _rtsp_reader_loop(self, reader_stop: threading.Event) -> None:
        with self._condition:
            cap = self.cap
        while not reader_stop.is_set():
            if cap is None:
                cap = self._reconnect_rtsp_capture(reader_stop)
                if cap is None:
                    if reader_stop.wait(self._reconnect_interval_sec()):
                        break
                    continue
            try:
                ok, frame = cap.read()
            except Exception as exc:
                ok, frame = False, None
                error = f"读取 RTSP 画面异常：{exc}"
            else:
                error = "" if ok and frame is not None else "RTSP 画面读取失败，正在重连。"

            if reader_stop.is_set():
                break
            if not ok or frame is None:
                self._record_reader_error(error)
                self._release(cap)
                with self._condition:
                    if self.cap is cap:
                        self.cap = None
                cap = None
                if reader_stop.wait(self._reconnect_interval_sec()):
                    break
                continue

            received_at = time.time()
            frame, rotate_error = self._rotate_frame(frame)
            if rotate_error:
                self._record_reader_error(rotate_error)
                continue

            with self._condition:
                if reader_stop.is_set():
                    break
                previous_id = int(self._latest_metadata.get("source_frame_id", 0) or 0)
                if previous_id > self._last_delivered_source_frame_id:
                    self._dropped_source_frames += 1
                self._source_frame_id += 1
                self._latest_frame = frame
                self._latest_metadata = self._frame_metadata(received_at)
                self._reader_error = ""
                self.last_error = ""
                self._condition.notify_all()

        self._release(cap)
        with self._condition:
            if self.cap is cap:
                self.cap = None
            self._condition.notify_all()

    def _reconnect_rtsp_capture(self, reader_stop: threading.Event) -> Any | None:
        source = self._source
        if source is None or reader_stop.is_set():
            return None
        cap = self._create_capture(source, True)
        if cap is None:
            self._record_reader_error(self.last_error or "RTSP 重连失败。")
            return None
        self._configure_rtsp_capture(cap)
        if not self._capture_is_opened(cap):
            self._release(cap)
            self._record_reader_error(f"RTSP 重连打开失败：{self.source_description}")
            return None
        with self._condition:
            if reader_stop.is_set() or self._reader_stop is not reader_stop:
                self._release(cap)
                return None
            self.cap = cap
            self._reader_error = ""
            self.last_error = ""
            self._condition.notify_all()
        return cap

    def _create_capture(self, source: int | str, rtsp_source: bool) -> Any | None:
        try:
            if rtsp_source:
                backend = getattr(cv2, "CAP_FFMPEG", None)
                open_key = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
                read_key = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
                params: list[int] = []
                if open_key is not None:
                    params.extend([int(open_key), self._open_timeout_msec()])
                if read_key is not None:
                    params.extend([int(read_key), self._read_timeout_msec()])
                if backend is not None and params:
                    try:
                        return cv2.VideoCapture(source, backend, params)
                    except (TypeError, ValueError):
                        pass
            return cv2.VideoCapture(source)
        except Exception as exc:
            self.last_error = f"视频源打开异常：{self.source_description}；{exc}"
            return None

    def _configure_rtsp_capture(self, cap: Any) -> None:
        self._safe_set(cap, getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1)
        self._safe_set(cap, getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), self._open_timeout_msec())
        self._safe_set(cap, getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), self._read_timeout_msec())

    def _rotate_frame(self, frame: Any) -> tuple[Any | None, str]:
        if not bool(self.config.get("rotate_180", False)):
            return frame, ""
        try:
            return cv2.rotate(frame, cv2.ROTATE_180), ""
        except Exception as exc:
            self.last_error = f"旋转视频源画面异常：{exc}"
            return None, self.last_error

    def _frame_metadata(self, received_at: float) -> dict[str, Any]:
        return {
            "source_frame_id": self._source_frame_id,
            "frame_received_at": float(received_at),
            "dropped_source_frames": self._dropped_source_frames,
        }

    def _record_reader_error(self, error: str) -> None:
        with self._condition:
            self._reader_error = str(error)
            self.last_error = self._reader_error
            self._condition.notify_all()

    def _open_timeout_msec(self) -> int:
        return self._positive_int_config("open_timeout_msec", "rtsp_open_timeout_msec", default=2000)

    def _read_timeout_msec(self) -> int:
        return self._positive_int_config("read_timeout_msec", "rtsp_read_timeout_msec", default=1000)

    def _read_timeout_sec(self) -> float:
        return max(0.05, self._read_timeout_msec() / 1000.0)

    def _reconnect_interval_sec(self) -> float:
        try:
            value = float(self.config.get("reconnect_interval_sec", self.config.get("rtsp_reconnect_interval_sec", 0.25)))
        except (TypeError, ValueError):
            value = 0.25
        return max(0.01, value)

    def _positive_int_config(self, key: str, alias: str, *, default: int) -> int:
        try:
            value = int(self.config.get(key, self.config.get(alias, default)))
        except (TypeError, ValueError):
            value = default
        return max(50, value)

    @staticmethod
    def _capture_is_opened(cap: Any | None) -> bool:
        try:
            return bool(cap is not None and cap.isOpened())
        except Exception:
            return False

    @staticmethod
    def _release(cap: Any | None) -> None:
        if cap is None:
            return
        try:
            cap.release()
        except Exception:
            pass

    @staticmethod
    def _safe_set(cap: Any, key: Any, value: Any) -> None:
        if key is None:
            return
        try:
            cap.set(key, value)
        except Exception:
            pass
