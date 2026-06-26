"""阶段六测试共用动作构造工具。"""

from __future__ import annotations

from typing import Any

import 动作测试路径_test_paths  # noqa: F401

from 动作工具_common import JOINT_ORDER, MULTI_TURN_JOINTS, build_empty_sequence, refresh_sequence_pose_count


def make_test_sequence(name: str = "测试动作") -> dict[str, Any]:
    """生成当前导轨版 schema 的最小可回放动作。"""

    sequence = build_empty_sequence(name, source="test")
    targets = [
        {"j10": 0.0, "j11": 0.0, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
        {"j10": 4.0, "j11": 8.0, "j12": 6.0, "j13": 10.0, "j14": 4.0, "j15": -6.0},
    ]
    continuous_raw = [
        {"j10": 123.0, "j11": 234.0, "j12": -345.0, "j13": 456.0, "j15": -567.0},
        {"j10": 5678.0, "j11": -6789.0, "j12": 7890.0, "j13": -8901.0, "j15": 9012.0},
    ]
    poses = []
    for index, target in enumerate(targets, start=1):
        replay_raw = {joint: float(continuous_raw[index - 1][joint]) for joint in MULTI_TURN_JOINTS}
        pose = {
            "index": index,
            "name": f"pose_{index}",
            "duration_sec": 0.05,
            "hold_sec": 0.0,
            "joint_targets_deg": {joint: float(target[joint]) for joint in JOINT_ORDER},
            "replay_joint_targets_deg": {joint: float(target[joint]) for joint in JOINT_ORDER},
            "raw_present_position": {joint: int(2000 + index * 10) for joint in JOINT_ORDER},
            "multi_turn_state": {joint: {"continuous_raw": replay_raw[joint]} for joint in MULTI_TURN_JOINTS},
            "replay_multi_turn_continuous_raw": replay_raw,
            "tcp_pose": None,
            "gripper": {"available": False},
        }
        poses.append(pose)
    sequence["poses"] = poses
    return refresh_sequence_pose_count(sequence)
