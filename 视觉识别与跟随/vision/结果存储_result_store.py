"""latest_result.json 和 latest_frame.jpg 的读写。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


class ResultStore:
    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.latest_result_path = self._resolve_path(str(self.config.get("latest_result_path", "runtime/latest_result.json")))
        self.latest_frame_path = self._resolve_path(str(self.config.get("latest_frame_path", "runtime/latest_frame.jpg")))
        self.save_latest_frame = bool(self.config.get("save_latest_frame", True))
        self._lock = threading.RLock()
        self._latest_result: dict[str, Any] = {}
        self._latest_frame: Any | None = None
        self.latest_result_path.parent.mkdir(parents=True, exist_ok=True)
        self.latest_frame_path.parent.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._latest_result = dict(result)
            tmp_path = self.latest_result_path.with_suffix(self.latest_result_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.latest_result_path)

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
            try:
                return json.loads(self.latest_result_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
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
        if frame is not None and cv2 is not None:
            ok, encoded = cv2.imencode(".jpg", frame)
            if ok:
                return encoded.tobytes()
        if self.latest_frame_path.exists():
            try:
                return self.latest_frame_path.read_bytes()
            except Exception:
                return None
        return None

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.base_dir / path
