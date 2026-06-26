"""GUI 和前面阶段控制器之间的统一桥接层。

GUI 只调用 ControllerBridge，不直接写舵机、不直接绕过阶段四安全检查。
"""

from __future__ import annotations

import math
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from gui_app.path_utils import GUI_ROOT, ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    DEFAULT_MOTION_TUNING,
    JOINT_ORDER,
    append_action_pose,
    build_motion_progress_payload,
    build_exception_context,
    check_python_modules,
    clamp_percent,
    clamp_symmetric,
    cinematic_real_speed_percent,
    compute_fk_payload,
    compute_ik_payload,
    compute_tcp_pose_payload,
    current_joints_for_controller,
    install_stage_paths,
    load_action_library,
    load_action_recorder,
    load_calibration_report,
    load_kinematics_model,
    load_pose_manager,
    load_real_controller,
    load_sequence_player,
    load_sim_controller,
    build_recording_sequence,
    list_action_items,
    list_pose_items,
    make_config_resolver,
    normalize_bridge_result,
    normalize_control_mode,
    normalize_joint_key,
    normalize_joint_targets,
    normalize_motion_tuning,
    normalize_motion_speed_percent,
    normalize_robot_state_payload,
    motion_speed_scale,
    play_action_from_library,
    read_controller_state,
    refresh_action_pose_count,
    resolve_base_path,
    result_fail as fail,
    result_ok as ok,
    safe_call_callback,
    sanitize_action_name,
    set_controller_gripper,
    smoothstep01,
    delete_pose_from_manager,
    save_pose_from_state,
    state_tcp_pose,
)
from 通用_io import atomic_write_json, latest_matching_file, log_json_line  # noqa: E402
from gui_app.结果格式化_result_format import result_data


class ControllerBridge:
    """GUI 统一控制入口。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or GUI_ROOT).resolve()
        self.project_root = self.base_dir.parent
        self.config = config
        self._config_resolver = make_config_resolver(self.config, self.base_dir, "GUI")
        self.mode = str(config.get("app", {}).get("default_mode", "dry_run"))
        self.connected = False
        self.controller: Any | None = None
        self.pose_manager: Any | None = None
        self.action_library: Any | None = None
        self.sequence_player: Any | None = None
        self.kinematics_model: Any | None = None
        self.cartesian_controller: Any | None = None
        self.last_error = ""
        self.action_status = "空闲"
        self.serial_port_override: str | None = None
        self.io_lock = threading.RLock()
        self.log_path = resolve_base_path(config.get("app", {}).get("log_path", "运行日志/gui_runtime.log"), self.base_dir)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.motion_speed_percent = normalize_motion_speed_percent(config.get("motion", {}).get("default_speed_percent"))
        self.recording_sequence: dict[str, Any] | None = None
        self.recording_name = ""
        self.recording_source = "gui_record"
        self._joint_command_targets: dict[str, float] = {}
        self._joint_command_updated_at: dict[str, float] = {}
        self.motion_update_callback = None
        self._continuous_jog_stop = threading.Event()
        self._continuous_jog_joint: str | None = None
        install_stage_paths(self.project_root, include_vision=True)

    def set_motion_update_callback(self, callback: Any | None) -> None:
        self.motion_update_callback = callback
        if self.sequence_player is not None:
            self.sequence_player.progress_callback = callback

    def set_motion_speed_percent(self, percent: float) -> dict[str, Any]:
        self.motion_speed_percent = normalize_motion_speed_percent(percent)
        self.config.setdefault("motion", {})["default_speed_percent"] = self.motion_speed_percent
        self._log("info", "set_motion_speed", f"全局速度已设置为 {self.motion_speed_percent:.0f}%。", speed_percent=self.motion_speed_percent)
        return ok("全局速度已更新。", {"speed_percent": self.motion_speed_percent})

    def get_motion_tuning(self) -> dict[str, Any]:
        return ok("运动调参已读取。", self._motion_tuning())

    def set_motion_tuning(self, values: dict[str, Any]) -> dict[str, Any]:
        tuning = self._motion_tuning(values)
        motion = self.config.setdefault("motion", {})
        for key, value in tuning.items():
            motion[key] = value
        self.motion_speed_percent = float(tuning["default_speed_percent"])
        if self.sequence_player is not None:
            try:
                self.sequence_player.config.setdefault("playback", {})["update_hz"] = float(tuning["playback_update_hz"])
            except Exception:
                pass
        self._log("info", "set_motion_tuning", "GUI 运动调参已更新。", **tuning)
        return ok("GUI 运动调参已更新。", tuning)

    def reset_motion_tuning(self) -> dict[str, Any]:
        return self.set_motion_tuning(DEFAULT_MOTION_TUNING)

    def connect(self) -> dict[str, Any]:
        with self.io_lock:
            return self._connect_unlocked()

    def _connect_unlocked(self) -> dict[str, Any]:
        try:
            self._ensure_controller()
            if self.controller is None:
                return fail("控制器创建失败。")
            if hasattr(self.controller, "connect"):
                result = self.controller.connect()
                normalized = normalize_bridge_result(result, "连接完成。")
            else:
                normalized = ok("仿真控制器已就绪。")
            self.connected = bool(normalized["ok"])
            if self.connected:
                self._joint_command_targets.clear()
                self._joint_command_updated_at.clear()
            self._log("info", "connect", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("连接失败", exc)

    def disconnect(self) -> dict[str, Any]:
        with self.io_lock:
            return self._disconnect_unlocked()

    def _disconnect_unlocked(self) -> dict[str, Any]:
        try:
            if self.controller is not None and hasattr(self.controller, "disconnect"):
                result = self.controller.disconnect()
                normalized = normalize_bridge_result(result, "已断开。")
            else:
                normalized = ok("已断开。")
            self.connected = False
            self._joint_command_targets.clear()
            self._joint_command_updated_at.clear()
            self._log("info", "disconnect", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("断开失败", exc)

    def is_connected(self) -> bool:
        if self.controller is not None and hasattr(self.controller, "connected"):
            return bool(getattr(self.controller, "connected"))
        return bool(self.connected)

    def get_mode(self) -> str:
        return self.mode

    def set_mode(self, mode: str) -> dict[str, Any]:
        try:
            mode = normalize_control_mode(mode, simulation_value="simulation")
        except ValueError as exc:
            return fail(str(exc))
        if self.is_connected():
            self.disconnect()
        self.mode = mode
        self.controller = None
        self.sequence_player = None
        self.cartesian_controller = None
        self.connected = False
        self._log("info", "set_mode", f"已切换模式：{mode}", mode=mode)
        return ok(f"已切换模式：{self.mode}", {"mode": self.mode})

    def set_serial_port(self, port: str) -> dict[str, Any]:
        self.serial_port_override = str(port).strip() or None
        return ok("串口设置已更新。", {"port": self.serial_port_override})

    def get_state(self) -> dict[str, Any]:
        with self.io_lock:
            return self._get_state_unlocked()

    def _get_state_unlocked(self) -> dict[str, Any]:
        try:
            self._ensure_controller()
            if self.controller is None:
                return fail("控制器未创建。")
            state = read_controller_state(self.controller, prefer_detailed=True)
            normalized = self._normalize_state(state)
            normalized["tcp_pose"] = state_tcp_pose(self.kinematics_model, normalized.get("joints_deg", {}))
            normalized["mode"] = self.mode
            normalized["connected"] = self.is_connected()
            return ok("状态已刷新。", normalized)
        except Exception as exc:
            return self._exception("读取状态失败", exc)

    def move_joints(self, targets_deg: dict[str, float] | list[float]) -> dict[str, Any]:
        with self.io_lock:
            return self._move_joints_unlocked(targets_deg)

    def _move_joints_unlocked(self, targets_deg: dict[str, float] | list[float]) -> dict[str, Any]:
        try:
            self._ensure_controller()
            if self.controller is None:
                return fail("控制器未创建。")
            targets = normalize_joint_targets(targets_deg)
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints(targets)
            elif hasattr(self.controller, "移动到关节角度"):
                result = self.controller.移动到关节角度([targets[joint] for joint in JOINT_ORDER])
            else:
                return fail("当前控制器不支持关节移动。")
            normalized = normalize_bridge_result(result, "关节移动完成。", {"targets_deg": targets})
            if normalized.get("ok"):
                now = time.monotonic()
                for joint, target in targets.items():
                    self._joint_command_targets[joint] = float(target)
                    self._joint_command_updated_at[joint] = now
            self._log("info" if normalized["ok"] else "error", "move_joints", normalized["message"], targets_deg=targets)
            return normalized
        except Exception as exc:
            return self._exception("关节移动失败", exc)

    def move_joints_smooth(self, targets_deg: dict[str, float] | list[float], label: str = "平滑移动") -> dict[str, Any]:
        with self.io_lock:
            return self._move_joints_smooth_unlocked(targets_deg, label)

    def _move_joints_smooth_unlocked(self, targets_deg: dict[str, float] | list[float], label: str = "平滑移动") -> dict[str, Any]:
        try:
            targets = normalize_joint_targets(targets_deg)
            max_delta = 0.0
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            current = result_data(state_result).get("joints_deg", {})
            for joint, target in targets.items():
                max_delta = max(max_delta, abs(float(target) - float(current.get(joint, 0.0))))
            speed_scale = motion_speed_scale(self.motion_speed_percent)
            max_speed_deg_s = float(self.config.get("motion", {}).get("max_smooth_speed_deg_s", 45.0)) * speed_scale
            duration = max(0.4, max_delta / max(1.0, max_speed_deg_s))
            update_hz = float(self._motion_tuning().get("playback_update_hz", 20.0))
            return self._move_joints_interpolated(targets, duration_s=duration, update_hz=update_hz, label=label)
        except Exception as exc:
            return self._exception("平滑移动失败", exc)

    def move_joint_delta(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        with self.io_lock:
            return self._move_joint_delta_unlocked(joint_key, delta_deg)

    def start_continuous_jog(self, joint_key: str, direction: int, speed_deg_s: float) -> dict[str, Any]:
        try:
            joint_key = normalize_joint_key(joint_key)
            signed_direction = 1 if int(direction) >= 0 else -1
            signed_direction *= self._jog_direction_override(joint_key)
            speed = abs(float(speed_deg_s))
            if speed <= 0:
                return fail("连续速度必须大于 0。")
            tuning = self._motion_tuning()
            update_hz = max(1.0, float(tuning["continuous_update_hz"]))
            horizon_s = max(0.0, float(tuning["continuous_target_horizon_s"]))
            sleep_s = 1.0 / update_hz
            stop_event = threading.Event()
            self._continuous_jog_stop = stop_event
            self._continuous_jog_joint = joint_key

            with self.io_lock:
                self._ensure_controller()
                state_result = self.get_state()
                if not state_result.get("ok"):
                    return state_result
                state_data = result_data(state_result)
                current = state_data.get("joints_deg", {})
                current_deg = float(current.get(joint_key, 0.0))
                start_deg = current_deg

            frame_count = 0
            started_at = time.monotonic()
            last_target = start_deg
            while not stop_event.is_set():
                elapsed = time.monotonic() - started_at
                # Continuous jog must not command a future point far ahead of the
                # current time; otherwise releasing the button can make the servo
                # stop short and the UI appears to jump backward.
                delta = signed_direction * speed * elapsed
                target_deg = start_deg + delta
                precheck = self._precheck_single_joint_target(joint_key, target_deg, last_target, delta)
                if precheck is not None:
                    stop_event.set()
                    self._joint_command_targets.pop(joint_key, None)
                    self._joint_command_updated_at.pop(joint_key, None)
                    if self._continuous_jog_joint == joint_key:
                        self._continuous_jog_joint = None
                    return precheck
                with self.io_lock:
                    result = self.controller.move_joints({joint_key: target_deg})
                    normalized = normalize_bridge_result(
                        result,
                        "连续移动帧完成。",
                        {"joint_key": joint_key, "target_deg": target_deg, "speed_deg_s": speed, "direction": signed_direction},
                    )
                    if not normalized.get("ok"):
                        stop_event.set()
                        self._joint_command_targets.pop(joint_key, None)
                        self._joint_command_updated_at.pop(joint_key, None)
                        if self._continuous_jog_joint == joint_key:
                            self._continuous_jog_joint = None
                        return normalized
                    self._joint_command_targets[joint_key] = float(target_deg)
                    self._joint_command_updated_at[joint_key] = time.monotonic()
                frame_count += 1
                last_target = target_deg
                self._emit_motion_update({joint_key: target_deg}, "continuous_jog", frame_index=frame_count, speed_deg_s=speed, direction=signed_direction)
                if stop_event.wait(sleep_s):
                    break

            duration_s = time.monotonic() - started_at
            with self.io_lock:
                self._joint_command_targets.pop(joint_key, None)
                self._joint_command_updated_at.pop(joint_key, None)
                if self._continuous_jog_joint == joint_key:
                    self._continuous_jog_joint = None
            return ok(
                "连续移动已停止。",
                {
                    "joint_key": joint_key,
                    "target_deg": last_target,
                    "targets_deg": {joint_key: last_target},
                    "duration_s": duration_s,
                    "frames": frame_count,
                    "update_hz": update_hz,
                    "horizon_s": horizon_s,
                },
            )
        except Exception as exc:
            return self._exception("连续移动失败", exc)

    def stop_continuous_jog(self) -> dict[str, Any]:
        self._continuous_jog_stop.set()
        joint_key = self._continuous_jog_joint
        if joint_key:
            self._joint_command_targets.pop(joint_key, None)
            self._joint_command_updated_at.pop(joint_key, None)
        return ok("连续移动停止信号已发送。")

    def move_follow_steps(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        with self.io_lock:
            self._ensure_controller()
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state_data = result_data(state_result)
            current = state_data.get("joints_deg", {})
            targets: dict[str, float] = {}
            responses: list[dict[str, Any]] = []
            max_step = float(self.config.get("safety", {}).get("max_real_step_deg" if self.mode == "real" else "max_gui_step_deg", 5.0))
            for command in commands:
                joint_key = str(command.get("joint_key", ""))
                try:
                    joint_key = normalize_joint_key(joint_key)
                    current_deg = float(targets.get(joint_key, current.get(joint_key, 0.0)))
                    base_deg = self._joint_delta_base_deg(joint_key, current_deg, state_data)
                    if "target_deg" in command:
                        target_deg = float(command.get("target_deg", current_deg))
                        delta = target_deg - current_deg
                    else:
                        delta = clamp_symmetric(float(command.get("delta_deg", 0.0)), max_step)
                        target_deg = (base_deg if base_deg != current_deg else current_deg) + delta
                    precheck = self._precheck_single_joint_target(joint_key, target_deg, current_deg, delta)
                    if precheck is not None:
                        responses.append(precheck)
                        continue
                    targets[joint_key] = float(target_deg)
                    responses.append(ok("待同步执行。", {"joint_key": joint_key, "delta_deg": delta, "current_deg": current_deg, "base_deg": base_deg, "target_deg": target_deg}))
                except Exception as exc:
                    responses.append(fail("跟随命令解析失败。", exc, {"command": command}))
            if any(not bool(item.get("ok")) for item in responses):
                return fail("视觉跟随步进部分失败。", data={"commands": commands, "responses": responses})
            if not targets:
                return ok("无有效视觉跟随目标。", {"commands": commands, "responses": responses})

            move_result = self._move_joints_unlocked(targets)
            ok_all = bool(move_result.get("ok"))
            now = time.monotonic()
            if ok_all:
                for joint, target in targets.items():
                    self._joint_command_targets[joint] = float(target)
                    self._joint_command_updated_at[joint] = now
            message = "视觉跟随同步步进已执行。" if ok_all else "视觉跟随同步步进失败。"
            data = {"commands": commands, "responses": responses, "targets_deg": targets, "move_result": move_result}
            return ok(message, data) if ok_all else fail(message, data=data)

    def _move_joint_delta_unlocked(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        try:
            joint_key = normalize_joint_key(joint_key)
            max_step = float(self.config.get("safety", {}).get("max_real_step_deg" if self.mode == "real" else "max_gui_step_deg", 5.0))
            delta = clamp_symmetric(float(delta_deg), max_step) * self._jog_direction_override(joint_key)
            self._ensure_controller()
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state_data = result_data(state_result)
            current = state_data.get("joints_deg", {})
            current_deg = float(current.get(joint_key, 0.0))
            base_deg = self._joint_delta_base_deg(joint_key, current_deg, state_data)
            target_deg = current_deg + delta
            if base_deg != current_deg:
                target_deg = base_deg + delta
            precheck = self._precheck_single_joint_target(joint_key, target_deg, current_deg, delta)
            if precheck is not None:
                self._log("warning", "move_joint_delta_blocked", precheck["message"], **precheck.get("data", {}))
                return precheck
            tuning = self._motion_tuning()
            duration_s = float(tuning["quick_step_duration_s"])
            frames = int(tuning["quick_step_frames"])
            normalized = self._move_single_joint_interpolated(
                joint_key,
                start_deg=base_deg if base_deg != current_deg else current_deg,
                target_deg=target_deg,
                duration_s=duration_s,
                steps=frames,
                label="关节微调",
                current_joints=current,
                data={"delta_deg": delta, "current_deg": current_deg, "base_deg": base_deg},
            )
            if normalized.get("ok"):
                self._joint_command_targets[joint_key] = float(target_deg)
                self._joint_command_updated_at[joint_key] = time.monotonic()
            self._log(
                "info" if normalized["ok"] else "error",
                "move_joint_delta",
                normalized["message"],
                joint_key=joint_key,
                delta_deg=delta,
                current_deg=current_deg,
                base_deg=base_deg,
                target_deg=target_deg,
            )
            return normalized
        except Exception as exc:
            return self._exception("关节微调失败", exc)

    def set_gripper(self, open_percent: float) -> dict[str, Any]:
        with self.io_lock:
            return self._set_gripper_unlocked(open_percent)

    def _set_gripper_unlocked(self, open_percent: float) -> dict[str, Any]:
        try:
            self._ensure_controller()
            value = clamp_percent(open_percent)
            normalized = set_controller_gripper(
                self.controller,
                value,
                connected=self.is_connected(),
                mode=self.mode,
                real_config_path=self._resolve_config("real_config_path"),
            )
            self._log("info" if normalized["ok"] else "error", "set_gripper", normalized["message"], open_percent=value)
            return normalized
        except Exception as exc:
            return self._exception("夹爪控制失败", exc)

    def home(self) -> dict[str, Any]:
        with self.io_lock:
            return self._home_unlocked()

    def _home_unlocked(self) -> dict[str, Any]:
        try:
            self._ensure_controller()
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "joint_config_by_key") and hasattr(self.controller, "move_joints"):
                targets = {
                    joint: float(self.controller.joint_config_by_key[joint].get("默认角度", 0.0))
                    for joint in JOINT_ORDER
                    if joint in self.controller.joint_config_by_key
                }
                speed_scale = motion_speed_scale(self.motion_speed_percent)
                normalized = self._move_joints_interpolated(targets, duration_s=2.0 / speed_scale, update_hz=12.0, label="Home")
                if normalized.get("ok"):
                    now = time.monotonic()
                    for joint, target in targets.items():
                        self._joint_command_targets[joint] = float(target)
                        self._joint_command_updated_at[joint] = now
                self._log("info" if normalized["ok"] else "error", "home", normalized["message"], slowed=True)
                return normalized
            if hasattr(self.controller, "move_home"):
                result = self.controller.move_home()
            elif hasattr(self.controller, "回到默认姿态"):
                result = self.controller.回到默认姿态()
            else:
                return fail("当前控制器不支持 Home。")
            normalized = normalize_bridge_result(result, "Home 完成。")
            self._log("info" if normalized["ok"] else "error", "home", normalized["message"])
            return normalized
        except Exception as exc:
            return self._exception("Home 失败", exc)

    def _move_joints_interpolated(
        self,
        targets: dict[str, float],
        duration_s: float,
        steps: int | None = None,
        update_hz: float = 10.0,
        label: str = "平滑移动",
    ) -> dict[str, Any]:
        state_result = self.get_state()
        if not state_result.get("ok"):
            return state_result
        current = result_data(state_result).get("joints_deg", {})
        start = {joint: float(current.get(joint, 0.0)) for joint in JOINT_ORDER}
        steps = max(1, int(steps if steps is not None else math.ceil(float(duration_s) * float(update_hz))))
        sleep_s = max(0.0, float(duration_s)) / float(steps)
        last = ok("Home 完成。", {"targets_deg": targets})
        for index in range(1, steps + 1):
            ratio = smoothstep01(index / steps)
            middle = {
                joint: start[joint] + (float(targets.get(joint, start[joint])) - start[joint]) * ratio
                for joint in JOINT_ORDER
                if joint in targets
            }
            result = self.controller.move_joints(middle)
            last = normalize_bridge_result(result, f"{label}分段移动完成。", {"targets_deg": middle})
            if not last.get("ok"):
                return last
            self._emit_motion_update(middle, "interpolated_move", label=label, frame_index=index, frame_count=steps)
            if index < steps and sleep_s > 0:
                time.sleep(sleep_s)
        return ok(f"{label}完成。", {"targets_deg": targets, "duration_s": float(duration_s), "steps": steps, "speed_percent": self.motion_speed_percent})

    def _move_single_joint_interpolated(
        self,
        joint_key: str,
        start_deg: float,
        target_deg: float,
        duration_s: float,
        steps: int,
        label: str,
        current_joints: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        steps = max(1, int(steps))
        duration_s = max(0.0, float(duration_s))
        sleep_s = duration_s / float(steps) if steps > 0 else 0.0
        extra = dict(data or {})
        last: dict[str, Any] = ok(f"{label}完成。")
        for index in range(1, steps + 1):
            ratio = smoothstep01(index / steps)
            middle_deg = float(start_deg) + (float(target_deg) - float(start_deg)) * ratio
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints({joint_key: middle_deg})
                last = normalize_bridge_result(result, f"{label}分段移动完成。", {"targets_deg": {joint_key: middle_deg}})
            else:
                frame_targets = {joint: float((current_joints or {}).get(joint, 0.0)) for joint in JOINT_ORDER}
                frame_targets[joint_key] = middle_deg
                last = self._move_joints_unlocked(frame_targets)
            if not last.get("ok"):
                return last
            self._joint_command_targets[joint_key] = float(middle_deg)
            self._joint_command_updated_at[joint_key] = time.monotonic()
            self._emit_motion_update({joint_key: middle_deg}, "quick_step", label=label, frame_index=index, frame_count=steps)
            if index < steps and sleep_s > 0:
                time.sleep(sleep_s)
        payload = {
            "joint_key": joint_key,
            "target_deg": float(target_deg),
            "targets_deg": {joint_key: float(target_deg)},
            "duration_s": duration_s,
            "steps": steps,
            "interpolated": True,
        }
        payload.update(extra)
        return ok(f"{label}完成。", payload)

    def stop(self) -> dict[str, Any]:
        with self.io_lock:
            return self._stop_unlocked()

    def _stop_unlocked(self) -> dict[str, Any]:
        try:
            self._continuous_jog_stop.set()
            self._continuous_jog_joint = None
            self._joint_command_targets.clear()
            self._joint_command_updated_at.clear()
            if self.controller is not None and hasattr(self.controller, "stop"):
                result = self.controller.stop()
                normalized = normalize_bridge_result(result, "已急停。")
            else:
                normalized = ok("已急停。")
            if self.sequence_player is not None:
                try:
                    self.sequence_player.stop()
                except Exception:
                    pass
            self.action_status = "已停止"
            self._log("warning", "stop", normalized["message"])
            return normalized
        except Exception as exc:
            return self._exception("急停失败", exc)

    def release_torque(self) -> dict[str, Any]:
        with self.io_lock:
            return self._release_torque_unlocked()

    def _release_torque_unlocked(self) -> dict[str, Any]:
        try:
            self._ensure_controller()
            if self.controller is None:
                return fail("控制器未创建。")
            if not self.is_connected():
                return fail("尚未连接，不能释放力矩。")

            if hasattr(self.controller, "release_torque"):
                result = self.controller.release_torque()
                normalized = normalize_bridge_result(result, "力矩已释放。")
            elif hasattr(self.controller, "driver") and hasattr(self.controller.driver, "disable_torque"):
                self.controller.driver.disable_torque()
                normalized = ok("力矩已释放。请扶稳机械臂。")
            elif hasattr(self.controller, "disable_torque"):
                self.controller.disable_torque()
                normalized = ok("力矩已释放。请扶稳机械臂。")
            else:
                return fail("当前控制器不支持释放力矩。")

            if hasattr(self.controller, "_torque_enabled_joints"):
                self.controller._torque_enabled_joints.clear()
            self.action_status = "力矩已释放"
            self._log("warning" if normalized["ok"] else "error", "release_torque", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("释放力矩失败", exc)

    def list_poses(self) -> dict[str, Any]:
        try:
            return ok("姿态列表已加载。", {"poses": list_pose_items(self._get_pose_manager())})
        except Exception as exc:
            return self._exception("读取姿态列表失败", exc)

    def save_pose(self, name: str) -> dict[str, Any]:
        try:
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state = state_result["data"]
            payload = save_pose_from_state(self._get_pose_manager(), name, state, "GUI 保存的当前姿态")
            self._log("info", "save_pose", f"已保存姿态：{name}")
            return ok(f"已保存姿态：{name}", {"pose": payload})
        except Exception as exc:
            return self._exception("保存姿态失败", exc)

    def goto_pose(self, name: str) -> dict[str, Any]:
        try:
            pose = self._get_pose_manager().获取姿态(name)
            if pose is None:
                return fail(f"姿态不存在：{name}")
            if self.mode in {"dry_run", "real"}:
                normalized = self.move_joints_smooth(pose.get("关节角度", []), label=f"前往姿态 {name}")
            elif hasattr(self.controller, "应用姿态"):
                normalized = normalize_bridge_result(self.controller.应用姿态(pose), f"已前往姿态：{name}", {"pose": pose})
            else:
                normalized = self.move_joints(pose.get("关节角度", []))
            self._log("info" if normalized["ok"] else "error", "goto_pose", normalized["message"], name=name)
            return normalized
        except Exception as exc:
            return self._exception("前往姿态失败", exc)

    def delete_pose(self, name: str) -> dict[str, Any]:
        try:
            deleted = delete_pose_from_manager(self._get_pose_manager(), name)
            if not deleted:
                return fail(f"姿态不存在：{name}")
            self._log("info", "delete_pose", f"已删除姿态：{name}")
            return ok(f"已删除姿态：{name}")
        except Exception as exc:
            return self._exception("删除姿态失败", exc)

    def list_actions(self) -> dict[str, Any]:
        try:
            return ok("动作列表已加载。", {"actions": list_action_items(self._get_action_library())})
        except Exception as exc:
            return self._exception("读取动作库失败", exc)

    def play_action(self, name: str) -> dict[str, Any]:
        try:
            self._ensure_controller()
            library = self._get_action_library()
            player = self._get_sequence_player()
            self.action_status = f"播放中：{name}"
            speed = motion_speed_scale(self.motion_speed_percent)
            result_bool = play_action_from_library(library, player, name, speed=speed, loop=False)
            self.action_status = "空闲" if result_bool else "已停止"
            message = f"动作播放完成：{name}" if result_bool else f"动作播放未完成：{name}"
            self._log("info" if result_bool else "warning", "play_action", message, name=name)
            return ok(message) if result_bool else fail(message)
        except Exception as exc:
            self.action_status = "错误"
            return self._exception("动作播放失败", exc)

    def pause_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.pause()
        self.action_status = "已暂停"
        return ok("动作已暂停。")

    def resume_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.resume()
        self.action_status = "播放中"
        return ok("动作已继续。")

    def stop_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.stop()
        self.action_status = "已停止"
        return ok("动作已停止。")

    def delete_action(self, name: str) -> dict[str, Any]:
        try:
            self._get_action_library().delete_action(name)
            self._log("info", "delete_action", f"已删除动作：{name}", name=name)
            return ok(f"已删除动作：{name}")
        except Exception as exc:
            return self._exception("删除动作失败", exc)

    def start_action_recording(self, name: str, source: str = "gui_record") -> dict[str, Any]:
        with self.io_lock:
            try:
                action_name = sanitize_action_name(name)
                self.recording_sequence = build_recording_sequence(action_name, source, self._resolve_config("action_config_path"))
                self.recording_name = action_name
                self.recording_source = source
                self.action_status = f"录制中：{action_name}"
                self._ensure_controller()
                self._log("info", "start_recording", f"已开始动作录制：{action_name}", name=action_name, source=source)
                return ok(
                    f"已开始动作录制：{action_name}",
                    {"recording": self._recording_summary()},
                )
            except Exception as exc:
                return self._exception("开始动作录制失败", exc)

    def start_teach_recording(self, name: str) -> dict[str, Any]:
        with self.io_lock:
            result = self.start_action_recording(name, source="gui_teach_mode")
            if not result.get("ok"):
                return result
            if self.mode == "real" and self.is_connected():
                release = self._release_torque_unlocked()
                result.setdefault("data", {})["release_torque"] = release
                if not release.get("ok"):
                    return release
            self.action_status = f"示教录制中：{self.recording_name}"
            self._log("warning", "start_teach_recording", "示教录制已开始。真实模式下请扶稳机械臂。", name=self.recording_name)
            return result

    def capture_recording_pose(self) -> dict[str, Any]:
        with self.io_lock:
            try:
                if self.recording_sequence is None:
                    return fail("没有正在进行的动作录制。")
                self._ensure_controller()

                recorder = load_action_recorder(self.controller, self._resolve_config("action_config_path"))
                index = len(self.recording_sequence.get("poses", [])) + 1
                pose = recorder.capture_current_pose(index=index, name=f"pose_{index}")
                append_action_pose(self.recording_sequence, pose)
                self._log(
                    "info",
                    "capture_recording_pose",
                    f"已采集录制帧 {index}。",
                    name=self.recording_name,
                    pose_index=index,
                )
                return ok(f"已采集第 {index} 帧。", {"recording": self._recording_summary(), "pose": pose})
            except Exception as exc:
                return self._exception("采集动作帧失败", exc)

    def save_recording_action(self) -> dict[str, Any]:
        with self.io_lock:
            try:
                if self.recording_sequence is None:
                    return fail("没有正在进行的动作录制。")
                if not self.recording_sequence.get("poses"):
                    return fail("当前录制没有任何姿态帧，不能保存。")
                name = self.recording_name
                library = self._get_action_library()
                refresh_action_pose_count(self.recording_sequence)
                path = library.save_action(name, self.recording_sequence)
                count = int(self.recording_sequence.get("pose_count", 0))
                self.recording_sequence = None
                self.recording_name = ""
                self.recording_source = "gui_record"
                self.action_status = "空闲"
                self._log("info", "save_recording_action", f"动作录制已保存：{name}", name=name, pose_count=count, path=str(path))
                return ok(
                    f"动作录制已保存：{name}（{count} 帧）",
                    {"action_name": name, "path": str(path), "pose_count": count, "recording": self._recording_summary()},
                )
            except Exception as exc:
                return self._exception("保存录制动作失败", exc)

    def cancel_recording_action(self) -> dict[str, Any]:
        with self.io_lock:
            name = self.recording_name
            self.recording_sequence = None
            self.recording_name = ""
            self.recording_source = "gui_record"
            self.action_status = "空闲"
            self._log("warning", "cancel_recording_action", "已取消动作录制。", name=name)
            return ok("已取消动作录制。", {"recording": self._recording_summary()})

    def get_recording_status(self) -> dict[str, Any]:
        return ok("录制状态已读取。", {"recording": self._recording_summary()})

    def get_calibration_status(self) -> dict[str, Any]:
        try:
            if self.mode in {"dry_run", "real"}:
                self._ensure_controller()
                if hasattr(self.controller, "calibration_report"):
                    report = self.controller.calibration_report()
                else:
                    report = load_calibration_report(self._resolve_config("real_config_path"))
            else:
                report = load_calibration_report(self._resolve_config("real_config_path"))
            return ok("标定状态已刷新。", {"calibration": report})
        except Exception as exc:
            return self._exception("读取标定状态失败", exc)

    def get_tcp_pose(self) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            state = self._raw_state_for_tcp()
            return ok("TCP 已计算。", compute_tcp_pose_payload(model, state))
        except Exception as exc:
            return fail("TCP 计算失败。", exc)

    def compute_fk(self, joints_deg: list[float]) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，FK 不可用。")
            return ok("FK 计算完成。", compute_fk_payload(model, list(joints_deg[: len(JOINT_ORDER)]), allow_approx=False))
        except Exception as exc:
            return self._exception("FK 计算失败", exc)

    def compute_ik(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，IK 不可用。")
            current = self._raw_state_for_tcp()
            return ok("IK 计算完成。", compute_ik_payload(model, xyz, rpy, current))
        except Exception as exc:
            return self._exception("IK 计算失败", exc)

    def move_pose(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        ik = self.compute_ik(xyz, rpy)
        if not ik.get("ok"):
            return ik
        return self.move_joints(ik["data"]["target_joints_deg"])

    def move_delta(self, dx: float, dy: float, dz: float, frame: str = "base") -> dict[str, Any]:
        computed = self.compute_delta(dx, dy, dz, frame)
        if not computed.get("ok"):
            return computed
        result = self.move_joints_smooth(computed["data"]["target_joints_deg"], label="末端增量移动")
        if result.get("ok"):
            result.setdefault("data", {}).update(computed.get("data", {}))
        return result

    def compute_delta(self, dx: float, dy: float, dz: float, frame: str = "base") -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，末端增量计算不可用。")
            tcp = self.get_tcp_pose()
            if not tcp.get("ok"):
                return tcp
            pose = result_data(tcp).get("tcp_pose", {})
            target_xyz, target_rpy = model.compose_delta_target(pose["xyz"], pose["rpy"], [dx, dy, dz], [0.0, 0.0, 0.0], frame)
            ik = self.compute_ik(target_xyz, None)
            if not ik.get("ok"):
                return ik
            data = result_data(ik)
            data["target_tcp_pose"] = {"xyz": target_xyz, "rpy": target_rpy, "frame": frame}
            data["delta_m"] = {"dx": float(dx), "dy": float(dy), "dz": float(dz)}
            data["source"] = f"{frame}_delta"
            return ok(f"{frame} 末端增量计算完成。", data)
        except Exception as exc:
            return self._exception("末端增量计算失败", exc)

    def check_dependencies(self) -> dict[str, Any]:
        modules = ("PyQt5", "yaml", "numpy", "pybullet", "lerobot")
        return ok("依赖检查完成。", check_python_modules(modules))

    def cinematic_latest_record(self) -> dict[str, Any]:
        try:
            record_dir = self.project_root / "视觉识别与跟随" / "runtime" / "cinematic_records"
            latest_path = latest_matching_file(record_dir, "cinematic_rehearsal_*.json")
            if latest_path is None:
                return fail("没有找到两步运镜试拍记录。")
            return ok("已找到最新试拍记录。", {"record_path": str(latest_path)})
        except Exception as exc:
            return self._exception("查找试拍记录失败", exc)

    def cinematic_analyze(self, record_path: str = "", video_path: str = "") -> dict[str, Any]:
        try:
            from 运镜导演_cinematic_director import CinematicDirector

            director = CinematicDirector(self.project_root)
            record = director.load_record(record_path) if str(record_path).strip() else {}
            project = director.analyze_take(video_path=str(video_path).strip() or None, record=record)
            project["source_record_path"] = str(record_path).strip()
            project["workflow_stage"] = "motion_analysis"
            project_path = director.save_project(project)
            summary = project.get("motion_analysis", {}).get("summary", {})
            self._log("info", "cinematic_analyze", "AI 运镜试拍分析完成。", project_path=str(project_path), summary=summary)
            return ok("AI 运镜试拍分析完成。", {"project_path": str(project_path), "project": project})
        except Exception as exc:
            return self._exception("AI 运镜分析失败", exc)

    def cinematic_select_keyframes(self, project_path: str, min_count: int = 3, max_count: int = 8) -> dict[str, Any]:
        try:
            from 运镜导演_cinematic_director import CinematicDirector, DirectorDefaults, load_project

            path = self._resolve_project_path(project_path)
            director = CinematicDirector(
                self.project_root,
                DirectorDefaults(target_fps=float(self._motion_tuning().get("playback_update_hz", 20.0))),
            )
            project = load_project(path)
            keyframes = director.select_keyframes(project, min_count=min_count, max_count=max_count)
            project["director_keyframes"] = keyframes
            project["workflow_stage"] = "director_keyframes"
            atomic_write_json(path, project)
            self._log("info", "cinematic_keyframes", "AI 运镜关键帧已生成。", project_path=str(path), keyframe_count=len(keyframes))
            return ok("AI 运镜关键帧已生成。", {"project_path": str(path), "project": project, "keyframes": keyframes})
        except Exception as exc:
            return self._exception("AI 运镜关键帧生成失败", exc)

    def cinematic_generate_action(self, project_path: str, action_name: str = "") -> dict[str, Any]:
        try:
            from 运镜导演_cinematic_director import CinematicDirector, DirectorDefaults, load_project

            path = self._resolve_project_path(project_path)
            director = CinematicDirector(
                self.project_root,
                DirectorDefaults(
                    target_fps=float(self._motion_tuning().get("playback_update_hz", 20.0)),
                    dry_run_speed_percent=float(self.motion_speed_percent),
                    real_speed_percent=cinematic_real_speed_percent(self.motion_speed_percent),
                ),
            )
            project = load_project(path)
            keyframes = project.get("director_keyframes", [])
            if not isinstance(keyframes, list) or len(keyframes) < 2:
                keyframes = director.select_keyframes(project)
                project["director_keyframes"] = keyframes
            if any(not item.get("pose", {}).get("joints_deg") for item in keyframes if isinstance(item, dict)):
                return fail("关键帧缺少同步关节状态，不能生成可执行动作。")
            trajectory = director.build_trajectory(keyframes)
            name = sanitize_action_name(action_name or f"AI运镜_{time.strftime('%H%M%S')}")
            payload = director.build_action_payload(name, project, trajectory)
            library = self._get_action_library()
            saved_path = library.save_action(name, payload)
            project["trajectory_plan"] = trajectory
            project["generated_action"] = {"name": name, "path": str(saved_path), "pose_count": payload.get("pose_count", 0)}
            project["workflow_stage"] = "action_generated"
            atomic_write_json(path, project)
            self._log(
                "info",
                "cinematic_generate_action",
                "AI 运镜动作已生成。",
                project_path=str(path),
                action_name=name,
                action_path=str(saved_path),
                pose_count=payload.get("pose_count", 0),
            )
            return ok(
                f"AI 运镜动作已生成：{name}",
                {"project_path": str(path), "project": project, "action_name": name, "action_path": str(saved_path), "pose_count": payload.get("pose_count", 0)},
            )
        except Exception as exc:
            return self._exception("AI 运镜动作生成失败", exc)

    def _ensure_controller(self) -> None:
        if self.controller is not None:
            return
        if self.mode == "simulation":
            self.controller = self._create_sim_controller()
        else:
            self.controller = self._create_real_controller(dry_run=(self.mode == "dry_run"))

    def _create_sim_controller(self) -> Any:
        return load_sim_controller(self._resolve_config("sim_config_path"))

    def _create_real_controller(self, dry_run: bool) -> Any:
        return load_real_controller(
            self._resolve_config("real_config_path"),
            dry_run=dry_run,
            runtime_state_path=self.base_dir / "运行日志" / "dry_run_runtime_state.json",
            temp_dir_name="arm_gui",
            serial_port=self.serial_port_override,
        )

    def _get_pose_manager(self) -> Any:
        if self.pose_manager is None:
            self.pose_manager = load_pose_manager(self.project_root, self._resolve_config("sim_config_path"))
        return self.pose_manager

    def _get_action_library(self) -> Any:
        if self.action_library is None:
            self.action_library = load_action_library(self._resolve_config("action_config_path"))
        return self.action_library

    def _get_sequence_player(self) -> Any:
        if self.sequence_player is None:
            self.sequence_player = load_sequence_player(
                self.controller,
                self._resolve_config("action_config_path"),
                playback_update_hz=float(self._motion_tuning()["playback_update_hz"]),
            )
            self.sequence_player.progress_callback = self.motion_update_callback
        return self.sequence_player

    def _get_kinematics_model(self) -> Any | None:
        if self.kinematics_model is not None:
            return self.kinematics_model
        self.kinematics_model, self.last_error = load_kinematics_model(self._resolve_config("kinematics_config_path"))
        return self.kinematics_model

    def _raw_state_for_tcp(self) -> dict[str, float]:
        try:
            self._ensure_controller()
        except Exception:
            return {joint: 0.0 for joint in JOINT_ORDER}
        return current_joints_for_controller(self.controller, prefer_detailed=False)

    def _normalize_state(self, state: Any) -> dict[str, Any]:
        state = state if isinstance(state, dict) else {}
        payload = normalize_robot_state_payload(state, self.mode, self.is_connected(), self._resolve_config("real_config_path"))
        payload["goal_joints_deg"] = self._normalize_goal_joints(state)
        payload["goal_raw_by_joint"] = dict(state.get("goal_raw_by_joint", {})) if isinstance(state.get("goal_raw_by_joint", {}), dict) else {}
        return payload

    def _motion_tuning(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        return normalize_motion_tuning(self.config.get("motion", {}), overrides, joint_order=JOINT_ORDER)

    def _jog_direction_override(self, joint_key: str) -> int:
        overrides = self._motion_tuning().get("jog_direction_overrides", {})
        value = overrides.get(joint_key, 1) if isinstance(overrides, dict) else 1
        return -1 if int(value) < 0 else 1

    def _precheck_single_joint_target(self, joint_key: str, target_deg: float, current_deg: float, delta_deg: float) -> dict[str, Any] | None:
        """在 GUI 桥接层提前拦截单圈 raw 限位。

        真实控制器本身也会做安全检查；这里额外做一次，是为了让快速控制里
        “按了按钮但机械臂没动”的场景显示成明确的限位提示，而不是泛泛的写入成功。
        """

        if self.controller is None:
            return None
        if not all(hasattr(self.controller, attr) for attr in ("joint_config_by_key", "calibration_manager", "safety_checker")):
            return None
        try:
            if joint_key not in self.controller.joint_config_by_key or not self.controller.calibration_manager.has(joint_key):
                return None
            from 角度映射_angle_mapper import joint_deg_to_goal_detail, joint_label

            joint_config = self.controller.joint_config_by_key[joint_key]
            entry = self.controller.calibration_manager.get(joint_key)
            detail = joint_deg_to_goal_detail(joint_key, target_deg, joint_config, entry, self.controller.runtime_state)
            raw_check = self.controller.safety_checker.check_goal_raw(joint_key, int(detail["goal_raw"]), entry)
            if raw_check.成功:
                return None
            direction_text = "负方向" if float(delta_deg) < 0 else "正方向"
            message = (
                f"{joint_label(joint_key)} 已接近或到达{direction_text}标定限位，"
                f"本次目标 {target_deg:.2f}° 对应 raw={int(detail['goal_raw'])}，"
                f"允许 raw 范围 [{int(entry.get('range_min', 0))}, {int(entry.get('range_max', 0))}]。"
                "如果实际机械结构还能继续运动，请重新标定该关节的单圈范围。"
            )
            return fail(
                message,
                data={
                    "joint_key": joint_key,
                    "current_deg": float(current_deg),
                    "target_deg": float(target_deg),
                    "delta_deg": float(delta_deg),
                    "goal_detail": detail,
                    "range_min": int(entry.get("range_min", 0)),
                    "range_max": int(entry.get("range_max", 0)),
                },
            )
        except Exception as exc:
            text = str(exc)
            if "signed absolute raw" in text or "多圈目标 raw" in text:
                try:
                    from 角度映射_angle_mapper import joint_label
                    label = joint_label(joint_key)
                except Exception:
                    label = joint_key
                unit = "mm" if joint_key == "j10" else "deg"
                return fail(
                    f"{label} 多圈目标超出 raw 安全范围。"
                    f"当前={current_deg:.2f} {unit}，目标={target_deg:.2f} {unit}。"
                    "请往反方向移动，或重新标定该多圈关节的 Home/零点；不要继续朝这个方向点动。",
                    data={
                        "joint_key": joint_key,
                        "current_deg": float(current_deg),
                        "target_deg": float(target_deg),
                        "delta_deg": float(delta_deg),
                        "error": text,
                    },
                )
            return None

    def _joint_delta_base_deg(self, joint_key: str, current_deg: float, state_data: dict[str, Any]) -> float:
        recent_target = self._joint_command_targets.get(joint_key)
        updated_at = self._joint_command_updated_at.get(joint_key, 0.0)
        if recent_target is not None and time.monotonic() - updated_at <= 2.0:
            return float(recent_target)

        return float(current_deg)

    def _normalize_goal_joints(self, state: dict[str, Any]) -> dict[str, float]:
        raw = state.get("goal_joint_targets_deg", state.get("goal_joints_deg", {}))
        if not isinstance(raw, dict):
            return {}
        goals: dict[str, float] = {}
        for joint in JOINT_ORDER:
            if joint in raw:
                try:
                    goals[joint] = float(raw[joint])
                except (TypeError, ValueError):
                    pass
        return goals

    def _emit_motion_update(self, targets_deg: dict[str, float], source: str, **extra: Any) -> None:
        payload = build_motion_progress_payload(targets_deg, source, **extra)
        safe_call_callback(self.motion_update_callback, payload)

    def _recording_summary(self) -> dict[str, Any]:
        sequence = self.recording_sequence or {}
        return {
            "active": self.recording_sequence is not None,
            "name": self.recording_name,
            "source": self.recording_source,
            "pose_count": len(sequence.get("poses", [])) if isinstance(sequence, dict) else 0,
        }

    def _resolve_config(self, key: str) -> Path:
        return self._config_resolver(key)

    def _resolve_project_path(self, path_value: str | Path) -> Path:
        return resolve_base_path(path_value, self.project_root)

    def _log(self, level: str, event: str, message: str, **extra: Any) -> None:
        log_json_line(self.log_path, level, event, message, time_style="local_string", **extra)

    def _exception(self, message: str, exc: Exception) -> dict[str, Any]:
        context = build_exception_context(message, exc, include_type=True)
        self.last_error = context["last_error"]
        self._log("error", "exception", context["message"], traceback=context["traceback"])
        return fail(context["message"], context["error"])

    def copy_log_path_to(self, target: str | Path) -> Path:
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.log_path, target_path)
        return target_path
