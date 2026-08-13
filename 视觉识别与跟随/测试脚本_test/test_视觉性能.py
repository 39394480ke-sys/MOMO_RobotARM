"""视觉处理分辨率与持久化节流测试。"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision.人脸检测_face_detector import FaceDetector
from vision.结果存储_result_store import ResultStore
from vision.视觉引擎_vision_engine import VisionEngine


class VisionPerformanceTest(unittest.TestCase):
    @staticmethod
    def _make_minimal_engine(video_source) -> VisionEngine:
        class FakeStore:
            def __init__(self):
                self.result = {}

            def save_result(self, result):
                self.result = dict(result)

            @staticmethod
            def save_frame(_frame):
                return None

        engine = VisionEngine.__new__(VisionEngine)
        engine.video_source = video_source
        engine.camera_cfg = {"processing_max_width": 640}
        engine.frame_id = 0
        engine._lock = threading.RLock()
        engine.latest_frame = None
        engine.target_mode = "face"
        engine.face_detector = SimpleNamespace(
            available=True,
            backend="fake",
            last_error="",
            detect=lambda _frame: {"available": True, "error": "", "faces": []},
        )
        engine._select_target = lambda _frame, _faces: {
            "has_target": False,
            "target_face": None,
            "target": None,
            "target_source": "none",
            "tracking_state": "idle",
            "confidence": 0.0,
            "message": "",
        }
        engine.offset_calculator = SimpleNamespace(
            empty=lambda width, height: {
                "dx": 0.0,
                "dy": 0.0,
                "ndx": 0.0,
                "ndy": 0.0,
                "desired_center": [width / 2, height / 2],
                "target_center": None,
                "dead_zone_x_norm": 0.05,
                "dead_zone_y_norm": 0.05,
                "in_dead_zone": True,
                "valid": False,
            }
        )
        engine.smoother = SimpleNamespace(
            update=lambda _offset: {"ndx": 0.0, "ndy": 0.0, "valid": False, "kept": False},
            reset=lambda: None,
        )
        engine._latest_gesture = {}
        engine._gesture_every_n_frames = 3
        engine.gesture_detector = SimpleNamespace(
            available=True,
            last_error="",
            detect=lambda _frame: {"available": True, "raw": "", "stable": "", "confidence": 0.0},
        )
        engine.victory_snapshot = SimpleNamespace(
            observe=lambda _gesture: {"enabled": False, "armed": False},
            status=lambda: {"enabled": False, "armed": False},
        )
        engine._fps = 0.0
        engine._last_frame_time = 0.0
        engine.visualizer = SimpleNamespace(draw=lambda source_frame, _result: source_frame)
        engine.store = FakeStore()
        return engine

    def test_processing_frame_is_limited_to_640_width(self) -> None:
        engine = VisionEngine.__new__(VisionEngine)
        engine.camera_cfg = {"processing_max_width": 640}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        resized = engine._prepare_processing_frame(frame)

        self.assertEqual(resized.shape[:2], (360, 640))

    def test_face_detector_uses_smaller_inference_frame_and_maps_bbox_back(self) -> None:
        observed_shapes: list[tuple[int, int]] = []

        class FakeDetector:
            @staticmethod
            def detect(frame):
                observed_shapes.append(frame.shape[:2])
                row = np.array(
                    [[48.0, 27.0, 96.0, 54.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.9]],
                    dtype=np.float32,
                )
                return True, row

        detector = FaceDetector.__new__(FaceDetector)
        detector.available = True
        detector.last_error = ""
        detector.processing_max_width = 480
        detector.detector = FakeDetector()
        detector._ensure_detector = lambda _width, _height: None

        result = detector.detect(np.zeros((360, 640, 3), dtype=np.uint8))

        self.assertEqual(observed_shapes, [(270, 480)])
        self.assertEqual(result["faces"][0]["bbox"], [64.0, 36.0, 128.0, 72.0])
        self.assertEqual(result["faces"][0]["center"], [128.0, 72.0])

    def test_result_store_persists_at_most_once_per_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResultStore(
                {"latest_result_path": "latest.json", "latest_frame_path": "latest.jpg", "persist_hz": 5.0},
                Path(temp_dir),
            )
            with patch("vision.结果存储_result_store.atomic_write_json") as write_json:
                store.save_result({"frame_id": 1})
                store.save_result({"frame_id": 2})

            self.assertEqual(write_json.call_count, 1)
            self.assertEqual(store.get_latest_result()["frame_id"], 2)

    def test_engine_result_carries_source_frame_timing_metadata(self) -> None:
        received_at = time.time() - 0.02
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        class FakeSource:
            source_description = {"source_type": "rtsp", "rtsp_url": "rtsp://example/analysis"}
            last_frame_metadata = {}

            @staticmethod
            def is_opened() -> bool:
                return True

            @staticmethod
            def read_with_metadata():
                return (
                    True,
                    frame,
                    {
                        "source_frame_id": 77,
                        "frame_received_at": received_at,
                        "dropped_source_frames": 12,
                    },
                    "",
                )

        engine = self._make_minimal_engine(FakeSource())

        result = engine.process_once()

        self.assertEqual(result["source_frame_id"], 77)
        self.assertEqual(result["frame_received_at"], received_at)
        self.assertEqual(result["dropped_source_frames"], 12)
        self.assertEqual(result["timestamp"], result["processed_at"])
        self.assertGreaterEqual(result["processing_latency_sec"], 0.02)

    def test_legacy_read_only_source_never_gets_trusted_timing_metadata(self) -> None:
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        class LegacySource:
            source_description = {"source_type": "custom_rtsp"}
            last_frame_metadata = {}

            @staticmethod
            def is_opened() -> bool:
                return True

            @staticmethod
            def read():
                return True, frame, ""

        result = self._make_minimal_engine(LegacySource()).process_once()

        self.assertIsNone(result["source_frame_id"])
        self.assertIsNone(result["frame_received_at"])
        self.assertIsNone(result["processing_latency_sec"])

    def test_camera_unavailable_does_not_count_as_victory_release(self) -> None:
        class UnavailableSource:
            source_description = {"source_type": "rtsp"}
            last_frame_metadata = {}

        engine = self._make_minimal_engine(UnavailableSource())
        observed: list[dict] = []
        snapshot_status = {"enabled": True, "release_required": True, "release_observed": False}
        engine.camera_cfg.update({"width": 640, "height": 360})
        engine.victory_snapshot = SimpleNamespace(
            observe=lambda gesture: observed.append(dict(gesture)) or {},
            status=lambda: dict(snapshot_status),
        )

        result = engine._camera_unavailable_result("stream down")

        self.assertEqual(observed, [])
        self.assertEqual(result["victory_snapshot"], snapshot_status)
        self.assertTrue(result["victory_snapshot"]["release_required"])

    def test_cached_async_gesture_does_not_advance_victory_twice(self) -> None:
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        source_frame_id = 0

        class FakeSource:
            source_description = {"source_type": "rtsp"}
            last_frame_metadata = {}

            @staticmethod
            def is_opened() -> bool:
                return True

            @staticmethod
            def read_with_metadata():
                nonlocal source_frame_id
                source_frame_id += 1
                return True, frame, {
                    "source_frame_id": source_frame_id,
                    "frame_received_at": time.time(),
                }, ""

        samples = [
            ({"available": True, "raw": "Victory", "stable": "Victory", "message": ""}, True, True),
            ({"available": True, "raw": "Victory", "stable": "Victory", "message": "", "cached": True}, False, True),
        ]
        engine = self._make_minimal_engine(FakeSource())
        engine.gesture_processor = SimpleNamespace(
            status=lambda: {"running": True},
            submit=lambda *_args, **_kwargs: True,
            consume=lambda: samples.pop(0),
        )
        observed: list[dict] = []
        engine.victory_snapshot = SimpleNamespace(
            observe=lambda gesture: observed.append(dict(gesture)) or {"enabled": True},
            status=lambda: {"enabled": True},
        )

        engine.process_once()
        engine.process_once()

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["stable"], "Victory")


if __name__ == "__main__":
    unittest.main()
