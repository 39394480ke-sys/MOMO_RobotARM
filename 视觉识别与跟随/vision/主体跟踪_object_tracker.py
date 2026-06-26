"""手动框选主体跟踪器。"""

from __future__ import annotations

from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


TRACKER_FACTORIES: dict[str, tuple[str, str]] = {
    "CSRT": ("TrackerCSRT_create", "当前 OpenCV 不支持 CSRT Tracker，请安装 opencv-contrib-python。"),
    "KCF": ("TrackerKCF_create", "当前 OpenCV 不支持 KCF Tracker，请安装 opencv-contrib-python。"),
    "MOSSE": ("TrackerMOSSE_create", "当前 OpenCV 不支持 MOSSE Tracker。"),
}


def create_tracker(tracker_type: str = "CSRT") -> Any:
    if cv2 is None:
        raise RuntimeError("OpenCV 未安装，无法创建目标跟踪器。")

    tracker_type = tracker_type.upper()
    factory_name, error_message = TRACKER_FACTORIES.get(tracker_type, ("", ""))
    if not factory_name:
        raise ValueError(f"未知 tracker 类型：{tracker_type}")

    legacy = getattr(cv2, "legacy", None)
    for owner in (legacy, cv2):
        if owner is not None and hasattr(owner, factory_name):
            return getattr(owner, factory_name)()

    raise RuntimeError(error_message)


class ObjectTracker:
    def __init__(self, tracker_type: str = "CSRT", max_lost_frames: int = 15, min_box_width: int = 20, min_box_height: int = 20):
        self.tracker_type = str(tracker_type or "CSRT").upper()
        self.max_lost_frames = int(max_lost_frames)
        self.min_box_width = int(min_box_width)
        self.min_box_height = int(min_box_height)
        self.tracker: Any | None = None
        self.active = False
        self.lost_count = 0
        self.last_bbox: tuple[int, int, int, int] | None = None
        self.last_error = ""

    def reset(self) -> None:
        self.tracker = None
        self.active = False
        self.lost_count = 0
        self.last_bbox = None
        self.last_error = ""

    def init(self, frame: Any, bbox: list[float] | tuple[float, float, float, float]) -> bool:
        if frame is None:
            raise ValueError("当前画面为空，无法初始化跟踪器。")
        x, y, w, h = self._sanitize_bbox(frame, bbox)
        if w < self.min_box_width or h < self.min_box_height:
            raise ValueError(f"框选区域太小，至少需要 {self.min_box_width}x{self.min_box_height} 像素。")

        self.tracker = create_tracker(self.tracker_type)
        ok = bool(self.tracker.init(frame, (x, y, w, h)))
        self.active = ok
        self.lost_count = 0
        self.last_bbox = (x, y, w, h)
        self.last_error = "" if ok else "跟踪器初始化失败。"
        return ok

    def update(self, frame: Any) -> dict[str, Any]:
        if not self.active or self.tracker is None:
            return {"ok": False, "bbox": None, "lost_count": self.lost_count, "state": "idle", "error": self.last_error}
        try:
            ok, bbox = self.tracker.update(frame)
        except Exception as exc:
            ok = False
            bbox = None
            self.last_error = f"目标跟踪失败：{exc}"

        if ok and bbox is not None:
            x, y, w, h = self._sanitize_bbox(frame, bbox)
            if w < self.min_box_width or h < self.min_box_height:
                ok = False
                self.last_error = "跟踪框过小，目标可能已丢失。"
            else:
                self.last_bbox = (x, y, w, h)
                self.lost_count = 0
                self.last_error = ""
                return {"ok": True, "bbox": self.last_bbox, "lost_count": 0, "state": "tracking", "error": ""}

        self.lost_count += 1
        if self.lost_count >= self.max_lost_frames:
            self.active = False
        return {"ok": False, "bbox": self.last_bbox, "lost_count": self.lost_count, "state": "lost", "error": self.last_error}

    @staticmethod
    def _sanitize_bbox(frame: Any, bbox: list[float] | tuple[float, ...]) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        x, y, w, h = [float(v) for v in list(bbox)[:4]]
        x = max(0.0, min(float(width - 1), x))
        y = max(0.0, min(float(height - 1), y))
        w = max(0.0, min(float(width) - x, w))
        h = max(0.0, min(float(height) - y, h))
        return int(round(x)), int(round(y)), int(round(w)), int(round(h))
