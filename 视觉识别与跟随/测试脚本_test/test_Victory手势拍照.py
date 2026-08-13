from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

from 视觉测试路径_test_paths import ensure_vision_test_paths

ensure_vision_test_paths()

from vision.胜利手势拍照_victory_snapshot import VictorySnapshotController
from vision.视觉引擎_vision_engine import VisionEngine


class MutableClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class VictorySnapshotControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.calls = 0
        self.called = threading.Event()

        def snapshot() -> dict:
            self.calls += 1
            self.called.set()
            return {"id": f"shot-{self.calls}"}

        self.controller = VictorySnapshotController(
            {"enabled": True, "cooldown_sec": 5.0},
            snapshot_client=snapshot,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.controller.close()

    def victory(self) -> dict:
        return {"raw": "Victory", "stable": "Victory"}

    def wait_for_capture(self) -> None:
        self.assertTrue(self.called.wait(1.0))
        deadline = time.monotonic() + 1.0
        while self.controller.status()["in_flight"] and time.monotonic() < deadline:
            time.sleep(0.005)

    def test_continuous_victory_only_takes_one_snapshot(self) -> None:
        self.controller.observe(self.victory())
        self.wait_for_capture()
        for _ in range(20):
            self.controller.observe(self.victory())
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.controller.status()["release_required"])

    def test_requires_release_and_cooldown_before_retrigger(self) -> None:
        self.controller.observe(self.victory())
        self.wait_for_capture()
        self.called.clear()
        self.controller.observe({"raw": "", "stable": ""})
        self.controller.observe(self.victory())
        self.assertEqual(self.calls, 1)
        self.clock.advance(5.0)
        self.controller.observe(self.victory())
        self.assertTrue(self.called.wait(1.0))
        self.assertEqual(self.calls, 2)

    def test_other_raw_gesture_counts_as_release_even_while_stable_lags(self) -> None:
        self.controller.observe(self.victory())
        self.wait_for_capture()
        status = self.controller.observe({"raw": "Open_Palm", "stable": "Victory"})
        self.assertTrue(status["release_observed"])

    def test_unstable_victory_does_not_trigger(self) -> None:
        self.controller.observe({"raw": "Victory", "stable": ""})
        self.assertEqual(self.calls, 0)

    def test_feature_is_opt_in_without_configuration(self) -> None:
        controller = VictorySnapshotController(snapshot_client=lambda: {"id": "unexpected"})
        try:
            status = controller.observe(self.victory())
        finally:
            controller.close()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["armed"])

    def test_stop_then_start_restores_snapshot_worker(self) -> None:
        self.controller.observe(self.victory())
        self.wait_for_capture()
        self.controller.observe({"raw": "", "stable": ""})
        self.clock.advance(5.0)

        stopped = self.controller.stop()
        ignored = self.controller.observe(self.victory())

        self.assertFalse(stopped["running"])
        self.assertFalse(stopped["accepting"])
        self.assertFalse(ignored["in_flight"])
        self.assertEqual(self.calls, 1)

        started = self.controller.start()
        self.called.clear()
        self.controller.observe(self.victory())

        self.assertTrue(started["running"])
        self.assertTrue(self.called.wait(1.0))
        self.assertEqual(self.calls, 2)

    def test_close_is_terminal_and_never_enqueues(self) -> None:
        self.controller.close()

        status = self.controller.observe(self.victory())

        self.assertTrue(status["closed"])
        self.assertFalse(status["running"])
        self.assertFalse(status["in_flight"])
        self.assertEqual(self.calls, 0)

    def test_stop_timeout_invalidates_inflight_result_and_rejects_early_restart(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocking_snapshot() -> dict:
            entered.set()
            release.wait(timeout=1.0)
            return {"id": "late-shot"}

        controller = VictorySnapshotController(
            {"enabled": True, "stop_timeout_sec": 0.05},
            snapshot_client=blocking_snapshot,
        )
        try:
            controller.observe(self.victory())
            self.assertTrue(entered.wait(1.0))

            started_at = time.monotonic()
            stopped = controller.stop()
            elapsed = time.monotonic() - started_at
            rejected = controller.start()

            self.assertLess(elapsed, 0.3)
            self.assertTrue(stopped["worker_alive"])
            self.assertTrue(stopped["stop_pending"])
            self.assertFalse(stopped["in_flight"])
            self.assertFalse(rejected["running"])
            self.assertIn("拒绝重新启动", rejected["lifecycle_error"])

            release.set()
            assert controller._worker is not None
            controller._worker.join(timeout=1.0)
            restarted = controller.start()
            self.assertTrue(restarted["running"])
        finally:
            release.set()
            controller.close()

    def test_vision_engine_stop_then_start_restores_victory_controller(self) -> None:
        called = threading.Event()
        snapshots: list[str] = []
        controller = VictorySnapshotController(
            {"enabled": True},
            snapshot_client=lambda: snapshots.append("shot") or called.set() or {"id": "shot"},
        )
        engine = VisionEngine.__new__(VisionEngine)
        engine._lock = threading.RLock()
        engine._running = False
        engine._thread = None
        engine._stop_event = threading.Event()
        engine._stop_event.set()
        engine._run_generation = 0
        engine._lifecycle_error = ""
        engine._thread_join_timeout_sec = 0.2
        engine.started_at = 0.0
        engine.victory_snapshot = controller
        engine.video_source = SimpleNamespace(close=lambda: None)
        engine.logger = SimpleNamespace(info=lambda *_args: None)
        engine.get_status = lambda: {"running": engine._running, "victory_snapshot": controller.status()}
        engine._loop = lambda stop_event, _generation: stop_event.wait()
        try:
            engine.start()
            engine.stop()
            restarted = engine.start()
            controller.observe(self.victory())

            self.assertTrue(restarted["running"])
            self.assertTrue(called.wait(1.0))
            self.assertEqual(snapshots, ["shot"])
        finally:
            engine.stop()
            controller.close()


if __name__ == "__main__":
    unittest.main()
