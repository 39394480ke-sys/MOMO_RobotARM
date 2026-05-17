"""阶段六动作序列回放器。"""

from __future__ import annotations

import inspect
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from 动作工具_common import (
    JOINT_ORDER,
    MULTI_TURN_JOINTS,
    SCHEMA_VERSION,
    call_move_joints,
    call_set_gripper,
    call_stop,
    extract_state,
    is_real_mode_controller,
    load_config,
    normalize_joint_targets,
    read_json,
    state_joint_targets,
)
from 动作插值器_motion_interpolator import MotionInterpolator
from 动作日志_motion_logger import MotionLogger


class SequencePlayer:
    def __init__(self, controller: Any, config: dict[str, Any] | None = None):
        self.controller = controller
        self.config = config or load_config()
        self.joint_order = list(self.config.get("robot", {}).get("sdk_joint_names", JOINT_ORDER))
        self.multi_turn_joints = list(self.config.get("robot", {}).get("multi_turn_joints", MULTI_TURN_JOINTS))
        self.interpolator = MotionInterpolator()
        self.paused = False
        self.stopped = False
        self.current_sequence_name = ""
        self.logger = MotionLogger(Path(__file__).resolve().parent / self.config["files"]["runtime_log"])
        self._warned_multi_turn_fallback = False
        self.progress_callback = None

    def load_sequence(self, path: str | Path) -> dict[str, Any]:
        sequence = read_json(path)
        self.validate_sequence(sequence)
        return sequence

    def validate_sequence(self, sequence: Mapping[str, Any]) -> bool:
        if not isinstance(sequence, Mapping):
            raise ValueError("动作文件最外层必须是 JSON 对象。")
        if sequence.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"动作 schema_version 必须是 {SCHEMA_VERSION}。")
        if list(sequence.get("joint_order", [])) != self.joint_order:
            raise ValueError(f"动作 joint_order 不匹配，必须是 {self.joint_order}。")
        poses = sequence.get("poses")
        if not isinstance(poses, list) or not poses:
            raise ValueError("动作文件必须包含非空 poses。")
        for pose in poses:
            if not isinstance(pose, Mapping):
                raise ValueError("poses 中每个姿态必须是对象。")
            targets = pose.get("joint_targets_deg") or pose.get("replay_joint_targets_deg")
            normalized = normalize_joint_targets(targets, self.joint_order)
            for joint, value in normalized.items():
                if not isinstance(value, float):
                    raise ValueError(f"{joint} 角度不是数字。")
        return True

    def prepare_sequence_for_replay(self, sequence: Mapping[str, Any]) -> dict[str, Any]:
        prepared = deepcopy(dict(sequence))
        for pose in prepared.get("poses", []):
            targets = pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg")
            pose["replay_joint_targets_deg"] = normalize_joint_targets(targets, self.joint_order)
            multi = pose.get("replay_multi_turn_continuous_raw") or {}
            pose["replay_multi_turn_continuous_raw"] = {
                joint: float(multi.get(joint, 0.0))
                for joint in self.multi_turn_joints
            }
        return prepared

    def play(self, sequence: Mapping[str, Any], loop: bool = False, speed: float = 1.0) -> bool:
        self.validate_sequence(sequence)
        sequence = self.prepare_sequence_for_replay(sequence)
        self.current_sequence_name = str(sequence.get("name", "未命名动作"))
        self.stopped = False
        self.paused = False
        self.print_summary(sequence)
        self.logger.log("play_start", mode=self._mode_name(), action_name=self.current_sequence_name, loop=loop)

        if is_real_mode_controller(self.controller) and self.config.get("safety", {}).get("require_confirm_before_real_replay", True):
            confirm = input("真实模式会移动机械臂。请输入“我确认机械臂周围安全”继续：")
            if confirm.strip() != "我确认机械臂周围安全":
                self.logger.log("play_cancelled", action_name=self.current_sequence_name, reason="真实模式未确认")
                print("未确认安全，已取消回放。")
                return False

        poses = list(sequence["poses"])
        start_index = 0
        if self.config.get("playback", {}).get("return_to_first_pose_before_replay", True):
            first_pose = poses[0]
            first_duration = self._duration(first_pose, speed)
            self.logger.log(
                "return_to_first_pose",
                mode=self._mode_name(),
                action_name=self.current_sequence_name,
                pose_index=first_pose.get("index"),
                duration_sec=first_duration,
            )
            if not self.play_pose(first_pose, first_duration):
                return False
            self._sleep_with_controls(self._hold_duration(first_pose, sequence, speed))
            start_index = 1

        first_pass = True
        while True:
            replay_poses = poses[start_index:] if first_pass else poses
            first_pass = False
            if not replay_poses:
                if not loop:
                    break
                replay_poses = poses

            for pose in replay_poses:
                if self.stopped:
                    self.logger.log("play_stopped", action_name=self.current_sequence_name, pose_index=pose.get("index"))
                    return False
                duration = self._duration(pose, speed)
                if not self.play_pose(pose, duration):
                    return False
                self._sleep_with_controls(self._hold_duration(pose, sequence, speed))
            if not loop or self.stopped:
                break
        self.logger.log("play_complete", action_name=self.current_sequence_name)
        print(f"动作“{self.current_sequence_name}”回放完成。")
        return True

    def pause(self) -> None:
        self.paused = True
        self.logger.log("pause", action_name=self.current_sequence_name)

    def resume(self) -> None:
        self.paused = False
        self.logger.log("resume", action_name=self.current_sequence_name)

    def stop(self) -> None:
        self.stopped = True
        ok, message = call_stop(self.controller)
        self.logger.log("stop", action_name=self.current_sequence_name, ok=ok, message=message)

    def play_pose(self, pose: Mapping[str, Any], duration_sec: float) -> bool:
        self._wait_if_paused()
        if self.stopped:
            return False
        targets = normalize_joint_targets(pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg"), self.joint_order)
        multi = pose.get("replay_multi_turn_continuous_raw") or {}
        multi = {joint: float(multi.get(joint, 0.0)) for joint in self.multi_turn_joints}
        if multi and not self._controller_accepts_multi_turn():
            self._log_multi_turn_fallback_once()
            multi_to_send = None
        else:
            multi_to_send = multi

        max_step = float(self.config.get("safety", {}).get("max_single_step_deg", 15.0))
        if is_real_mode_controller(self.controller):
            max_step = float(self.config.get("safety", {}).get("real_mode_max_single_step_deg", 5.0))
        current = state_joint_targets(extract_state(self.controller), self.joint_order)
        update_hz = float(self.config.get("playback", {}).get("update_hz", 10.0))
        smooth_frames = self.interpolator.interpolate_joints(current, targets, duration_sec, update_hz)
        safety_frames = self.interpolator.split_large_step(current, targets, max_step)
        frames = smooth_frames if len(smooth_frames) >= len(safety_frames) else safety_frames
        per_frame_sleep = max(0.0, duration_sec / max(1, len(frames)))

        for frame_index, frame in enumerate(frames, start=1):
            self._wait_if_paused()
            if self.stopped:
                return False
            use_multi = multi_to_send if frame_index == len(frames) else None
            ok, message = call_move_joints(self.controller, frame, use_multi)
            self.logger.log(
                "play_pose",
                mode=self._mode_name(),
                action_name=self.current_sequence_name,
                pose_index=pose.get("index"),
                frame_index=frame_index,
                frame_count=len(frames),
                targets_deg=frame,
                multi_turn_targets_continuous_raw=use_multi,
                ok=ok,
                message=message,
            )
            print(f"pose {pose.get('index')} frame {frame_index}/{len(frames)} -> {frame}")
            if not ok:
                self.logger.log("limit_or_move_error", pose_index=pose.get("index"), error=message)
                print(f"动作停止：{message}")
                return False
            self._emit_progress(frame, "action_playback", pose=pose, frame_index=frame_index, frame_count=len(frames))
            self._sleep_with_controls(per_frame_sleep)

        gripper = pose.get("gripper")
        if isinstance(gripper, Mapping) and gripper.get("available") is True:
            ok, message = call_set_gripper(self.controller, gripper)
            self.logger.log("gripper", pose_index=pose.get("index"), gripper_target=dict(gripper), ok=ok, message=message)
            if not ok:
                print(f"夹爪回放警告：{message}")
        return True

    def print_summary(self, sequence: Mapping[str, Any]) -> None:
        poses = sequence.get("poses", [])
        total = sum(float(pose.get("duration_sec", 0)) + float(pose.get("hold_sec", 0)) for pose in poses)
        has_raw = any(pose.get("raw_present_position") for pose in poses if isinstance(pose, Mapping))
        has_tcp = any(pose.get("tcp_pose") for pose in poses if isinstance(pose, Mapping))
        has_gripper = any((pose.get("gripper") or {}).get("available") for pose in poses if isinstance(pose, Mapping))
        has_multi = any(pose.get("multi_turn_state") for pose in poses if isinstance(pose, Mapping))
        print("动作摘要：")
        print(f"  名称：{sequence.get('name')}")
        print(f"  姿态数：{len(poses)}")
        print(f"  预计总时长：{total:.2f} 秒")
        print(f"  包含 raw：{has_raw}，TCP：{has_tcp}，夹爪：{has_gripper}，多圈状态：{has_multi}")
        if is_real_mode_controller(self.controller):
            print("  当前是真实模式。第一次建议只回放 1 个 pose 或很小动作。")

    def _duration(self, pose: Mapping[str, Any], speed: float) -> float:
        duration = float(pose.get("duration_sec", self.config.get("playback", {}).get("default_duration_sec", 1.5)))
        duration = duration / max(0.01, float(speed))
        if is_real_mode_controller(self.controller):
            duration = max(duration, float(self.config.get("playback", {}).get("real_mode_min_duration_sec", 2.0)))
        return duration

    def _hold_duration(self, pose: Mapping[str, Any], sequence: Mapping[str, Any], speed: float) -> float:
        hold = pose.get("hold_sec", sequence.get("playback", {}).get("default_interval_sec", 0.3))
        return max(0.0, float(hold) / max(0.01, float(speed)))

    def _emit_progress(self, targets_deg: Mapping[str, float], source: str, **extra: Any) -> None:
        callback = self.progress_callback
        if not callable(callback):
            return
        payload = {
            "source": source,
            "targets_deg": {joint: float(value) for joint, value in targets_deg.items()},
        }
        payload.update(extra)
        try:
            callback(payload)
        except Exception:
            pass

    def _wait_if_paused(self) -> None:
        while self.paused and not self.stopped:
            time.sleep(0.05)

    def _sleep_with_controls(self, seconds: float) -> None:
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end:
            if self.stopped:
                return
            self._wait_if_paused()
            time.sleep(min(0.05, max(0.0, end - time.time())))

    def _controller_accepts_multi_turn(self) -> bool:
        if not hasattr(self.controller, "move_joints"):
            return False
        try:
            signature = inspect.signature(self.controller.move_joints)
        except (TypeError, ValueError):
            return False
        return "multi_turn_targets_continuous_raw" in signature.parameters

    def _log_multi_turn_fallback_once(self) -> None:
        if self._warned_multi_turn_fallback:
            return
        self._warned_multi_turn_fallback = True
        print("当前控制器不支持多圈 continuous_raw 回放，已退化为角度回放。")
        self.logger.log("multi_turn_fallback", action_name=self.current_sequence_name)

    def _mode_name(self) -> str:
        if is_real_mode_controller(self.controller):
            return "真实"
        state = extract_state(self.controller)
        mode = state.get("模式") or getattr(self.controller, "mode", None)
        return str(mode or "dry-run/仿真")


动作回放器 = SequencePlayer
