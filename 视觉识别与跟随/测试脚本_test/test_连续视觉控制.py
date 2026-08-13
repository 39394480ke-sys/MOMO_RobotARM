"""连续视觉跟随控制律测试。"""

from __future__ import annotations

import threading
import time
import unittest

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision.连续跟随_control import ContinuousFollowPlanner
from vision.视觉跟随_controller import VisionFollowController


def make_vision_result(source_frame_id: int = 1, *, received_at: float | None = None, latency: float = 0.005) -> dict:
    now = time.time()
    frame_received_at = now - latency if received_at is None else float(received_at)
    processed_at = frame_received_at + latency
    return {
        "source_frame_id": source_frame_id,
        "frame_received_at": frame_received_at,
        "processed_at": processed_at,
        "processing_latency_sec": latency,
        "dropped_source_frames": 0,
        "detected": True,
        "has_target": True,
        "tracking_state": "tracking",
        "smoothed_offset": {"valid": True, "ndx": 0.5, "ndy": -0.5},
    }


class ContinuousFollowPlannerTest(unittest.TestCase):
    def make_planner(self) -> ContinuousFollowPlanner:
        return ContinuousFollowPlanner(
            {
                "enabled_follow_joints": ["j11", "j13"],
                "pan_dead_zone_norm": 0.03,
                "tilt_dead_zone_norm": 0.035,
                "pan_resume_zone_norm": 0.05,
                "tilt_resume_zone_norm": 0.055,
                "max_pan_speed_deg_s": 12.0,
                "max_tilt_speed_deg_s": 10.0,
                "pan_accel_deg_s2": 30.0,
                "tilt_accel_deg_s2": 25.0,
                "pan_sign": 1.0,
                "tilt_sign": 1.0,
            },
            {"j11": 0.0, "j13": 0.0},
        )

    def test_acceleration_limits_velocity_and_integrates_real_dt(self) -> None:
        planner = self.make_planner()

        frame = planner.step(1.0, -1.0, dt=0.025)

        self.assertAlmostEqual(frame.velocities_deg_s["j11"], 0.75)
        self.assertAlmostEqual(frame.velocities_deg_s["j13"], -0.625)
        self.assertAlmostEqual(frame.targets_deg["j11"], 0.01875)
        self.assertAlmostEqual(frame.targets_deg["j13"], -0.015625)

    def test_dead_zone_decelerates_but_hard_hold_stops_immediately(self) -> None:
        planner = self.make_planner()
        planner.step(1.0, 1.0, dt=0.1)

        decelerating = planner.step(0.0, 0.0, dt=0.025)
        held = planner.step(1.0, 1.0, dt=0.025, hold_reason="vision_stale")

        self.assertGreater(decelerating.velocities_deg_s["j11"], 0.0)
        self.assertEqual(held.velocities_deg_s["j11"], 0.0)
        self.assertEqual(held.velocities_deg_s["j13"], 0.0)
        self.assertEqual(held.hold_reason, "vision_stale")

    def test_speed_is_capped_and_direction_is_preserved(self) -> None:
        planner = self.make_planner()
        frame = None
        for _ in range(40):
            frame = planner.step(1.0, -1.0, dt=0.025)

        assert frame is not None
        self.assertEqual(frame.velocities_deg_s["j11"], 12.0)
        self.assertEqual(frame.velocities_deg_s["j13"], -10.0)

    def test_manual_tracker_uses_wider_resume_zone(self) -> None:
        planner = self.make_planner()

        frame = planner.step(0.07, 0.07, dt=0.025, manual_tracker=True)

        self.assertEqual(frame.velocities_deg_s["j11"], 0.0)
        self.assertEqual(frame.velocities_deg_s["j13"], 0.0)


class ContinuousFollowControllerTest(unittest.TestCase):
    def test_stream_mode_runs_fixed_loop_and_syncs_once(self) -> None:
        writes: list[dict[str, float]] = []
        sync_count = 0
        source_frame_id = 0

        def sync() -> dict:
            nonlocal sync_count
            sync_count += 1
            return {"ok": True}

        def latest() -> dict:
            nonlocal source_frame_id
            source_frame_id += 1
            return make_vision_result(source_frame_id)

        controller = VisionFollowController(
            {
                "follow": {
                    "command_mode": "stream",
                    "control_update_hz": 40.0,
                    "poll_interval_sec": 0.02,
                    "vision_stale_timeout_sec": 0.25,
                    "enabled_follow_joints": ["j11", "j13"],
                }
            },
            latest_provider=latest,
            dry_run=False,
            initial_state_provider=lambda: {"j11": 0.0, "j13": 0.0},
            stream_writer=lambda targets: writes.append(dict(targets)) or {"ok": True, "data": {"written_joints": list(targets)}},
            stream_sync=sync,
        )

        controller.start()
        time.sleep(0.14)
        status = controller.stop()

        self.assertGreaterEqual(len(writes), 4)
        self.assertEqual(sync_count, 1)
        self.assertEqual(status["control_mode"], "continuous_position_stream")
        self.assertGreater(status["actual_update_hz"], 25.0)
        self.assertIn("p95_interval_ms", status)

    def test_joint_step_rejects_missing_and_repeated_source_metadata(self) -> None:
        payload = make_vision_result(10)
        controller = VisionFollowController(
            {"follow": {"command_mode": "joint_step", "enabled_follow_joints": ["j11", "j13"]}},
            latest_provider=lambda: dict(payload),
            dry_run=True,
        )

        first = controller.step_once()
        repeated = controller.step_once()
        del payload["frame_received_at"]
        missing = controller.step_once()

        self.assertEqual(first["action"], "joint_step")
        self.assertEqual(repeated["action"], "vision_frame_repeated")
        self.assertEqual(repeated["commands"], [])
        self.assertEqual(missing["action"], "vision_metadata_missing")
        self.assertEqual(missing["commands"], [])

    def test_freshness_guard_rejects_old_slow_and_not_updating_frames(self) -> None:
        controller = VisionFollowController(
            {"follow": {"vision_stale_timeout_sec": 0.1}},
            dry_run=True,
        )
        now = time.time()
        stale = make_vision_result(1, received_at=now - 0.2, latency=0.005)
        slow = make_vision_result(2, received_at=now - 0.2, latency=0.2)
        current = make_vision_result(3)

        self.assertEqual(controller._vision_freshness_hold_reason(stale), "vision_frame_stale")
        self.assertEqual(controller._vision_freshness_hold_reason(slow), "vision_processing_stale")
        self.assertEqual(
            controller._vision_freshness_hold_reason(
                current,
                latest_source_seen_at=time.monotonic() - 0.2,
            ),
            "vision_not_updating",
        )

    def test_stream_never_writes_when_processing_latency_is_over_limit(self) -> None:
        writes: list[dict[str, float]] = []

        def slow_latest() -> dict:
            now = time.time()
            return make_vision_result(5, received_at=now - 0.2, latency=0.2)

        controller = VisionFollowController(
            {
                "follow": {
                    "command_mode": "stream",
                    "control_update_hz": 40.0,
                    "poll_interval_sec": 0.01,
                    "vision_stale_timeout_sec": 0.1,
                }
            },
            latest_provider=slow_latest,
            dry_run=False,
            initial_state_provider=lambda: {"j11": 0.0, "j13": 0.0},
            stream_writer=lambda targets: writes.append(dict(targets)) or {"ok": True},
        )

        controller.start()
        time.sleep(0.09)
        status = controller.stop()

        self.assertEqual(writes, [])
        self.assertEqual(status["hold_reason"], "vision_processing_stale")
        self.assertEqual(status["write_count"], 0)
        self.assertEqual(status["last_command"]["response"]["data"]["written_joints"], [])

    def test_start_clears_cached_vision_and_holds_until_first_sample(self) -> None:
        provider_entered = threading.Event()
        release_provider = threading.Event()
        writes: list[dict[str, float]] = []

        def delayed_latest() -> dict:
            provider_entered.set()
            release_provider.wait(timeout=1.0)
            return make_vision_result(102)

        controller = VisionFollowController(
            {
                "follow": {
                    "command_mode": "stream",
                    "control_update_hz": 40.0,
                    "poll_interval_sec": 0.01,
                }
            },
            latest_provider=delayed_latest,
            dry_run=False,
            initial_state_provider=lambda: {"j11": 0.0, "j13": 0.0},
            stream_writer=lambda targets: writes.append(dict(targets)) or {
                "ok": True,
                "data": {"written_joints": list(targets)},
            },
        )
        controller._stream_latest = make_vision_result(101)
        controller._stream_latest_at = time.monotonic()
        controller._stream_latest_key = 101

        controller.start()
        self.assertTrue(provider_entered.wait(1.0))
        time.sleep(0.08)

        self.assertEqual(writes, [])
        self.assertEqual(controller.get_status()["hold_reason"], "vision_metadata_missing")

        release_provider.set()
        deadline = time.monotonic() + 1.0
        while not writes and time.monotonic() < deadline:
            time.sleep(0.01)
        controller.stop()
        self.assertTrue(writes)

    def test_blocked_previous_writer_prevents_restart_and_never_resurrects(self) -> None:
        writer_entered = threading.Event()
        release_writer = threading.Event()
        frame_id = 0
        write_threads: list[int] = []

        def latest() -> dict:
            nonlocal frame_id
            frame_id += 1
            return make_vision_result(frame_id)

        def blocking_writer(targets: dict[str, float]) -> dict:
            write_threads.append(threading.get_ident())
            writer_entered.set()
            release_writer.wait(timeout=1.0)
            return {"ok": True, "data": {"written_joints": list(targets)}}

        controller = VisionFollowController(
            {
                "follow": {
                    "command_mode": "stream",
                    "control_update_hz": 40.0,
                    "poll_interval_sec": 0.01,
                    "thread_join_timeout_sec": 0.05,
                }
            },
            latest_provider=latest,
            dry_run=False,
            initial_state_provider=lambda: {"j11": 0.0, "j13": 0.0},
            stream_writer=blocking_writer,
        )
        try:
            controller.start()
            self.assertTrue(writer_entered.wait(1.0))

            stopped = controller.stop()
            rejected = controller.start()

            self.assertTrue(stopped["thread_alive"])
            self.assertFalse(rejected["running"])
            self.assertEqual(rejected["hold_reason"], "previous_run_still_stopping")
            self.assertIn("拒绝重新启动", rejected["last_error"])

            release_writer.set()
            deadline = time.monotonic() + 1.0
            while controller._worker_threads_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(controller._worker_threads_alive())
            self.assertEqual(len(set(write_threads)), 1)

            restarted = controller.start()
            self.assertTrue(restarted["running"])
            time.sleep(0.06)
        finally:
            release_writer.set()
            controller.stop()


if __name__ == "__main__":
    unittest.main()
