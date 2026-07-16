"""连续视觉跟随控制律测试。"""

from __future__ import annotations

import unittest
import time

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision.连续跟随_control import ContinuousFollowPlanner
from vision.视觉跟随_controller import VisionFollowController


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

        def sync() -> dict:
            nonlocal sync_count
            sync_count += 1
            return {"ok": True}

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
            latest_provider=lambda: {
                "detected": True,
                "has_target": True,
                "tracking_state": "tracking",
                "smoothed_offset": {"valid": True, "ndx": 0.5, "ndy": -0.5},
            },
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


if __name__ == "__main__":
    unittest.main()
