"""所有关节共用同一时间参数，并优先走批量连续位置流。"""

from typing import Any, Mapping
import unittest

import 动作测试路径_test_paths  # noqa: F401

from 动作回放器_sequence_player import SequencePlayer
from 动作轨迹采样_trajectory_sampling import sample_bounded_cinematic
from 动作工具_common import JOINT_ORDER, build_empty_sequence, load_config


class StreamController:
    def __init__(self) -> None:
        self.current = {joint: 0.0 for joint in JOINT_ORDER}
        self.frames: list[dict[str, float]] = []
        self.move_calls = 0

    def is_dry_run(self) -> bool:
        return True

    def get_state(self) -> dict[str, Any]:
        return {"模式": "dry-run", "已连接": True, "关节角度": dict(self.current)}

    def stream_joint_targets(self, targets: Mapping[str, float]):
        self.current = {joint: float(targets[joint]) for joint in JOINT_ORDER}
        self.frames.append(dict(self.current))
        return True, "streamed"

    def move_joints(self, targets: Mapping[str, float], **_kwargs: Any):
        self.move_calls += 1
        return True, "moved"

    def stop(self):
        return True, "stopped"


class NoSleepPlayer(SequencePlayer):
    def _sleep_with_controls(self, _seconds: float) -> None:
        return


class RecordingSleepPlayer(SequencePlayer):
    def __init__(self, controller, config):
        super().__init__(controller, config)
        self.sleep_calls: list[float] = []

    def _sleep_with_controls(self, seconds: float) -> None:
        self.sleep_calls.append(float(seconds))


class SynchronizedPlaybackTest(unittest.TestCase):
    def test_time_parameterized_curve_keeps_velocity_across_unequal_segments(self) -> None:
        points = [{"j11": 0.0}, {"j11": 20.0}, {"j11": 80.0}]
        durations = [1.0, 3.0]
        epsilon = 0.001
        before = sample_bounded_cinematic(points, 0, 1.0 - epsilon, durations)["j11"]
        waypoint = sample_bounded_cinematic(points, 0, 1.0, durations)["j11"]
        after = sample_bounded_cinematic(points, 1, epsilon / 3.0, durations)["j11"]

        velocity_before = (waypoint - before) / epsilon
        velocity_after = (after - waypoint) / epsilon
        self.assertAlmostEqual(velocity_before, velocity_after, delta=0.1)
        self.assertGreater(velocity_before, 1.0)

    def test_all_joints_share_eased_progress_and_stream_batch_writes(self) -> None:
        config = load_config()
        config["playback"]["update_hz"] = 4.0
        config["playback"]["auto_duration_from_distance"] = False
        config["playback"]["continuous_interpolation_default"] = True
        config["playback"]["synchronized_segment_timing"] = True
        config["safety"]["max_single_step_deg"] = 1000.0
        controller = StreamController()
        player = NoSleepPlayer(controller, config)
        sequence = build_empty_sequence("同步", source="test", config=config)
        target = {"j10": 100.0, "j11": 20.0, "j12": -40.0, "j13": 0.0, "j14": 10.0, "j15": 5.0}
        sequence["poses"] = [{"index": 1, "duration_sec": 1.0, "hold_sec": 0.0, "joint_targets_deg": target}]

        self.assertTrue(player.play(sequence))
        self.assertEqual(len(controller.frames), 4)
        self.assertEqual(controller.move_calls, 0)
        for frame in controller.frames:
            progress = frame["j10"] / target["j10"]
            self.assertAlmostEqual(frame["j11"] / target["j11"], progress)
            self.assertAlmostEqual(frame["j12"] / target["j12"], progress)
            self.assertAlmostEqual(frame["j14"] / target["j14"], progress)
        self.assertLess(controller.frames[0]["j10"], 25.0)
        self.assertEqual(controller.frames[-1], target)

    def test_playback_keeps_moving_through_interior_keyframe(self) -> None:
        config = load_config()
        config["playback"]["update_hz"] = 4.0
        config["playback"]["auto_duration_from_distance"] = False
        config["playback"]["continuous_interpolation_default"] = True
        config["playback"]["synchronized_segment_timing"] = True
        config["safety"]["max_single_step_deg"] = 1000.0
        controller = StreamController()
        player = NoSleepPlayer(controller, config)
        sequence = build_empty_sequence("连续通过关键帧", source="test", config=config)
        first = {joint: 0.0 for joint in JOINT_ORDER}
        second = dict(first)
        third = dict(first)
        second["j11"] = 40.0
        third["j11"] = 100.0
        sequence["poses"] = [
            {"index": 1, "duration_sec": 1.0, "hold_sec": 0.0, "joint_targets_deg": first},
            {"index": 2, "duration_sec": 1.0, "hold_sec": 0.0, "joint_targets_deg": second},
            {"index": 3, "duration_sec": 1.0, "hold_sec": 0.0, "joint_targets_deg": third},
        ]

        self.assertTrue(player.play(sequence))
        waypoint_index = next(index for index, frame in enumerate(controller.frames) if frame["j11"] == 40.0)
        before = controller.frames[waypoint_index - 1]["j11"]
        after = controller.frames[waypoint_index + 1]["j11"]
        self.assertLess(before, 40.0)
        self.assertGreater(after, 40.0)
        self.assertGreater(40.0 - before, 1.0)
        self.assertGreater(after - 40.0, 1.0)

    def test_composed_action_honors_holds_without_changing_legacy_actions(self) -> None:
        config = load_config()
        config["playback"]["update_hz"] = 2.0
        config["playback"]["auto_duration_from_distance"] = False
        config["playback"]["continuous_interpolation_default"] = True
        config["playback"]["synchronized_segment_timing"] = True
        config["safety"]["max_single_step_deg"] = 1000.0

        def make_sequence(honor_holds: bool):
            sequence = build_empty_sequence("编排停留", source="test", config=config)
            sequence["playback"].update({"position_before_replay": True, "entry_duration_sec": 1.0})
            sequence["cinematic"] = {"pass_through": True, "honor_keyframe_holds": honor_holds}
            sequence["poses"] = []
            for index, (value, hold) in enumerate(((0.0, 0.37), (20.0, 0.43), (40.0, 0.51)), 1):
                joints = {joint: 0.0 for joint in JOINT_ORDER}
                joints["j11"] = value
                sequence["poses"].append(
                    {"index": index, "duration_sec": 1.0, "hold_sec": hold, "joint_targets_deg": joints}
                )
            return sequence

        composed = RecordingSleepPlayer(StreamController(), config)
        self.assertTrue(composed.play(make_sequence(True)))
        for hold in (0.37, 0.43, 0.51):
            self.assertIn(hold, composed.sleep_calls)

        legacy = RecordingSleepPlayer(StreamController(), config)
        self.assertTrue(legacy.play(make_sequence(False)))
        for hold in (0.37, 0.43, 0.51):
            self.assertNotIn(hold, legacy.sleep_calls)


if __name__ == "__main__":
    unittest.main()
