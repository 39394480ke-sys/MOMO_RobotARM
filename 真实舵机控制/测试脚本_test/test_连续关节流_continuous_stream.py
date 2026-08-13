"""连续关节流的确定性时序测试。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import 真实测试路径_test_paths  # noqa: F401
from 控制桥接_common import DEFAULT_MOTION_TUNING, normalize_motion_tuning
from 连续关节流_continuous_joint_stream import run_continuous_joint_stream
from 真实机械臂控制器_real_arm_controller import RealArmController


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += max(0.0, float(seconds))


class FakeStopEvent:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def set(self) -> None:
        self.stopped = True

    def wait(self, timeout: float) -> bool:
        if not self.stopped:
            self.clock.advance(timeout)
        return self.stopped


class ContinuousJointStreamTimingTest(unittest.TestCase):
    def test_motion_tuning_defaults_to_50_hz_and_ignores_legacy_horizon(self) -> None:
        tuning = normalize_motion_tuning({}, {"continuous_target_horizon_s": 1.5})

        self.assertEqual(DEFAULT_MOTION_TUNING["continuous_update_hz"], 50.0)
        self.assertEqual(tuning["continuous_update_hz"], 50.0)
        self.assertNotIn("continuous_target_horizon_s", tuning)

    def test_writer_time_does_not_accumulate_into_tick_period(self) -> None:
        clock = FakeClock()
        stop_event = FakeStopEvent(clock)
        targets: list[float] = []

        def write_target(target_deg: float) -> bool:
            targets.append(target_deg)
            clock.advance(0.005)
            if len(targets) == 4:
                stop_event.set()
            return True

        stats = run_continuous_joint_stream(
            start_deg=0.0,
            direction=1,
            speed_units_s=10.0,
            update_hz=50.0,
            max_step=3.0,
            stop_event=stop_event,
            write_target=write_target,
            monotonic=clock.monotonic,
        )

        self.assertEqual([round(value, 3) for value in targets], [0.2, 0.4, 0.6, 0.8])
        self.assertEqual(stats.tick_count, 4)
        self.assertEqual(stats.write_count, 4)
        self.assertAlmostEqual(stats.mean_interval_ms, 20.0, places=6)
        self.assertAlmostEqual(stats.p95_interval_ms, 20.0, places=6)
        self.assertAlmostEqual(stats.max_interval_ms, 20.0, places=6)
        self.assertAlmostEqual(stats.actual_update_hz, 50.0, places=6)

    def test_overrun_skips_expired_ticks_without_target_catch_up(self) -> None:
        clock = FakeClock()
        stop_event = FakeStopEvent(clock)
        targets: list[float] = []
        write_times: list[float] = []

        def write_target(target_deg: float) -> bool:
            targets.append(target_deg)
            write_times.append(clock.monotonic())
            clock.advance(0.055 if len(targets) == 1 else 0.0)
            if len(targets) == 2:
                stop_event.set()
            return True

        stats = run_continuous_joint_stream(
            start_deg=0.0,
            direction=1,
            speed_units_s=10.0,
            update_hz=50.0,
            max_step=3.0,
            stop_event=stop_event,
            write_target=write_target,
            monotonic=clock.monotonic,
        )

        self.assertEqual([round(value, 3) for value in targets], [0.2, 0.4])
        self.assertEqual([round(value, 3) for value in write_times], [0.02, 0.08])
        self.assertEqual(stats.skipped_tick_count, 2)


class SpyDriver:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.read_one_count = 0
        self.read_all_count = 0
        self.write_count = 0
        self.enable_count = 0
        self.fail_stream_write = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def read_all_present_positions(self) -> dict[str, int]:
        self.read_all_count += 1
        return self.delegate.read_all_present_positions()

    def read_present_position(self, joint_key: str) -> int:
        self.read_one_count += 1
        return self.delegate.read_present_position(joint_key)

    def write_goal_position(self, joint_key: str, goal_raw: int) -> None:
        self.write_count += 1
        self.delegate.write_goal_position(joint_key, goal_raw)

    def write_stream_goal_position(self, joint_key: str, goal_raw: int) -> None:
        self.write_count += 1
        if self.fail_stream_write:
            raise OSError("模拟通信失败")
        self.delegate.write_stream_goal_position(joint_key, goal_raw)

    def write_many_goal_positions(self, goal_raw_by_joint: dict[str, int]) -> None:
        self.write_count += len(goal_raw_by_joint)
        self.delegate.write_many_goal_positions(goal_raw_by_joint)

    def enable_torque(self, joint_key: str | None = None) -> None:
        self.enable_count += 1
        self.delegate.enable_torque(joint_key)


class RealControllerStreamTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        calibration_path = root / "calibration.json"
        calibration = {
            **{
                f"j{index}": {
                    "id": index,
                    "模式": "多圈",
                    "home_present_raw": 0,
                    "phase": 28,
                    "direction": 1,
                    "range_min": 0,
                    "range_max": 0,
                }
                for index in range(10, 16)
            },
        }
        calibration_path.write_text(
            json.dumps(calibration, ensure_ascii=False),
            encoding="utf-8",
        )
        config_path = root / "real.yaml"
        config_path.write_text(
            json.dumps(
                {
                    "transport": {
                        "port": "",
                        "driver_backend": "sdk",
                        "dry_run": True,
                        "gripper_available": False,
                    },
                    "robot": {
                        "variant": "V2",
                        "joint_order": [f"j{index}" for index in range(10, 16)],
                        "joints": [
                            {
                                "key": f"j{index}",
                                "舵机ID": index,
                                "模式": "多圈",
                                "默认角度": 0,
                            }
                            for index in range(10, 16)
                        ],
                    },
                    "calibration": {"path": str(calibration_path)},
                    "files": {"runtime_state": str(root / "runtime.json")},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.controller = RealArmController(config_path)
        self.controller.set_dry_run(True, persist=False)
        self.assertTrue(self.controller.connect().成功)
        self.spy = SpyDriver(self.controller.driver)
        self.controller.driver = self.spy
        self.save_count = 0

        def count_save() -> None:
            self.save_count += 1

        self.controller._save_runtime_state = count_save

    def tearDown(self) -> None:
        self.controller.disconnect()
        self.temp_dir.cleanup()

    def test_stream_frame_only_writes_changed_joint_goal(self) -> None:
        first = self.controller.stream_joint_target("j14", 1.0)
        second = self.controller.stream_joint_target("j14", 1.0)

        self.assertTrue(first.成功, first.消息)
        self.assertTrue(second.成功, second.消息)
        self.assertEqual(self.spy.write_count, 1)
        self.assertEqual(self.spy.read_all_count, 0)
        self.assertEqual(self.save_count, 0)
        self.assertEqual(self.spy.enable_count, 1)

    def test_batch_stream_writes_changed_targets_without_read_or_save(self) -> None:
        first = self.controller.stream_joint_targets({"j11": 1.0, "j13": -1.0})
        second = self.controller.stream_joint_targets({"j11": 1.0, "j13": -1.0})

        self.assertTrue(first.成功, first.消息)
        self.assertTrue(second.成功, second.消息)
        self.assertEqual(set(first.已写入关节), {"j11", "j13"})
        self.assertEqual(second.已写入关节, ())
        self.assertEqual(self.spy.write_count, 2)
        self.assertEqual(self.spy.read_all_count, 0)
        self.assertEqual(self.save_count, 0)

    def test_batch_stream_validation_checks_raw_without_writing_or_reading(self) -> None:
        result = self.controller.validate_stream_joint_targets({"j10": 1.0, "j11": 2.0})

        self.assertTrue(result.成功, result.消息)
        self.assertEqual(set(result.目标raw), {"j10", "j11"})
        self.assertEqual(result.已写入关节, ())
        self.assertEqual(self.spy.write_count, 0)
        self.assertEqual(self.spy.read_all_count, 0)
        self.assertEqual(self.save_count, 0)

    def test_cached_state_uses_commanded_target_without_hardware_read(self) -> None:
        self.assertTrue(self.controller.stream_joint_target("j14", 1.5).成功)

        state = self.controller.get_cached_state()

        self.assertAlmostEqual(state["关节角度"]["j14"], 1.5)
        self.assertEqual(self.spy.read_all_count, 0)

    def test_stream_goal_write_does_not_print_per_frame(self) -> None:
        self.spy.enable_torque("j14")
        self.controller._torque_enabled_joints.add("j14")

        output = io.StringIO()
        with redirect_stdout(output):
            result = self.controller.stream_joint_target("j14", 1.0)

        self.assertTrue(result.成功, result.消息)
        self.assertEqual(output.getvalue(), "")

    def test_stream_finish_reads_and_persists_once(self) -> None:
        self.assertTrue(self.controller.stream_joint_target("j14", 1.0).成功)

        result = self.controller.sync_after_joint_stream()

        self.assertTrue(result.成功, result.消息)
        self.assertEqual(self.spy.read_all_count, 1)
        self.assertEqual(self.save_count, 1)

    def test_real_stream_caps_target_lead_from_present_position(self) -> None:
        self.controller.config["transport"]["dry_run"] = False
        self.controller.calibration_manager.data["_meta"] = {"robot_variant": "V2"}
        self.spy.delegate.present_raw["j14"] = 0

        result = self.controller.stream_joint_target("j14", 10.0, max_target_lead=0.5)

        self.assertTrue(result.成功, result.消息)
        self.assertEqual(self.spy.read_one_count, 1)
        self.assertAlmostEqual(self.controller.runtime_state["goal_joint_targets_deg"]["j14"], 0.5)

    def test_stream_rejects_joint_limit_without_writing(self) -> None:
        result = self.controller.stream_joint_target("j14", 999.0)

        self.assertFalse(result.成功)
        self.assertIn("超出范围", result.消息)
        self.assertEqual(self.spy.write_count, 0)

    def test_stream_rejects_raw_boundary_without_writing(self) -> None:
        entry = self.controller.calibration_manager.get("j14")
        entry["range_min"] = 2048
        entry["range_max"] = 2049

        result = self.controller.stream_joint_target("j14", 1.0)

        self.assertFalse(result.成功)
        self.assertIn("raw", result.消息)
        self.assertEqual(self.spy.write_count, 0)

    def test_stream_rejects_missing_calibration_in_real_mode(self) -> None:
        self.controller.config.setdefault("transport", {})["dry_run"] = False
        self.controller.calibration_manager.data.pop("j14", None)

        result = self.controller.stream_joint_target("j14", 1.0)

        self.assertFalse(result.成功)
        self.assertIn("标定", result.消息)
        self.assertEqual(self.spy.write_count, 0)

    def test_stream_returns_failure_on_communication_error(self) -> None:
        self.spy.fail_stream_write = True

        result = self.controller.stream_joint_target("j14", 1.0)

        self.assertFalse(result.成功)
        self.assertIn("通信失败", result.消息)


if __name__ == "__main__":
    unittest.main()
