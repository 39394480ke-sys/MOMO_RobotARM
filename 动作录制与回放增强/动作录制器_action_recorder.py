"""阶段六动作录制器。

录制结果不是简单角度列表，而是包含 joint / tcp / raw / multi-turn /
gripper / replay 元数据的完整可回放记录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from 动作工具_common import (
    JOINT_ORDER,
    MULTI_TURN_JOINTS,
    append_sequence_pose,
    build_empty_sequence,
    compute_tcp_pose_if_possible,
    extract_state,
    load_config,
    normalize_gripper_state,
    normalize_joint_targets,
    normalize_multi_turn_state,
    normalize_raw_present_position,
    now_text,
    refresh_sequence_pose_count,
    state_joint_targets,
)
from 通用_io import atomic_write_json


class ActionRecorder:
    def __init__(self, controller: Any, config: dict[str, Any] | None = None):
        self.controller = controller
        self.config = config or load_config()
        robot = self.config.get("robot", {})
        self.joint_order = list(robot.get("sdk_joint_names", JOINT_ORDER))
        self.multi_turn_joints = list(robot.get("multi_turn_joints", MULTI_TURN_JOINTS))

    def capture_current_pose(self, index: int | None = None, name: str | None = None) -> dict[str, Any]:
        state = extract_state(self.controller)
        joint_targets = state_joint_targets(state, self.joint_order)
        raw_present_position = normalize_raw_present_position(state.get("raw_present_position"))
        tcp_pose = state.get("tcp_pose")
        if self.config.get("recording", {}).get("include_tcp_pose", True):
            tcp_pose = compute_tcp_pose_if_possible(joint_targets, tcp_pose)
        else:
            tcp_pose = None
        multi_turn_state = normalize_multi_turn_state(state, self.multi_turn_joints)
        gripper = normalize_gripper_state(state)

        pose = {
            "index": int(index or 1),
            "name": name or f"pose_{int(index or 1)}",
            "recorded_at": now_text(),
            "duration_sec": float(self.config.get("recording", {}).get("recorded_pose_duration_sec", 0.0)),
            "hold_sec": float(self.config.get("playback", {}).get("default_interval_sec", 0.3)),
            "joint_targets_deg": joint_targets,
            "tcp_pose": tcp_pose,
            "raw_present_position": raw_present_position,
            "multi_turn_state": multi_turn_state,
            "gripper": gripper,
        }
        pose.update(self.build_replay_metadata(pose))
        return pose

    def record_pose_sequence(self, pose_count: int, output_path: str | Path, wait_for_enter: bool = True) -> dict[str, Any]:
        name = Path(output_path).stem
        sequence = build_empty_sequence(name=name, source="teach_mode", config=self.config)
        for index in range(1, int(pose_count) + 1):
            if wait_for_enter:
                input(f"请摆好第 {index} 个姿态后按 Enter 录制...")
            pose = self.capture_current_pose(index=index, name=f"pose_{index}")
            append_sequence_pose(sequence, pose)
            self._print_pose(pose)
        self.save_sequence(sequence, output_path)
        return sequence

    def save_sequence(self, action_payload: dict[str, Any], output_path: str | Path) -> None:
        refresh_sequence_pose_count(action_payload)
        atomic_write_json(output_path, action_payload)

    def build_replay_metadata(self, pose: dict[str, Any]) -> dict[str, Any]:
        joint_targets = normalize_joint_targets(pose.get("joint_targets_deg", {}), self.joint_order)
        multi_turn_state = pose.get("multi_turn_state") or {}
        replay_multi_turn: dict[str, float] = {}
        for joint in self.multi_turn_joints:
            item = multi_turn_state.get(joint, {}) if isinstance(multi_turn_state, dict) else {}
            value = 0.0
            if isinstance(item, dict):
                raw_value = item.get("continuous_raw", item.get("relative_raw", 0.0))
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = 0.0
            replay_multi_turn[joint] = value
        return {
            "replay_joint_targets_deg": joint_targets,
            "replay_multi_turn_continuous_raw": replay_multi_turn,
        }

    def _print_pose(self, pose: dict[str, Any]) -> None:
        print(f"已录制 {pose['name']}：")
        print(f"  关节角度：{pose['joint_targets_deg']}")
        print(f"  夹爪：{pose.get('gripper')}")
        print(f"  TCP：{pose.get('tcp_pose')}")


动作录制器 = ActionRecorder
