"""视觉处理分辨率与持久化节流测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision.结果存储_result_store import ResultStore
from vision.视觉引擎_vision_engine import VisionEngine


class VisionPerformanceTest(unittest.TestCase):
    def test_processing_frame_is_limited_to_640_width(self) -> None:
        engine = VisionEngine.__new__(VisionEngine)
        engine.camera_cfg = {"processing_max_width": 640}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        resized = engine._prepare_processing_frame(frame)

        self.assertEqual(resized.shape[:2], (360, 640))

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


if __name__ == "__main__":
    unittest.main()
