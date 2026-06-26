"""阶段六动作序列回放器。"""

from __future__ import annotations

import inspect
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from 动作工具_common import (
    DEFAULT_JOINT_SPEED_LIMITS,
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
    normalize_playback_speed,
    refresh_sequence_pose_count,
    state_joint_targets,
    summarize_sequence_payload,
)
from 控制桥接_common import bounded_catmull_rom, build_motion_progress_payload, safe_call_callback, smoothstep01
from 通用_io import read_json_object
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
        sequence = read_json_object(path)
        refresh_sequence_pose_count(sequence)
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
        refresh_sequence_pose_count(prepared)
        for pose in prepared.get("poses", []):
            targets = pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg")
            pose["replay_joint_targets_deg"] = normalize_joint_targets(targets, self.joint_order)
            multi = pose.get("replay_multi_turn_continuous_raw")
            if isinstance(multi, Mapping) and multi:
                pose["replay_multi_turn_continuous_raw"] = {
                    joint: float(multi[joint])
                    for joint in self.multi_turn_joints
                    if joint in multi and multi[joint] is not None
                }
            else:
                pose["replay_multi_turn_continuous_raw"] = {}
        return prepared

    def play(self, sequence: Mapping[str, Any], loop: bool = False, speed: float = 1.0) -> bool:
        speed = normalize_playback_speed(speed)
        self.validate_sequence(sequence)
        sequence = self.prepare_sequence_for_replay(sequence)
        self.current_sequence_name = str(sequence.get("name", "未命名动作"))
        self.stopped = False
        self.paused = False
        self.print_summary(sequence)
        self.logger.log("play_start", mode=self._mode_name(), action_name=self.current_sequence_name, loop=loop, speed=speed)

        if is_real_mode_controller(self.controller) and self.config.get("safety", {}).get("require_confirm_before_real_replay", True):
            confirm = input("真实模式会移动机械臂。请输入“我确认机械臂周围安全”继续：")
            if confirm.strip() != "我确认机械臂周围安全":
                self.logger.log("play_cancelled", action_name=self.current_sequence_name, reason="真实模式未确认")
                print("未确认安全，已取消回放。")
                return False

        poses = list(sequence["poses"])
        cinematic_cfg = sequence.get("cinematic") if isinstance(sequence.get("cinematic"), Mapping) else {}
        pass_through = bool(cinematic_cfg.get("pass_through", False))
        start_index = 0
        if self.config.get("playback", {}).get("return_to_first_pose_before_replay", True):
            first_pose = poses[0]
            first_duration = self._duration_for_pose(first_pose, speed)
            self.logger.log(
                "return_to_first_pose",
                mode=self._mode_name(),
                action_name=self.current_sequence_name,
                pose_index=first_pose.get("index"),
                duration_sec=first_duration,
            )
            if not self.play_pose(first_pose, first_duration, wait_until_reached=True):
                return False
            if not pass_through:
                self._sleep_with_controls(self._hold_duration(first_pose, sequence, speed))
            start_index = 1

        if pass_through and not loop:
            completed = self._play_cinematic_pass_through(poses, start_index, speed)
            if completed:
                self.logger.log("play_complete", action_name=self.current_sequence_name)
                print(f"动作“{self.current_sequence_name}”回放完成。")
            return completed

        first_pass = True
        while True:
            replay_poses = poses[start_index:] if first_pass else poses
            first_pass = False
            if not replay_poses:
                if not loop:
                    break
                replay_poses = poses

            for pose_index, pose in enumerate(replay_poses):
                if self.stopped:
                    self.logger.log("play_stopped", action_name=self.current_sequence_name, pose_index=pose.get("index"))
                    return False
                duration = self._duration_for_pose(pose, speed)
                is_last_pose = pose_index == len(replay_poses) - 1 and not loop
                wait_until_reached = (not pass_through) or is_last_pose
                if not self.play_pose(pose, duration, wait_until_reached=wait_until_reached):
                    return False
                if not pass_through or float(pose.get("hold_sec", 0.0) or 0.0) > 0:
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

    def play_pose(self, pose: Mapping[str, Any], duration_sec: float, wait_until_reached: bool = True) -> bool:
        self._wait_if_paused()
        if self.stopped:
            return False
        targets = normalize_joint_targets(pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg"), self.joint_order)
        multi_raw = pose.get("replay_multi_turn_continuous_raw")
        multi = {
            joint: float(multi_raw[joint])
            for joint in self.multi_turn_joints
            if isinstance(multi_raw, Mapping) and joint in multi_raw and multi_raw[joint] is not None
        }
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
        if wait_until_reached and not self._wait_until_pose_reached(targets, pose):
            return False
        return True

    def _play_cinematic_pass_through(self, poses: list[Mapping[str, Any]], start_index: int, speed: float) -> bool:
        """Play cinematic keyframes as one continuous joint-space spline."""

        if self.stopped:
            return False
        playback_cfg = self.config.get("playback", {})
        update_hz = float(playback_cfg.get("update_hz", 10.0))
        max_step = float(self.config.get("safety", {}).get("max_single_step_deg", 15.0))
        if is_real_mode_controller(self.controller):
            max_step = float(self.config.get("safety", {}).get("real_mode_max_single_step_deg", 5.0))

        if start_index <= 0:
            current_targets = state_joint_targets(extract_state(self.controller), self.joint_order)
            waypoints: list[dict[str, Any]] = [
                {"index": 0, "name": "cinematic_current", "replay_joint_targets_deg": current_targets, "duration_sec": 0.0}
            ]
            waypoints.extend(dict(pose) for pose in poses)
        else:
            previous = max(0, start_index - 1)
            waypoints = [dict(pose) for pose in poses[previous:]]

        if len(waypoints) < 2:
            return True

        targets_by_waypoint = [
            normalize_joint_targets(pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg"), self.joint_order)
            for pose in waypoints
        ]
        segment_steps: list[tuple[int, float]] = []
        for index in range(len(waypoints) - 1):
            start_targets = targets_by_waypoint[index]
            end_targets = targets_by_waypoint[index + 1]
            duration = self._duration(waypoints[index + 1], speed, current=start_targets, targets=end_targets)
            max_delta = max(abs(float(end_targets[joint]) - float(start_targets.get(joint, end_targets[joint]))) for joint in end_targets)
            steps = max(1, int(duration * update_hz + 0.999), int(max_delta / max(0.001, max_step) + 0.999))
            segment_steps.append((steps, duration))

        frame_total = sum(steps for steps, _duration in segment_steps)
        frame_index = 0
        last_frame: dict[str, float] | None = None
        for segment_index, (steps, duration) in enumerate(segment_steps):
            p0 = targets_by_waypoint[max(0, segment_index - 1)]
            p1 = targets_by_waypoint[segment_index]
            p2 = targets_by_waypoint[segment_index + 1]
            p3 = targets_by_waypoint[min(len(targets_by_waypoint) - 1, segment_index + 2)]
            per_frame_sleep = max(0.0, duration / max(1, steps))
            for step in range(1, steps + 1):
                self._wait_if_paused()
                if self.stopped:
                    return False
                frame_index += 1
                t = step / max(1, steps)
                if segment_index == 0 or segment_index == len(segment_steps) - 1:
                    t = smoothstep01(t)
                frame = {
                    joint: bounded_catmull_rom(
                        float(p0.get(joint, p1[joint])),
                        float(p1[joint]),
                        float(p2[joint]),
                        float(p3.get(joint, p2[joint])),
                        t,
                    )
                    for joint in p2
                }
                use_multi = None
                if segment_index == len(segment_steps) - 1 and step == steps:
                    final_pose = waypoints[-1]
                    multi_raw = final_pose.get("replay_multi_turn_continuous_raw")
                    if isinstance(multi_raw, Mapping) and self._controller_accepts_multi_turn():
                        use_multi = {
                            joint: float(multi_raw[joint])
                            for joint in self.multi_turn_joints
                            if joint in multi_raw and multi_raw[joint] is not None
                        }
                ok, message = call_move_joints(self.controller, frame, use_multi)
                self.logger.log(
                    "play_cinematic",
                    mode=self._mode_name(),
                    action_name=self.current_sequence_name,
                    segment_index=segment_index,
                    frame_index=frame_index,
                    frame_count=frame_total,
                    targets_deg=frame,
                    ok=ok,
                    message=message,
                )
                print(f"cinematic frame {frame_index}/{frame_total} -> {frame}")
                if not ok:
                    self.logger.log("limit_or_move_error", pose_index=waypoints[segment_index + 1].get("index"), error=message)
                    print(f"动作停止：{message}")
                    return False
                last_frame = frame
                self._emit_progress(frame, "cinematic_pass_through", pose=waypoints[segment_index + 1], frame_index=frame_index, frame_count=frame_total)
                if frame_index < frame_total and per_frame_sleep > 0:
                    self._sleep_with_controls(per_frame_sleep)

        final_pose = waypoints[-1]
        final_targets = targets_by_waypoint[-1]
        if last_frame is not None and is_real_mode_controller(self.controller):
            if not self._wait_until_pose_reached(final_targets, final_pose):
                return False
        gripper = final_pose.get("gripper")
        if isinstance(gripper, Mapping) and gripper.get("available") is True:
            ok, message = call_set_gripper(self.controller, gripper)
            self.logger.log("gripper", pose_index=final_pose.get("index"), gripper_target=dict(gripper), ok=ok, message=message)
            if not ok:
                print(f"夹爪回放警告：{message}")
        return True

    def print_summary(self, sequence: Mapping[str, Any]) -> None:
        summary = summarize_sequence_payload(sequence)
        print("动作摘要：")
        print(f"  名称：{summary.get('动作名称')}")
        print(f"  姿态数：{summary.get('pose_count', 0)}")
        print(f"  预计总时长：{float(summary.get('总时长', 0.0)):.2f} 秒")
        print(
            f"  包含 raw：{summary.get('是否包含 raw')}，"
            f"TCP：{summary.get('是否包含 tcp_pose')}，"
            f"夹爪：{summary.get('是否包含 gripper')}，"
            f"多圈状态：{summary.get('是否包含 multi_turn_state')}"
        )
        if is_real_mode_controller(self.controller):
            print("  当前是真实模式。第一次建议只回放 1 个 pose 或很小动作。")

    def _duration_for_pose(self, pose: Mapping[str, Any], speed: float) -> float:
        targets = normalize_joint_targets(pose.get("replay_joint_targets_deg") or pose.get("joint_targets_deg"), self.joint_order)
        current = state_joint_targets(extract_state(self.controller), self.joint_order)
        return self._duration(pose, speed, current=current, targets=targets)

    def _duration(
        self,
        pose: Mapping[str, Any],
        speed: float,
        current: Mapping[str, float] | None = None,
        targets: Mapping[str, float] | None = None,
    ) -> float:
        playback_cfg = self.config.get("playback", {})
        duration = float(pose.get("duration_sec", playback_cfg.get("default_duration_sec", 1.5)))
        if bool(playback_cfg.get("auto_duration_from_distance", True)) and current is not None and targets is not None:
            duration = max(duration, self._distance_based_duration(current, targets))
        duration = duration / normalize_playback_speed(speed)
        if is_real_mode_controller(self.controller):
            duration = max(duration, float(playback_cfg.get("real_mode_min_duration_sec", 2.0)))
        return duration

    def _distance_based_duration(self, current: Mapping[str, float], targets: Mapping[str, float]) -> float:
        speed_limits = self.config.get("playback", {}).get("joint_speed_limits", {})
        if not isinstance(speed_limits, Mapping):
            speed_limits = {}
        required = 0.0
        for joint in self.joint_order:
            if joint not in targets:
                continue
            limit = float(speed_limits.get(joint, DEFAULT_JOINT_SPEED_LIMITS.get(joint, 45.0)))
            if limit <= 0:
                continue
            delta = abs(float(targets[joint]) - float(current.get(joint, targets[joint])))
            required = max(required, delta / limit)
        return required

    def _hold_duration(self, pose: Mapping[str, Any], sequence: Mapping[str, Any], speed: float) -> float:
        hold = pose.get("hold_sec", sequence.get("playback", {}).get("default_interval_sec", 0.3))
        return max(0.0, float(hold) / normalize_playback_speed(speed))

    def _wait_until_pose_reached(self, targets: Mapping[str, float], pose: Mapping[str, Any]) -> bool:
        playback_cfg = self.config.get("playback", {})
        if not is_real_mode_controller(self.controller):
            return True
        if not bool(playback_cfg.get("real_mode_wait_until_reached", True)):
            return True

        timeout = max(0.0, float(playback_cfg.get("real_mode_reach_timeout_sec", 12.0)))
        tolerance_deg = max(0.0, float(playback_cfg.get("real_mode_reach_tolerance_deg", 2.0)))
        tolerance_mm = max(0.0, float(playback_cfg.get("real_mode_reach_tolerance_mm", 2.0)))
        deadline = time.time() + timeout
        last_errors: dict[str, float] = {}

        while True:
            self._wait_if_paused()
            if self.stopped:
                return False
            current = state_joint_targets(extract_state(self.controller), self.joint_order)
            last_errors = {
                joint: float(targets[joint]) - float(current.get(joint, 0.0))
                for joint in self.joint_order
                if joint in targets
            }
            reached = all(
                abs(error) <= (tolerance_mm if joint == "j10" else tolerance_deg)
                for joint, error in last_errors.items()
            )
            if reached:
                self.logger.log(
                    "pose_reached",
                    mode=self._mode_name(),
                    action_name=self.current_sequence_name,
                    pose_index=pose.get("index"),
                    errors=last_errors,
                )
                return True
            if time.time() >= deadline:
                worst_joint, worst_error = max(last_errors.items(), key=lambda item: abs(item[1])) if last_errors else ("--", 0.0)
                message = (
                    f"姿态 {pose.get('index')} 未在 {timeout:.1f}s 内到位，"
                    f"最大误差 {worst_joint}={worst_error:+.2f}"
                )
                self.logger.log(
                    "pose_reach_timeout",
                    mode=self._mode_name(),
                    action_name=self.current_sequence_name,
                    pose_index=pose.get("index"),
                    timeout_sec=timeout,
                    errors=last_errors,
                    message=message,
                )
                print(f"动作停止：{message}")
                return False
            time.sleep(0.05)

    def _emit_progress(self, targets_deg: Mapping[str, float], source: str, **extra: Any) -> None:
        payload = build_motion_progress_payload(targets_deg, source, **extra)
        safe_call_callback(self.progress_callback, payload)

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
