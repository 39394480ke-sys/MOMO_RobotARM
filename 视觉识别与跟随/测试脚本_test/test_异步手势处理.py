from __future__ import annotations

import threading
import time
import unittest

import numpy as np

from 视觉测试路径_test_paths import ensure_vision_test_paths

ensure_vision_test_paths()

from vision.异步手势处理_async_gesture import AsyncGestureProcessor
from vision.胜利手势拍照_victory_snapshot import VictorySnapshotController


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class AsyncGestureProcessorTest(unittest.TestCase):
    @staticmethod
    def _wait_until(predicate, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.002)
        raise AssertionError("等待异步手势处理超时")

    def test_fixed_cadence_and_latest_slot_never_build_a_queue(self) -> None:
        monotonic = MutableClock(0.0)
        entered = threading.Event()
        release = threading.Event()
        calls: list[int] = []

        class Detector:
            available = True
            last_error = ""

            @staticmethod
            def detect(frame):
                value = int(frame[0, 0, 0])
                calls.append(value)
                if value == 1:
                    entered.set()
                    release.wait(timeout=1.0)
                return {"available": True, "raw": "", "stable": "", "confidence": 0.0, "message": ""}

        processor = AsyncGestureProcessor(
            Detector(),
            {"process_hz": 5.0},
            monotonic=monotonic,
        )
        processor.start()
        try:
            self.assertTrue(processor.submit(np.full((1, 1, 3), 1, np.uint8), source_frame_id=1, frame_received_at=100.0))
            self.assertTrue(entered.wait(1.0))
            self.assertFalse(processor.submit(np.full((1, 1, 3), 9, np.uint8), source_frame_id=9, frame_received_at=100.0))
            monotonic.advance(0.2)
            self.assertTrue(processor.submit(np.full((1, 1, 3), 2, np.uint8), source_frame_id=2, frame_received_at=100.0))
            monotonic.advance(0.2)
            self.assertTrue(processor.submit(np.full((1, 1, 3), 3, np.uint8), source_frame_id=3, frame_received_at=100.0))
            release.set()
            self._wait_until(lambda: len(calls) >= 2)

            self.assertEqual(calls, [1, 3])
            status = processor.status()
            self.assertEqual(status["submitted_frames"], 3)
            self.assertEqual(status["overwritten_frames"], 1)
        finally:
            release.set()
            processor.stop()

    def test_each_completed_sample_is_new_only_once_and_needs_trusted_fresh_metadata(self) -> None:
        clock = MutableClock(100.0)
        completed = threading.Event()

        class Detector:
            available = True
            last_error = ""

            @staticmethod
            def detect(_frame):
                completed.set()
                return {
                    "available": True,
                    "raw": "Victory",
                    "stable": "Victory",
                    "confidence": 0.99,
                    "message": "",
                }

        processor = AsyncGestureProcessor(
            Detector(),
            {"process_hz": 5.0, "stale_timeout_sec": 0.5},
            clock=clock,
        )
        processor.start()
        try:
            processor.submit(np.zeros((2, 2, 3), np.uint8), source_frame_id=7, frame_received_at=99.9)
            self.assertTrue(completed.wait(1.0))
            self._wait_until(lambda: processor.status()["latest_sample_id"] is not None)

            gesture, is_new, valid = processor.consume()
            cached, cached_is_new, cached_valid = processor.consume()

            self.assertTrue(is_new)
            self.assertTrue(valid)
            self.assertFalse(gesture["cached"])
            self.assertFalse(cached_is_new)
            self.assertTrue(cached_valid)
            self.assertTrue(cached["cached"])

            clock.advance(0.5)
            stale, stale_is_new, stale_valid = processor.consume()
            self.assertFalse(stale_is_new)
            self.assertFalse(stale_valid)
            self.assertTrue(stale["stale"])
        finally:
            processor.stop()

    def test_inference_error_does_not_become_a_victory_release(self) -> None:
        completed = threading.Event()

        class Detector:
            available = True
            last_error = ""

            @staticmethod
            def detect(_frame):
                completed.set()
                return {
                    "available": True,
                    "raw": "",
                    "stable": "Victory",
                    "confidence": 0.0,
                    "message": "推理失败",
                }

        processor = AsyncGestureProcessor(Detector(), {"process_hz": 5.0})
        processor.start()
        try:
            now = time.time()
            processor.submit(np.zeros((2, 2, 3), np.uint8), source_frame_id=1, frame_received_at=now)
            self.assertTrue(completed.wait(1.0))
            self._wait_until(lambda: processor.status()["latest_sample_id"] is not None)
            gesture, is_new, valid = processor.consume()

            self.assertTrue(is_new)
            self.assertFalse(valid)
            self.assertEqual(gesture["stable"], "Victory")
        finally:
            processor.stop()

    def test_stable_victory_uses_real_inferences_and_cached_results_do_not_retrigger(self) -> None:
        clock = MutableClock(100.0)
        monotonic = MutableClock(0.0)
        completed = threading.Event()
        raw_values = ["Victory", "Victory", "Victory", "Victory", "Open_Palm"]

        class StableDetector:
            available = True
            last_error = ""
            count = 0

            @classmethod
            def detect(cls, _frame):
                raw = raw_values[cls.count]
                cls.count += 1
                completed.set()
                return {
                    "available": True,
                    "raw": raw,
                    "stable": "Victory" if cls.count >= 4 else "",
                    "confidence": 0.9,
                    "stable_frames": min(cls.count, 4),
                    "message": "",
                }

        captured = threading.Event()
        snapshot = VictorySnapshotController(
            {"enabled": True, "cooldown_sec": 5.0},
            snapshot_client=lambda: captured.set() or {"id": "shot"},
            clock=clock,
        )
        processor = AsyncGestureProcessor(
            StableDetector(),
            {"process_hz": 5.0, "stale_timeout_sec": 0.5},
            clock=clock,
            monotonic=monotonic,
        )
        processor.start()
        try:
            for index in range(4):
                completed.clear()
                processor.submit(
                    np.full((2, 2, 3), index, np.uint8),
                    source_frame_id=index + 1,
                    frame_received_at=clock(),
                )
                self.assertTrue(completed.wait(1.0))
                self._wait_until(lambda: processor.status()["latest_sample_id"] == index + 1)
                gesture, is_new, valid = processor.consume()
                if is_new and valid:
                    snapshot.observe(gesture)
                else:
                    snapshot.status()
                if index < 3:
                    self.assertFalse(captured.is_set())
                monotonic.advance(0.2)
                clock.advance(0.2)

            self.assertTrue(captured.wait(1.0))
            trigger_count = snapshot.status()["trigger_count"]
            for _ in range(20):
                gesture, is_new, valid = processor.consume()
                if is_new and valid:
                    snapshot.observe(gesture)
            self.assertEqual(snapshot.status()["trigger_count"], trigger_count)

            completed.clear()
            processor.submit(
                np.zeros((2, 2, 3), np.uint8),
                source_frame_id=5,
                frame_received_at=clock(),
            )
            self.assertTrue(completed.wait(1.0))
            self._wait_until(lambda: processor.status()["latest_sample_id"] == 5)
            release_gesture, is_new, valid = processor.consume()
            if is_new and valid:
                released = snapshot.observe(release_gesture)
            else:
                released = snapshot.status()
            self.assertTrue(released["release_observed"])
        finally:
            processor.stop()
            snapshot.close()

    def test_blocked_old_worker_prevents_restart_and_cannot_publish_after_stop(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class Detector:
            available = True
            last_error = ""

            @staticmethod
            def detect(_frame):
                entered.set()
                release.wait(timeout=1.0)
                return {"available": True, "raw": "Victory", "stable": "Victory", "message": ""}

        processor = AsyncGestureProcessor(
            Detector(),
            {"process_hz": 5.0, "worker_join_timeout_sec": 0.03},
        )
        try:
            processor.start()
            processor.submit(
                np.zeros((2, 2, 3), np.uint8),
                source_frame_id=1,
                frame_received_at=time.time(),
            )
            self.assertTrue(entered.wait(1.0))

            stopped = processor.stop()
            rejected = processor.start()
            self.assertTrue(stopped["thread_alive"])
            self.assertTrue(stopped["stop_pending"])
            self.assertFalse(rejected["running"])
            self.assertIn("拒绝重新启动", rejected["last_error"])

            release.set()
            assert processor._thread is not None
            processor._thread.join(timeout=1.0)
            self.assertIsNone(processor.status()["latest_sample_id"])
            restarted = processor.start()
            self.assertTrue(restarted["running"])
        finally:
            release.set()
            processor.stop()


if __name__ == "__main__":
    unittest.main()
