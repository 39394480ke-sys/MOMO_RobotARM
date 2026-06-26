"""latest_result.json 和 latest_frame.jpg 的读写。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .可视化_visualizer import encode_jpeg
from .路径工具_path_utils import (
    ensure_parent_dirs,
    ensure_project_root_on_path,
    resolve_vision_path,
)

ensure_project_root_on_path()

from 通用_io import atomic_write_json, read_json_object_or_default  # noqa: E402

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


class ResultStore:
    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.latest_result_path = resolve_vision_path(
            str(self.config.get("latest_result_path", "runtime/latest_result.json")),
            self.base_dir,
        )
        self.latest_frame_path = resolve_vision_path(
            str(self.config.get("latest_frame_path", "runtime/latest_frame.jpg")),
            self.base_dir,
        )
        self.save_latest_frame = bool(self.config.get("save_latest_frame", True))
        self._lock = threading.RLock()
        self._latest_result: dict[str, Any] = {}
        self._latest_frame: Any | None = None
        ensure_parent_dirs(self.latest_result_path, self.latest_frame_path)

    def save_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._latest_result = dict(result)
            atomic_write_json(self.latest_result_path, result)

    def save_frame(self, frame: Any) -> None:
        with self._lock:
            self._latest_frame = frame.copy() if hasattr(frame, "copy") else frame
            if self.save_latest_frame and cv2 is not None and frame is not None:
                cv2.imwrite(str(self.latest_frame_path), frame)

    def get_latest_result(self) -> dict[str, Any]:
        with self._lock:
            if self._latest_result:
                return dict(self._latest_result)
        if self.latest_result_path.exists():
            return read_json_object_or_default(self.latest_result_path)
        return {}

    def get_latest_frame(self) -> Any | None:
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy() if hasattr(self._latest_frame, "copy") else self._latest_frame
        if cv2 is not None and self.latest_frame_path.exists():
            return cv2.imread(str(self.latest_frame_path))
        return None

    def latest_frame_bytes(self) -> bytes | None:
        frame = self.get_latest_frame()
        encoded = encode_jpeg(frame)
        if encoded is not None:
            return encoded
        if self.latest_frame_path.exists():
            try:
                return self.latest_frame_path.read_bytes()
            except Exception:
                return None
        return None
