"""主体锁定运镜曲线、轨迹与调度测试。"""

from __future__ import annotations

import threading
import tempfile
import time
import unittest
from pathlib import Path

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision.主体锁定运镜_subject_lock import (
    ShapePreservingHermiteCurve,
    build_playback_plan,
    calibration_positions,
    run_target_plan,
    validate_calibration_samples,
    validate_playback_speed,
)
from vision.主体锁定控制器_subject_lock_controller import FineCenterPlanner, SubjectLockController


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def wait(self, seconds: float) -> bool:
        self.now += max(0.0, float(seconds))
        return False


class SubjectLockCurveTest(unittest.TestCase):
    def test_calibration_uses_eleven_points_in_requested_direction(self) -> None:
        self.assertEqual(calibration_positions(-50.0, 50.0), [-50.0, -40.0, -30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertEqual(calibration_positions(20.0, -20.0)[0:2], [20.0, 16.0])

    def test_shape_preserving_curve_hits_knots_without_segment_overshoot(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [
                {"j10_mm": -50.0, "j11_deg": -20.0},
                {"j10_mm": 0.0, "j11_deg": 0.0},
                {"j10_mm": 50.0, "j11_deg": 30.0},
            ]
        )

        self.assertAlmostEqual(curve.evaluate(-50.0), -20.0)
        self.assertAlmostEqual(curve.evaluate(0.0), 0.0)
        self.assertAlmostEqual(curve.evaluate(50.0), 30.0)
        left = [curve.evaluate(-50.0 + index) for index in range(51)]
        right = [curve.evaluate(float(index)) for index in range(51)]
        self.assertTrue(all(-20.0 <= value <= 0.0 for value in left))
        self.assertTrue(all(0.0 <= value <= 30.0 for value in right))

        restored = ShapePreservingHermiteCurve.from_dict(curve.to_dict())
        self.assertAlmostEqual(restored.evaluate(12.5), curve.evaluate(12.5))

    def test_speed_validation_blocks_excessive_j11_velocity(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [
                {"j10_mm": 0.0, "j11_deg": 0.0},
                {"j10_mm": 10.0, "j11_deg": 40.0},
            ]
        )

        result = validate_playback_speed(
            curve,
            start_mm=0.0,
            end_mm=10.0,
            speed_mm_s=5.0,
            max_j11_speed_deg_s=12.0,
            max_j11_accel_deg_s2=30.0,
        )

        self.assertFalse(result["valid"])
        self.assertLess(result["safe_max_speed_mm_s"], 5.0)
        self.assertIn("J11", result["message"])

    def test_calibration_rejects_an_isolated_angle_outlier(self) -> None:
        points = [
            {"j10_mm": float(index), "j11_deg": float(index)}
            for index in range(11)
        ]
        points[5]["j11_deg"] = 18.0

        with self.assertRaisesRegex(ValueError, "异常标定点"):
            validate_calibration_samples(points)

    def test_validation_blocks_targets_outside_joint_limits(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [{"j10_mm": 0.0, "j11_deg": 9.0}, {"j10_mm": 10.0, "j11_deg": 15.0}]
        )

        result = validate_playback_speed(
            curve,
            start_mm=0.0,
            end_mm=10.0,
            speed_mm_s=0.5,
            j11_limits=(-10.0, 10.0),
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["safe_max_speed_mm_s"], 0.0)
        self.assertIn("限位", result["message"])

    def test_linear_lock_curve_has_continuous_start_stop_acceleration(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [{"j10_mm": -20.0, "j11_deg": 5.0}, {"j10_mm": 20.0, "j11_deg": -5.0}]
        )

        result = validate_playback_speed(
            curve,
            start_mm=-20.0,
            end_mm=20.0,
            speed_mm_s=2.0,
            update_hz=60.0,
            max_j11_speed_deg_s=12.0,
            max_j11_accel_deg_s2=30.0,
        )

        self.assertTrue(result["valid"], result)
        self.assertLessEqual(result["metrics"]["max_j10_accel_mm_s2"], 4.0)
        self.assertLessEqual(result["metrics"]["max_j11_accel_deg_s2"], 2.0)

    def test_validation_names_acceleration_only_failure(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [
                {"j10_mm": 0.0, "j11_deg": 0.0},
                {"j10_mm": 4.0, "j11_deg": 0.0},
                {"j10_mm": 6.0, "j11_deg": 8.0},
                {"j10_mm": 10.0, "j11_deg": 8.0},
            ]
        )

        result = validate_playback_speed(
            curve,
            start_mm=0.0,
            end_mm=10.0,
            speed_mm_s=2.0,
            max_j11_speed_deg_s=12.0,
            max_j11_accel_deg_s2=30.0,
        )

        self.assertFalse(result["valid"])
        self.assertLessEqual(result["metrics"]["max_j11_speed_deg_s"], 12.0)
        self.assertIn("加速度不平滑", result["message"])


class SubjectLockPlaybackTest(unittest.TestCase):
    def test_plan_contains_synchronized_j10_j11_targets(self) -> None:
        curve = ShapePreservingHermiteCurve.from_points(
            [{"j10_mm": 0.0, "j11_deg": 10.0}, {"j10_mm": 10.0, "j11_deg": 20.0}]
        )
        plan = build_playback_plan(curve, start_mm=0.0, end_mm=10.0, speed_mm_s=2.0, update_hz=40.0)

        self.assertEqual(plan[0]["targets_deg"], {"j10": 0.0, "j11": 10.0})
        self.assertEqual(plan[-1]["targets_deg"], {"j10": 10.0, "j11": 20.0})
        self.assertTrue(all(set(frame["targets_deg"]) == {"j10", "j11"} for frame in plan))

    def test_absolute_scheduler_does_not_write_after_stop(self) -> None:
        clock = FakeClock()
        stop_event = threading.Event()
        writes: list[dict[str, float]] = []
        plan = [
            {"time_sec": 0.0, "targets_deg": {"j10": 0.0, "j11": 0.0}},
            {"time_sec": 0.025, "targets_deg": {"j10": 0.1, "j11": 0.2}},
            {"time_sec": 0.050, "targets_deg": {"j10": 0.2, "j11": 0.4}},
        ]

        def writer(targets: dict[str, float]) -> dict:
            writes.append(dict(targets))
            stop_event.set()
            return {"ok": True, "data": {"written_joints": list(targets)}}

        stats = run_target_plan(
            plan,
            stop_event=stop_event,
            write_target=writer,
            monotonic=clock.monotonic,
            wait=clock.wait,
        )

        self.assertEqual(len(writes), 1)
        self.assertEqual(stats["write_count"], 1)
        self.assertTrue(stats["stopped"])

    def test_late_scheduler_drops_frames_instead_of_bursting_old_targets(self) -> None:
        clock = FakeClock()
        stop_event = threading.Event()
        writes: list[float] = []
        plan = [
            {"time_sec": index * 0.025, "targets_deg": {"j10": float(index), "j11": 0.0}}
            for index in range(5)
        ]

        def writer(targets: dict[str, float]) -> dict:
            writes.append(targets["j10"])
            if len(writes) == 1:
                clock.now += 0.040
            return {"ok": True}

        stats = run_target_plan(
            plan,
            stop_event=stop_event,
            write_target=writer,
            monotonic=clock.monotonic,
            wait=clock.wait,
        )

        self.assertEqual(writes, [0.0, 3.0, 4.0])
        self.assertEqual(stats["skipped_tick_count"], 2)

    def test_wait_overshoot_never_sends_a_future_target_early(self) -> None:
        clock = FakeClock()
        stop_event = threading.Event()
        writes: list[tuple[float, float]] = []
        overshot = False

        def wait(seconds: float) -> bool:
            nonlocal overshot
            clock.now += max(0.0, seconds)
            if seconds > 0.0 and not overshot:
                clock.now += 0.015
                overshot = True
            return False

        plan = [
            {"time_sec": index * 0.025, "targets_deg": {"j10": float(index), "j11": 0.0}}
            for index in range(5)
        ]
        run_target_plan(
            plan,
            stop_event=stop_event,
            write_target=lambda targets: writes.append((targets["j10"], clock.now)) or {"ok": True},
            monotonic=clock.monotonic,
            wait=wait,
        )

        self.assertNotIn(1.0, [target for target, _ in writes])
        target_two_time = next(at for target, at in writes if target == 2.0)
        self.assertGreaterEqual(target_two_time, 0.050)


class FineCenterPlannerTest(unittest.TestCase):
    def test_fine_center_respects_speed_acceleration_and_limits(self) -> None:
        planner = FineCenterPlanner(
            initial_j11_deg=0.0,
            sign=1.0,
            max_speed_deg_s=5.0,
            max_accel_deg_s2=15.0,
            min_j11_deg=-1.0,
            max_j11_deg=1.0,
        )

        first = planner.step(1.0, dt=0.025)
        self.assertAlmostEqual(first["velocity_deg_s"], 0.375)
        self.assertAlmostEqual(first["target_deg"], 0.009375)
        for _ in range(100):
            last = planner.step(1.0, dt=0.025)
        self.assertLessEqual(last["target_deg"], 1.0)
        self.assertTrue(last["at_limit"])

        held = planner.step(0.0, dt=0.025, hold=True)
        self.assertEqual(held["velocity_deg_s"], 0.0)
        self.assertEqual(held["target_deg"], last["target_deg"])


class SubjectLockControllerTest(unittest.TestCase):
    def test_calibration_move_keeps_correcting_pan_from_live_vision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writes: list[dict[str, float]] = []
            frame_id = 0

            def latest() -> dict:
                nonlocal frame_id
                frame_id += 1
                return {
                    "frame_id": frame_id,
                    "detected": True,
                    "has_target": True,
                    "smoothed_offset": {"valid": True, "ndx": 0.2, "ndy": -0.2},
                }

            controller = SubjectLockController(
                Path(directory),
                latest_provider=latest,
                state_provider=lambda: {"j10": 0.0, "j11": 0.0},
                stream_writer=lambda targets: writes.append(dict(targets)) or {"ok": True},
                stream_sync=lambda: {"ok": True},
                dry_run=False,
            )
            pan_planner = FineCenterPlanner(
                initial_j11_deg=0.0,
                sign=1.0,
                max_speed_deg_s=5.0,
                max_accel_deg_s2=15.0,
                min_j11_deg=-360.0,
                max_j11_deg=360.0,
            )
            tilt_planner = FineCenterPlanner(
                initial_j11_deg=0.0,
                sign=1.0,
                max_speed_deg_s=5.0,
                max_accel_deg_s2=15.0,
                min_j11_deg=-180.0,
                max_j11_deg=180.0,
            )

            controller._run_plan(
                [
                    {"time_sec": 0.0, "targets_deg": {"j10": 0.0, "j11": 0.0}},
                    {"time_sec": 0.001, "targets_deg": {"j10": 0.1, "j11": 0.0}},
                ],
                require_vision=True,
                center_planners={"j11": pan_planner, "j13": tilt_planner},
            )

            self.assertTrue(writes)
            self.assertTrue(all(write["j11"] > 0.0 for write in writes))
            self.assertGreater(writes[-1]["j11"], writes[0]["j11"])
            self.assertTrue(all(write["j13"] < 0.0 for write in writes))
            self.assertLess(writes[-1]["j13"], writes[0]["j13"])

    def test_calibration_records_eleven_points_and_saves_blockable_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = {"j10": 0.0, "j11": 0.0, "j12": 10.0, "j13": 20.0, "j14": 30.0, "j15": 40.0}
            writes: list[dict[str, float]] = []
            sync_count = 0
            frame_id = 0

            def latest() -> dict:
                nonlocal frame_id
                frame_id += 1
                return {
                    "frame_id": frame_id,
                    "timestamp": time.time(),
                    "detected": True,
                    "has_target": True,
                    "target_source": "manual_tracker",
                    "camera": {"width": 640, "height": 360},
                    "smoothed_offset": {"valid": True, "ndx": 0.0, "ndy": 0.0},
                }

            def write(targets: dict[str, float]) -> dict:
                writes.append(dict(targets))
                current.update(targets)
                return {"ok": True, "data": {"written_joints": list(targets)}}

            def sync() -> dict:
                nonlocal sync_count
                sync_count += 1
                return {"ok": True}

            controller = SubjectLockController(
                Path(directory),
                latest_provider=latest,
                state_provider=lambda: dict(current),
                stream_writer=write,
                stream_sync=sync,
                dry_run=False,
                config={"stable_sec": 0.0, "center_timeout_sec": 0.2, "control_update_hz": 40.0},
            )
            controller.start_calibration("玩偶轨迹", 0.0, 0.1, 0.2)
            deadline = time.time() + 3.0
            while controller.get_status()["running"] and time.time() < deadline:
                time.sleep(0.01)

            status = controller.get_status()
            self.assertFalse(status["running"])
            self.assertEqual(status["phase"], "ready")
            self.assertEqual(status["calibration_point_count"], 11)
            self.assertEqual(sync_count, 1)
            self.assertTrue(all(set(item).issubset({"j10", "j11", "j13"}) for item in writes))
            profiles = controller.list_profiles()
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["schema"], "subject_lock_v1")
            self.assertEqual(profiles[0]["name"], "玩偶轨迹")
            profile = controller.load_profile(profiles[0]["profile_id"])
            self.assertEqual(profile["controlled_joints"], ["j10", "j11", "j13"])
            self.assertIn("tilt_curve", profile)
            current.update({"j10": 0.0, "j11": 0.0, "j12": 15.0})
            with self.assertRaisesRegex(ValueError, "参考姿态"):
                controller.play(profiles[0]["profile_id"])

    def test_stop_prevents_further_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = {"j10": 0.0, "j11": 0.0}
            writes: list[dict[str, float]] = []
            controller = SubjectLockController(
                Path(directory),
                latest_provider=lambda: {"detected": False, "has_target": False},
                state_provider=lambda: dict(current),
                stream_writer=lambda targets: writes.append(dict(targets)) or {"ok": True, "data": {"written_joints": list(targets)}},
                stream_sync=lambda: {"ok": True},
                dry_run=False,
            )
            controller.start_calibration("stop", 0.0, 10.0, 1.0)
            time.sleep(0.05)
            controller.stop("manual_stop")
            count = len(writes)
            time.sleep(0.08)
            self.assertEqual(len(writes), count)
            self.assertFalse(controller.get_status()["running"])

    def test_target_loss_holds_rail_before_first_calibration_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writes: list[dict[str, float]] = []
            controller = SubjectLockController(
                Path(directory),
                latest_provider=lambda: {"frame_id": 1, "detected": False, "has_target": False},
                state_provider=lambda: {"j10": 0.0, "j11": 0.0},
                stream_writer=lambda targets: writes.append(dict(targets)) or {"ok": True, "data": {"written_joints": list(targets)}},
                stream_sync=lambda: {"ok": True},
                dry_run=False,
                config={"vision_loss_abort_sec": 0.05, "vision_stale_timeout_sec": 0.02},
            )
            controller.start_calibration("lost", 0.0, 0.1, 1.0)
            deadline = time.time() + 1.0
            while controller.get_status()["running"] and time.time() < deadline:
                time.sleep(0.01)

            self.assertEqual(writes, [])
            self.assertEqual(controller.get_status()["phase"], "error")
            self.assertIn("视觉", controller.get_status()["last_error"])


if __name__ == "__main__":
    unittest.main()
