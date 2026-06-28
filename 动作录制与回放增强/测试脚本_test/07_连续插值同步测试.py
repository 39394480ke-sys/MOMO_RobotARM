from __future__ import annotations

from typing import Any, Mapping

import 动作测试路径_test_paths  # noqa: F401

from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import JOINT_ORDER, build_empty_sequence, load_config, refresh_sequence_pose_count


class RecordingController:
    def __init__(self):
        self.current = {joint: 0.0 for joint in JOINT_ORDER}
        self.current.update({"j10": -40.0, "j11": -4.0})
        self.frames: list[dict[str, float]] = []

    def is_dry_run(self) -> bool:
        return True

    def get_state(self) -> dict[str, Any]:
        return {
            "模式": "dry-run",
            "已连接": True,
            "关节角度": dict(self.current),
        }

    def move_joints(self, target_deg_by_joint: Mapping[str, float], multi_turn_targets_continuous_raw=None):
        self.current = {joint: float(target_deg_by_joint[joint]) for joint in JOINT_ORDER}
        self.frames.append(dict(self.current))
        return True, "ok"

    def stop(self):
        return True, "stopped"


class NoSleepSequencePlayer(SequencePlayer):
    def __init__(self, controller, config):
        super().__init__(controller, config)
        self.sleep_calls: list[float] = []
        self.play_pose_calls = 0

    def _sleep_with_controls(self, seconds: float) -> None:
        self.sleep_calls.append(float(seconds))

    def play_pose(self, pose: Mapping[str, Any], duration_sec: float, wait_until_reached: bool = True) -> bool:
        self.play_pose_calls += 1
        return super().play_pose(pose, duration_sec, wait_until_reached)


def make_three_pose_sequence() -> dict[str, Any]:
    sequence = build_empty_sequence("连续插值同步测试", source="test")
    targets = [
        {"j10": 0.0, "j11": 0.0, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
        {"j10": 100.0, "j11": 10.0, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
        {"j10": 50.0, "j11": -20.0, "j12": 5.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
    ]
    poses = []
    for index, target in enumerate(targets, start=1):
        poses.append(
            {
                "index": index,
                "name": f"pose_{index}",
                "duration_sec": 0.4,
                "hold_sec": 0.3,
                "joint_targets_deg": {joint: float(target[joint]) for joint in JOINT_ORDER},
                "replay_joint_targets_deg": {joint: float(target[joint]) for joint in JOINT_ORDER},
                "replay_multi_turn_continuous_raw": {},
                "gripper": {"available": False},
            }
        )
    sequence["poses"] = poses
    return refresh_sequence_pose_count(sequence)


config = load_config()
config["playback"]["continuous_interpolation_default"] = True
config["playback"]["synchronized_segment_timing"] = True
config["playback"]["auto_duration_from_distance"] = False
config["playback"]["update_hz"] = 10.0
config["safety"]["max_single_step_deg"] = 1000.0

controller = RecordingController()
player = NoSleepSequencePlayer(controller, config)
sequence = make_three_pose_sequence()
ok = player.play(sequence)
assert ok is True
assert player.play_pose_calls == 0

assert all(call < 0.3 for call in player.sleep_calls), player.sleep_calls

first_segment_frames = controller.frames[:4]
assert first_segment_frames[0]["j10"] == -30.0
assert first_segment_frames[0]["j11"] == -3.0
assert first_segment_frames[-1]["j10"] == 0.0
assert first_segment_frames[-1]["j11"] == 0.0

ab_frames = controller.frames[4:8]
assert len(ab_frames) >= 3, ab_frames
for frame in ab_frames:
    j10_ratio = frame["j10"] / 100.0
    j11_ratio = frame["j11"] / 10.0
    assert abs(j10_ratio - j11_ratio) < 1e-9, frame
assert ab_frames[-1]["j10"] == 100.0
assert ab_frames[-1]["j11"] == 10.0

print("连续插值同步测试通过")
