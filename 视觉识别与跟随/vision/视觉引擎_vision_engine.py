"""视觉引擎：采集、检测、目标选择、偏移、平滑、手势和结果存储。"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .人脸检测_face_detector import FaceDetector
from .偏移计算_offset_calculator import OffsetCalculator
from .可视化_visualizer import Visualizer, make_placeholder_frame
from .平滑滤波_smoothing import OffsetSmoother
from .手势识别_gesture_detector import GestureDetector
from .主体跟踪_object_tracker import ObjectTracker
from .摄像头_source import VideoSource
from .目标选择_target_selector import TargetSelector
from .结果存储_result_store import ResultStore


class VisionEngine:
    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.camera_cfg = dict(self.config.get("camera", {}))
        self.detector_cfg = dict(self.config.get("detector", {}))
        self.gesture_cfg = dict(self.config.get("gesture", {}))
        self.target_cfg = dict(self.config.get("target", {}))
        self.tracker_cfg = dict(self.config.get("tracker", {}))
        self.smoothing_cfg = dict(self.config.get("smoothing", {}))
        self.service_cfg = dict(self.config.get("service", {}))

        self.video_source = VideoSource(self.camera_cfg, self.base_dir)
        self.face_detector = FaceDetector(self.detector_cfg, self.base_dir)
        self.object_tracker = ObjectTracker(
            tracker_type=str(self.tracker_cfg.get("type", "CSRT")),
            max_lost_frames=int(self.tracker_cfg.get("max_lost_frames", 15)),
            min_box_width=int(self.tracker_cfg.get("min_box_width", 20)),
            min_box_height=int(self.tracker_cfg.get("min_box_height", 20)),
        )
        self.target_selector = TargetSelector(self.target_cfg)
        self.offset_calculator = OffsetCalculator(self.target_cfg)
        self.smoother = OffsetSmoother(self.smoothing_cfg)
        self.gesture_detector = GestureDetector(self.gesture_cfg, self.base_dir)
        self.store = ResultStore(self.service_cfg, self.base_dir)
        self.visualizer = Visualizer()

        self.frame_id = 0
        self.started_at = 0.0
        self.target_mode = str(self.target_cfg.get("mode", "face")).strip().lower() or "face"
        self.latest_frame: Any | None = None
        self.manual_reference_bbox: tuple[int, int, int, int] | None = None
        self.manual_reference_area = 0.0
        self.manual_reference_size = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_frame_time = 0.0
        self._fps = 0.0
        self.logger = self._make_logger()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self.get_status()
            self.started_at = time.time()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="vision-engine", daemon=True)
            self._thread.start()
            self.logger.info("视觉引擎已启动。")
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.video_source.close()
        self.logger.info("视觉引擎已停止。")
        return self.get_status()

    def select_manual_target(self, bbox: list[float] | tuple[float, float, float, float]) -> dict[str, Any]:
        with self._lock:
            frame = self.latest_frame.copy() if self.latest_frame is not None and hasattr(self.latest_frame, "copy") else self.latest_frame
        if frame is None:
            return {"ok": False, "message": "当前还没有摄像头画面，无法框选主体。"}
        try:
            ok = self.object_tracker.init(frame, bbox)
        except Exception as exc:
            return {"ok": False, "message": f"初始化手动目标失败：{exc}"}
        if ok:
            self.target_mode = "manual"
            if self.object_tracker.last_bbox:
                self.manual_reference_bbox = self.object_tracker.last_bbox
                size_meta = self._bbox_size_meta(self.object_tracker.last_bbox)
                self.manual_reference_area = size_meta["area"]
                self.manual_reference_size = size_meta["size"]
            self.smoother.reset()
            return {
                "ok": True,
                "message": "手动目标已锁定。",
                "bbox": list(self.object_tracker.last_bbox or bbox),
                "reference_area": round(self.manual_reference_area, 3),
                "reference_size": round(self.manual_reference_size, 3),
                "target_mode": self.target_mode,
            }
        return {"ok": False, "message": self.object_tracker.last_error or "手动目标初始化失败。"}

    def reset_manual_target(self, fallback_mode: str = "face") -> dict[str, Any]:
        self.object_tracker.reset()
        self.manual_reference_bbox = None
        self.manual_reference_area = 0.0
        self.manual_reference_size = 0.0
        self.target_mode = str(fallback_mode or "face").strip().lower()
        if self.target_mode not in {"face", "manual", "hybrid"}:
            self.target_mode = "face"
        self.smoother.reset()
        return {"ok": True, "message": "已取消手动目标。", "target_mode": self.target_mode}

    def get_target_state(self) -> dict[str, Any]:
        latest = self.store.get_latest_result()
        target = latest.get("target") if isinstance(latest.get("target"), dict) else {}
        return {
            "target_mode": self.target_mode,
            "tracker_active": self.object_tracker.active,
            "tracker_type": self.object_tracker.tracker_type,
            "tracker_lost_count": self.object_tracker.lost_count,
            "tracker_last_bbox": list(self.object_tracker.last_bbox) if self.object_tracker.last_bbox else None,
            "manual_reference_bbox": list(self.manual_reference_bbox) if self.manual_reference_bbox else None,
            "manual_reference_area": round(self.manual_reference_area, 3),
            "manual_reference_size": round(self.manual_reference_size, 3),
            "target": target,
            "has_target": bool(latest.get("has_target", latest.get("detected", False))),
            "tracking_state": latest.get("tracking_state", target.get("tracking_state", "idle")),
            "target_source": latest.get("target_source", target.get("source", "none")),
        }

    def process_once(self) -> dict[str, Any]:
        if not self.video_source.is_opened():
            if not self.video_source.open():
                result = self._camera_unavailable_result(self.video_source.last_error)
                self._save_result_and_placeholder(result, self.video_source.last_error)
                return result

        ok, frame, error = self.video_source.read()
        if not ok or frame is None:
            self.video_source.close()
            result = self._camera_unavailable_result(error)
            self._save_result_and_placeholder(result, error)
            return result

        self.frame_id += 1
        height, width = frame.shape[:2]
        with self._lock:
            self.latest_frame = frame.copy()
        now = time.time()
        self._update_fps(now)

        face_result = self.face_detector.detect(frame)
        faces = list(face_result.get("faces", []))
        target_info = self._select_target(frame, faces)
        target_face = target_info.get("target_face")
        target = target_info.get("target")
        detected = bool(target_info.get("has_target", False))

        if detected and isinstance(target, dict):
            offset = self.offset_calculator.calculate(width, height, target.get("center"))
        else:
            offset = self.offset_calculator.empty(width, height)
        smoothed = self.smoother.update(offset if detected else None)
        gesture = self.gesture_detector.detect(frame)

        direction = {
            "horizontal": offset.get("horizontal", "center"),
            "vertical": offset.get("vertical", "center"),
            "combined": offset.get("combined", "center"),
        }
        result = {
            "timestamp": now,
            "frame_id": self.frame_id,
            "detected": detected,
            "has_target": detected,
            "target_source": target_info.get("target_source", "none"),
            "tracking_state": target_info.get("tracking_state", "idle"),
            "target": target,
            "bbox": target.get("bbox") if isinstance(target, dict) else None,
            "center": target.get("center") if isinstance(target, dict) else None,
            "confidence": target_info.get("confidence", 0.0),
            "target_face": target_face,
            "faces": faces,
            "offset": {
                "dx": offset.get("dx", 0.0),
                "dy": offset.get("dy", 0.0),
                "ndx": offset.get("ndx", 0.0),
                "ndy": offset.get("ndy", 0.0),
                "desired_center": offset.get("desired_center"),
                "target_center": offset.get("target_center"),
                "dead_zone_x_norm": offset.get("dead_zone_x_norm"),
                "dead_zone_y_norm": offset.get("dead_zone_y_norm"),
                "in_dead_zone": offset.get("in_dead_zone", True),
                "valid": offset.get("valid", False),
            },
            "smoothed_offset": {
                "ndx": smoothed.get("ndx", 0.0),
                "ndy": smoothed.get("ndy", 0.0),
                "valid": smoothed.get("valid", False),
                "kept": smoothed.get("kept", False),
            },
            "direction": direction,
            "gesture": gesture,
            "fps": round(self._fps, 3),
            "camera": {
                **self.video_source.source_description,
                "available": True,
                "width": int(width),
                "height": int(height),
            },
            "detector": {
                "face_backend": self.face_detector.backend,
                "face_available": bool(face_result.get("available", False)),
                "face_error": str(face_result.get("error", "")),
            },
            "message": target_info.get("message", ""),
        }

        visualized = self.visualizer.draw(frame, result)
        self.store.save_result(result)
        self.store.save_frame(visualized)
        return result

    def get_latest_result(self) -> dict[str, Any]:
        result = self.store.get_latest_result()
        if result:
            return result
        return self._camera_unavailable_result("视觉引擎还没有处理任何画面。")

    def get_latest_frame(self) -> Any | None:
        return self.store.get_latest_frame()

    def get_status(self) -> dict[str, Any]:
        latest = self.store.get_latest_result()
        thread_alive = bool(self._thread and self._thread.is_alive())
        return {
            "running": bool(self._running),
            "thread_alive": thread_alive,
            "started_at": self.started_at,
            "uptime_sec": round(time.time() - self.started_at, 3) if self.started_at else 0.0,
            "frame_id": self.frame_id,
            "fps": round(self._fps, 3),
            "camera": {
                **(self.video_source.source_description or {"source_type": self.camera_cfg.get("source_type", "camera")}),
                "opened": self.video_source.is_opened(),
                "last_error": self.video_source.last_error,
            },
            "face_detector": {
                "available": self.face_detector.available,
                "error": self.face_detector.last_error,
                "model_path": str(self.face_detector.model_path),
            },
            "target": self.get_target_state(),
            "gesture_detector": {
                "available": self.gesture_detector.available,
                "error": self.gesture_detector.last_error,
                "model_path": str(self.gesture_detector.model_path),
            },
            "latest_timestamp": latest.get("timestamp"),
        }

    def _loop(self) -> None:
        interval = 1.0 / max(1.0, float(self.camera_cfg.get("fps", 30)))
        while self._running:
            started = time.time()
            try:
                result = self.process_once()
                if not result.get("camera", {}).get("available", False):
                    time.sleep(0.5)
            except Exception as exc:
                self.logger.exception("视觉处理异常：%s", exc)
                result = self._camera_unavailable_result(f"视觉处理异常：{exc}")
                self._save_result_and_placeholder(result, str(exc))
                time.sleep(0.2)
            elapsed = time.time() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)

    def _camera_unavailable_result(self, message: str) -> dict[str, Any]:
        self.smoother.reset()
        width = int(self.camera_cfg.get("width", 640))
        height = int(self.camera_cfg.get("height", 480))
        offset = self.offset_calculator.empty(width, height)
        return {
            "timestamp": time.time(),
            "frame_id": self.frame_id,
            "detected": False,
            "has_target": False,
            "target_source": "none",
            "tracking_state": "idle",
            "target": None,
            "bbox": None,
            "center": None,
            "confidence": 0.0,
            "target_face": None,
            "faces": [],
            "offset": {
                "dx": 0.0,
                "dy": 0.0,
                "ndx": 0.0,
                "ndy": 0.0,
                "desired_center": offset.get("desired_center"),
                "target_center": None,
                "dead_zone_x_norm": offset.get("dead_zone_x_norm"),
                "dead_zone_y_norm": offset.get("dead_zone_y_norm"),
                "in_dead_zone": True,
                "valid": False,
            },
            "smoothed_offset": {"ndx": 0.0, "ndy": 0.0, "valid": False, "kept": False},
            "direction": {"horizontal": "center", "vertical": "center", "combined": "center"},
            "gesture": {
                "available": self.gesture_detector.available,
                "raw": "",
                "stable": "",
                "confidence": 0.0,
                "stable_frames": 0,
                "message": self.gesture_detector.last_error,
            },
            "fps": 0.0,
            "camera": {
                **(self.video_source.source_description or {"source_type": self.camera_cfg.get("source_type", "camera")}),
                "available": False,
                "error": message,
            },
            "detector": {
                "face_backend": self.face_detector.backend,
                "face_available": self.face_detector.available,
                "face_error": self.face_detector.last_error,
            },
            "message": message or "camera unavailable",
        }

    def _select_target(self, frame: Any, faces: list[dict[str, Any]]) -> dict[str, Any]:
        mode = self.target_mode if self.target_mode in {"face", "manual", "hybrid"} else "face"

        if mode in {"manual", "hybrid"} and self.object_tracker.active:
            tracked = self.object_tracker.update(frame)
            if tracked.get("ok") and tracked.get("bbox"):
                target = self._target_from_bbox(
                    tracked["bbox"],
                    "manual_tracker",
                    1.0,
                    "tracking",
                    reference_area=self.manual_reference_area,
                    reference_size=self.manual_reference_size,
                )
                return {
                    "has_target": True,
                    "target": target,
                    "target_face": None,
                    "target_source": "manual_tracker",
                    "tracking_state": "tracking",
                    "confidence": 1.0,
                    "message": "正在跟踪手动框选主体。",
                }
            return {
                "has_target": False,
                "target": None,
                "target_face": None,
                "target_source": "manual_tracker",
                "tracking_state": "lost",
                "confidence": 0.0,
                "message": "手动框选目标丢失，已停止输出跟随目标。",
            }

        if mode in {"face", "hybrid"}:
            selection = self.target_selector.select(faces)
            target_face = selection.get("target_face")
            if bool(selection.get("detected")) and isinstance(target_face, dict):
                target = self._target_from_bbox(
                    target_face.get("bbox", [0, 0, 0, 0]),
                    "face",
                    float(target_face.get("score", 1.0)),
                    "tracking",
                    center=target_face.get("center"),
                )
                return {
                    "has_target": True,
                    "target": target,
                    "target_face": target_face,
                    "target_source": "face",
                    "tracking_state": "tracking",
                    "confidence": target.get("confidence", 0.0),
                    "message": selection.get("message", "已选择人脸目标。"),
                }
            return {
                "has_target": False,
                "target": None,
                "target_face": None,
                "target_source": "face",
                "tracking_state": "idle",
                "confidence": 0.0,
                "message": selection.get("message", "没有检测到人脸。"),
            }

        return {
            "has_target": False,
            "target": None,
            "target_face": None,
            "target_source": "none",
            "tracking_state": "idle",
            "confidence": 0.0,
            "message": "当前目标模式未启用。",
        }

    @staticmethod
    def _target_from_bbox(
        bbox: list[float] | tuple[float, float, float, float],
        source: str,
        confidence: float,
        tracking_state: str,
        center: list[float] | tuple[float, float] | None = None,
        reference_area: float = 0.0,
        reference_size: float = 0.0,
    ) -> dict[str, Any]:
        x, y, w, h = [float(v) for v in list(bbox)[:4]]
        if center:
            cx, cy = float(center[0]), float(center[1])
        else:
            cx, cy = x + w / 2.0, y + h / 2.0
        size_meta = VisionEngine._bbox_size_meta((x, y, w, h))
        ref_area = max(0.0, float(reference_area))
        ref_size = max(0.0, float(reference_size))
        if ref_size <= 0.0 and ref_area > 0.0:
            ref_size = ref_area ** 0.5
        size_scale = size_meta["size"] / ref_size if ref_size > 0.0 else 1.0
        size_error = size_scale - 1.0 if ref_size > 0.0 else 0.0
        return {
            "source": source,
            "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
            "center": [round(cx, 2), round(cy, 2)],
            "confidence": round(float(confidence), 4),
            "tracking_state": tracking_state,
            "area": round(size_meta["area"], 3),
            "size": round(size_meta["size"], 3),
            "reference_area": round(ref_area, 3),
            "reference_size": round(ref_size, 3),
            "size_scale": round(size_scale, 6),
            "size_error": round(size_error, 6),
        }

    @staticmethod
    def _bbox_size_meta(bbox: list[float] | tuple[float, ...]) -> dict[str, float]:
        _x, _y, w, h = [float(v) for v in list(bbox)[:4]]
        area = max(0.0, w) * max(0.0, h)
        return {"area": area, "size": area ** 0.5 if area > 0.0 else 0.0}

    def _save_result_and_placeholder(self, result: dict[str, Any], message: str) -> None:
        self.store.save_result(result)
        frame = make_placeholder_frame(message or "camera unavailable", int(self.camera_cfg.get("width", 640)), int(self.camera_cfg.get("height", 480)))
        if frame is not None:
            self.store.save_frame(frame)

    def _update_fps(self, now: float) -> None:
        if self._last_frame_time <= 0:
            self._fps = 0.0
        else:
            dt = max(1e-6, now - self._last_frame_time)
            instant = 1.0 / dt
            self._fps = instant if self._fps <= 0 else 0.2 * instant + 0.8 * self._fps
        self._last_frame_time = now

    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger("vision_stage9")
        logger.setLevel(logging.INFO)
        if logger.handlers:
            return logger
        log_path_value = self.service_cfg.get("log_path", "runtime/logs/vision.log")
        log_path = Path(log_path_value)
        if not log_path.is_absolute():
            log_path = self.base_dir / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger
