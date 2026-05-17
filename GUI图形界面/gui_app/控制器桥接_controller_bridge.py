"""GUI 和前面阶段控制器之间的统一桥接层。

GUI 只调用 ControllerBridge，不直接写舵机、不直接绕过阶段四安全检查。
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any


JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
JOINT_LABELS = {
    "shoulder_pan": "J1 底座旋转",
    "shoulder_lift": "J2 肩部抬升",
    "elbow_flex": "J3 肘部弯曲",
    "wrist_flex": "J4 腕部俯仰",
    "wrist_roll": "J5 腕部旋转",
}


def ok(message: str = "成功", data: Any | None = None) -> dict[str, Any]:
    return {"ok": True, "message": message, "data": data or {}}


def fail(message: str, error: Any | None = None, data: Any | None = None) -> dict[str, Any]:
    return {"ok": False, "message": message, "error": str(error or message), "data": data or {}}


class ControllerBridge:
    """GUI 统一控制入口。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1]).resolve()
        self.project_root = self.base_dir.parent
        self.config = config
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
        self._dry_run_config_path: Path | None = None
        self.serial_port_override: str | None = None
        self.io_lock = threading.RLock()
        self.log_path = self._resolve_gui_path(config.get("app", {}).get("log_path", "运行日志/gui_runtime.log"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.motion_speed_percent = float(config.get("motion", {}).get("default_speed_percent", 50.0))
        self.recording_sequence: dict[str, Any] | None = None
        self.recording_name = ""
        self.recording_source = "gui_record"
        self._joint_command_targets: dict[str, float] = {}
        self._joint_command_updated_at: dict[str, float] = {}
        self.motion_update_callback = None
        self._install_stage_paths()

    def set_motion_update_callback(self, callback: Any | None) -> None:
        self.motion_update_callback = callback
        if self.sequence_player is not None:
            self.sequence_player.progress_callback = callback

    def set_motion_speed_percent(self, percent: float) -> dict[str, Any]:
        self.motion_speed_percent = max(10.0, min(100.0, float(percent)))
        self._log("info", "set_motion_speed", f"全局速度已设置为 {self.motion_speed_percent:.0f}%。", speed_percent=self.motion_speed_percent)
        return ok("全局速度已更新。", {"speed_percent": self.motion_speed_percent})

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
                normalized = self._normalize_result(result, "连接完成。")
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
                normalized = self._normalize_result(result, "已断开。")
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
        mode = str(mode).strip()
        if mode not in {"simulation", "dry_run", "real"}:
            return fail(f"未知模式：{mode}")
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
            if hasattr(self.controller, "get_state"):
                state = self.controller.get_state()
            elif hasattr(self.controller, "获取详细状态"):
                state = self.controller.获取详细状态()
            elif hasattr(self.controller, "获取当前状态"):
                state = self.controller.获取当前状态()
            else:
                state = {}
            normalized = self._normalize_state(state)
            tcp = self.get_tcp_pose()
            if tcp.get("ok"):
                normalized["tcp_pose"] = tcp.get("data", {}).get("tcp_pose", {})
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
            targets = self._normalize_targets(targets_deg)
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints(targets)
            elif hasattr(self.controller, "移动到关节角度"):
                result = self.controller.移动到关节角度([targets[joint] for joint in JOINT_ORDER])
            else:
                return fail("当前控制器不支持关节移动。")
            normalized = self._normalize_result(result, "关节移动完成。", {"targets_deg": targets})
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
            targets = self._normalize_targets(targets_deg)
            max_delta = 0.0
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            current = state_result.get("data", {}).get("joints_deg", {})
            for joint, target in targets.items():
                max_delta = max(max_delta, abs(float(target) - float(current.get(joint, 0.0))))
            speed_scale = max(0.1, min(1.0, self.motion_speed_percent / 100.0))
            max_speed_deg_s = float(self.config.get("motion", {}).get("max_smooth_speed_deg_s", 45.0)) * speed_scale
            duration = max(0.4, max_delta / max(1.0, max_speed_deg_s))
            return self._move_joints_interpolated(targets, duration_s=duration, update_hz=20.0, label=label)
        except Exception as exc:
            return self._exception("平滑移动失败", exc)

    def move_joint_delta(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        with self.io_lock:
            return self._move_joint_delta_unlocked(joint_key, delta_deg)

    def _move_joint_delta_unlocked(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        try:
            joint_key = self._normalize_joint_key(joint_key)
            max_step = float(self.config.get("safety", {}).get("max_real_step_deg" if self.mode == "real" else "max_gui_step_deg", 5.0))
            delta = max(-max_step, min(max_step, float(delta_deg)))
            self._ensure_controller()
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            current = state_result.get("data", {}).get("joints_deg", {})
            current_deg = float(current.get(joint_key, 0.0))
            base_deg = self._joint_delta_base_deg(joint_key, current_deg, state_result.get("data", {}))
            target_deg = current_deg + delta
            if base_deg != current_deg:
                target_deg = base_deg + delta
            precheck = self._precheck_single_joint_target(joint_key, target_deg, current_deg, delta)
            if precheck is not None:
                self._log("warning", "move_joint_delta_blocked", precheck["message"], **precheck.get("data", {}))
                return precheck
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints({joint_key: target_deg})
                normalized = self._normalize_result(
                    result,
                    "关节微调完成。",
                    {"joint_key": joint_key, "delta_deg": delta, "current_deg": current_deg, "base_deg": base_deg, "target_deg": target_deg},
                )
            else:
                targets = {joint: float(current.get(joint, 0.0)) for joint in JOINT_ORDER}
                targets[joint_key] = target_deg
                normalized = self.move_joints(targets)
                normalized.setdefault("data", {}).update({"joint_key": joint_key, "delta_deg": delta, "current_deg": current_deg, "base_deg": base_deg, "target_deg": target_deg})
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
            value = max(0.0, min(100.0, float(open_percent)))
            if hasattr(self.controller, "set_gripper"):
                result = self.controller.set_gripper(value)
            elif hasattr(self.controller, "设置夹爪"):
                result = self.controller.设置夹爪(value)
            else:
                return fail("当前控制器不支持夹爪控制。")
            normalized = self._normalize_result(result, "夹爪控制完成。", {"open_percent": value})
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
                speed_scale = max(0.1, min(1.0, self.motion_speed_percent / 100.0))
                normalized = self._move_joints_interpolated(targets, duration_s=2.0 / speed_scale, update_hz=12.0, label="Home")
                if normalized.get("ok") and hasattr(self.controller, "set_gripper"):
                    try:
                        gripper_default = float(self.controller.config.get("gripper", {}).get("默认开合", 50))
                        self.controller.set_gripper(gripper_default)
                    except Exception:
                        pass
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
            normalized = self._normalize_result(result, "Home 完成。")
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
        current = state_result.get("data", {}).get("joints_deg", {})
        start = {joint: float(current.get(joint, 0.0)) for joint in JOINT_ORDER}
        steps = max(1, int(steps if steps is not None else math.ceil(float(duration_s) * float(update_hz))))
        sleep_s = max(0.0, float(duration_s)) / float(steps)
        last = ok("Home 完成。", {"targets_deg": targets})
        for index in range(1, steps + 1):
            ratio = index / steps
            middle = {
                joint: start[joint] + (float(targets.get(joint, start[joint])) - start[joint]) * ratio
                for joint in JOINT_ORDER
                if joint in targets
            }
            result = self.controller.move_joints(middle)
            last = self._normalize_result(result, f"{label}分段移动完成。", {"targets_deg": middle})
            if not last.get("ok"):
                return last
            self._emit_motion_update(middle, "interpolated_move", label=label, frame_index=index, frame_count=steps)
            if index < steps and sleep_s > 0:
                time.sleep(sleep_s)
        return ok(f"{label}完成。", {"targets_deg": targets, "duration_s": float(duration_s), "steps": steps, "speed_percent": self.motion_speed_percent})

    def stop(self) -> dict[str, Any]:
        with self.io_lock:
            return self._stop_unlocked()

    def _stop_unlocked(self) -> dict[str, Any]:
        try:
            if self.controller is not None and hasattr(self.controller, "stop"):
                result = self.controller.stop()
                normalized = self._normalize_result(result, "已急停。")
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
                normalized = self._normalize_result(result, "力矩已释放。")
            elif hasattr(self.controller, "driver") and hasattr(self.controller.driver, "disable_torque"):
                self.controller.driver.disable_torque()
                normalized = ok("力矩已释放。请扶稳机械臂。")
            elif hasattr(self.controller, "disable_torque"):
                self.controller.disable_torque()
                normalized = ok("力矩已释放。请扶稳机械臂。")
            else:
                return fail("当前控制器不支持释放力矩。")

            self.action_status = "力矩已释放"
            self._log("warning" if normalized["ok"] else "error", "release_torque", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("释放力矩失败", exc)

    def list_poses(self) -> dict[str, Any]:
        try:
            manager = self._get_pose_manager()
            names = manager.列出姿态()
            items = [{"name": name, "pose": manager.获取姿态(name)} for name in names]
            return ok("姿态列表已加载。", {"poses": items})
        except Exception as exc:
            return self._exception("读取姿态列表失败", exc)

    def save_pose(self, name: str) -> dict[str, Any]:
        try:
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state = state_result["data"]
            payload = {"关节角度": [state["joints_deg"].get(joint, 0.0) for joint in JOINT_ORDER], "夹爪": state.get("gripper", {}).get("open_percent", 50)}
            self._get_pose_manager().保存姿态(name, payload, "GUI 保存的当前姿态")
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
                normalized = self._normalize_result(self.controller.应用姿态(pose), f"已前往姿态：{name}", {"pose": pose})
            else:
                normalized = self.move_joints(pose.get("关节角度", []))
            self._log("info" if normalized["ok"] else "error", "goto_pose", normalized["message"], name=name)
            return normalized
        except Exception as exc:
            return self._exception("前往姿态失败", exc)

    def delete_pose(self, name: str) -> dict[str, Any]:
        try:
            deleted = self._get_pose_manager().删除姿态(name)
            if not deleted:
                return fail(f"姿态不存在：{name}")
            self._log("info", "delete_pose", f"已删除姿态：{name}")
            return ok(f"已删除姿态：{name}")
        except Exception as exc:
            return self._exception("删除姿态失败", exc)

    def list_actions(self) -> dict[str, Any]:
        try:
            library = self._get_action_library()
            actions = []
            for name in library.list_actions():
                summary = library.summarize_action(name)
                actions.append({"name": name, "summary": summary})
            return ok("动作列表已加载。", {"actions": actions})
        except Exception as exc:
            return self._exception("读取动作库失败", exc)

    def play_action(self, name: str) -> dict[str, Any]:
        try:
            self._ensure_controller()
            library = self._get_action_library()
            sequence = library.load_action(name)
            player = self._get_sequence_player()
            self.action_status = f"播放中：{name}"
            result_bool = player.play(sequence, loop=False, speed=max(0.1, min(1.0, self.motion_speed_percent / 100.0)))
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
                from 动作工具_common import build_empty_sequence, load_config

                action_name = self._sanitize_action_name(name)
                action_config = load_config(self._resolve_config("action_config_path"))
                self.recording_sequence = build_empty_sequence(name=action_name, source=source, config=action_config)
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
                from 动作录制器_action_recorder import ActionRecorder
                from 动作工具_common import load_config

                action_config = load_config(self._resolve_config("action_config_path"))
                recorder = ActionRecorder(self.controller, action_config)
                index = len(self.recording_sequence.get("poses", [])) + 1
                pose = recorder.capture_current_pose(index=index, name=f"pose_{index}")
                self.recording_sequence.setdefault("poses", []).append(pose)
                self.recording_sequence["pose_count"] = len(self.recording_sequence["poses"])
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
                    report = self._load_calibration_report_from_file()
            else:
                report = self._load_calibration_report_from_file()
            return ok("标定状态已刷新。", {"calibration": report})
        except Exception as exc:
            return self._exception("读取标定状态失败", exc)

    def get_tcp_pose(self) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，TCP 位姿不可用。")
            state = self._raw_state_for_tcp()
            q_rad = [math.radians(float(state.get(joint, 0.0))) for joint in JOINT_ORDER]
            pose = model.forward(q_rad)
            return ok("TCP 已计算。", {"tcp_pose": pose})
        except Exception as exc:
            return fail("TCP 计算失败。", exc)

    def compute_fk(self, joints_deg: list[float]) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，FK 不可用。")
            targets = self._normalize_targets(list(joints_deg[:5]))
            q_rad = [math.radians(float(targets[joint])) for joint in JOINT_ORDER]
            return ok("FK 计算完成。", {"tcp_pose": model.forward(q_rad), "target_joints_deg": targets, "source": "fk"})
        except Exception as exc:
            return self._exception("FK 计算失败", exc)

    def compute_ik(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return fail("PyBullet 未安装，IK 不可用。")
            current = self._raw_state_for_tcp()
            seed = [math.radians(float(current.get(joint, 0.0))) for joint in JOINT_ORDER]
            ik = model.inverse(xyz, rpy, seed_q_user=seed)
            joints_deg = {joint: math.degrees(float(ik["q_user_rad"][idx])) for idx, joint in enumerate(JOINT_ORDER)}
            return ok("IK 计算完成。", {"ik": ik, "target_joints_deg": joints_deg, "source": "ik"})
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
            pose = tcp["data"]["tcp_pose"]
            target_xyz, target_rpy = model.compose_delta_target(pose["xyz"], pose["rpy"], [dx, dy, dz], [0.0, 0.0, 0.0], frame)
            ik = self.compute_ik(target_xyz, None)
            if not ik.get("ok"):
                return ik
            data = dict(ik.get("data", {}))
            data["target_tcp_pose"] = {"xyz": target_xyz, "rpy": target_rpy, "frame": frame}
            data["delta_m"] = {"dx": float(dx), "dy": float(dy), "dz": float(dz)}
            data["source"] = f"{frame}_delta"
            return ok(f"{frame} 末端增量计算完成。", data)
        except Exception as exc:
            return self._exception("末端增量计算失败", exc)

    def check_dependencies(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for module_name in ("PyQt5", "yaml", "numpy", "pybullet", "lerobot"):
            try:
                __import__(module_name)
                data[module_name] = {"available": True, "message": "可用"}
            except Exception as exc:
                data[module_name] = {"available": False, "message": str(exc)}
        return ok("依赖检查完成。", data)

    def _ensure_controller(self) -> None:
        if self.controller is not None:
            return
        if self.mode == "simulation":
            self.controller = self._create_sim_controller()
        else:
            self.controller = self._create_real_controller(dry_run=(self.mode == "dry_run"))

    def _create_sim_controller(self) -> Any:
        from 机械臂模型_robot_arm import 机械臂模型

        config_path = self._resolve_config("sim_config_path")
        config = self._read_structured(config_path)
        return 机械臂模型(config)

    def _create_real_controller(self, dry_run: bool) -> Any:
        from 真实机械臂控制器_real_arm_controller import RealArmController

        config_path = self._resolve_config("real_config_path")
        use_path = self._make_runtime_real_config(config_path, dry_run=dry_run)
        return RealArmController(use_path)

    def _get_pose_manager(self) -> Any:
        if self.pose_manager is None:
            from 姿态管理_pose_manager import 姿态管理器

            sim_config = self._read_structured(self._resolve_config("sim_config_path"))
            pose_path = self.project_root / "仿真控制系统" / sim_config.get("文件", {}).get("姿态库", "姿态管理/姿态库.json")
            self.pose_manager = 姿态管理器(pose_path, sim_config.get("默认姿态", {}))
        return self.pose_manager

    def _get_action_library(self) -> Any:
        if self.action_library is None:
            from 动作文件管理_action_library import ActionLibrary
            from 动作工具_common import load_config

            action_config = load_config(self._resolve_config("action_config_path"))
            self.action_library = ActionLibrary(action_config)
        return self.action_library

    def _get_sequence_player(self) -> Any:
        if self.sequence_player is None:
            from 动作回放器_sequence_player import SequencePlayer
            from 动作工具_common import load_config

            config = load_config(self._resolve_config("action_config_path"))
            # GUI 已经在播放真实动作前做二次确认，避免后台线程里 input() 阻塞界面。
            config.setdefault("safety", {})["require_confirm_before_real_replay"] = False
            config.setdefault("playback", {})["update_hz"] = float(self.config.get("motion", {}).get("playback_update_hz", 20.0))
            self.sequence_player = SequencePlayer(self.controller, config)
            self.sequence_player.progress_callback = self.motion_update_callback
        return self.sequence_player

    def _get_kinematics_model(self) -> Any | None:
        if self.kinematics_model is not None:
            return self.kinematics_model
        try:
            from 运动学模型_kinematics_model import 创建运动学模型

            self.kinematics_model = 创建运动学模型(self._resolve_config("kinematics_config_path"), use_gui=False)
            return self.kinematics_model
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def _load_calibration_report_from_file(self) -> dict[str, Any]:
        from 标定管理_calibration_manager import CalibrationManager
        from 真实机械臂控制器_real_arm_controller import 读取配置

        real_config_path = self._resolve_config("real_config_path")
        config = 读取配置(real_config_path)
        cal_path = Path(config.get("calibration", {}).get("path", "标定文件.json"))
        if not cal_path.is_absolute():
            cal_path = real_config_path.parent / cal_path
        return CalibrationManager(cal_path, config).calibration_report()

    def _raw_state_for_tcp(self) -> dict[str, float]:
        state: dict[str, Any] = {}
        try:
            self._ensure_controller()
            if self.controller is not None:
                if hasattr(self.controller, "get_state"):
                    state = self.controller.get_state()
                elif hasattr(self.controller, "获取当前状态"):
                    state = self.controller.获取当前状态()
        except Exception:
            state = {}
        normalized = self._normalize_state(state)
        return {joint: float(normalized.get("joints_deg", {}).get(joint, 0.0)) for joint in JOINT_ORDER}

    def _normalize_state(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            state = {}
        joints_raw = state.get("关节角度", state.get("joints_deg", {}))
        if isinstance(joints_raw, dict):
            joints = {joint: float(joints_raw.get(joint, 0.0)) for joint in JOINT_ORDER}
        elif isinstance(joints_raw, list):
            joints = {joint: float(joints_raw[idx]) if idx < len(joints_raw) else 0.0 for idx, joint in enumerate(JOINT_ORDER)}
        else:
            joints = {joint: 0.0 for joint in JOINT_ORDER}
        gripper_raw = state.get("夹爪", state.get("gripper", {}))
        if isinstance(gripper_raw, dict):
            grip = gripper_raw.get("open_value", gripper_raw.get("开合", gripper_raw.get("open_percent", 50)))
        else:
            grip = gripper_raw if gripper_raw is not None else 50
        return {
            "mode": self.mode,
            "connected": self.is_connected(),
            "joints_deg": joints,
            "goal_joints_deg": self._normalize_goal_joints(state),
            "goal_raw_by_joint": dict(state.get("goal_raw_by_joint", {})) if isinstance(state.get("goal_raw_by_joint", {}), dict) else {},
            "joint_labels": dict(JOINT_LABELS),
            "gripper": {"open_percent": float(grip)},
            "raw": state,
        }

    def _normalize_targets(self, targets: dict[str, float] | list[float]) -> dict[str, float]:
        if isinstance(targets, dict):
            return {self._normalize_joint_key(key): float(value) for key, value in targets.items()}
        return {joint: float(targets[idx]) if idx < len(targets) else 0.0 for idx, joint in enumerate(JOINT_ORDER)}

    def _normalize_joint_key(self, value: str) -> str:
        text = str(value).strip()
        if text in JOINT_ORDER:
            return text
        mapping = {"J1": "shoulder_pan", "J2": "shoulder_lift", "J3": "elbow_flex", "J4": "wrist_flex", "J5": "wrist_roll", "1": "shoulder_pan", "2": "shoulder_lift", "3": "elbow_flex", "4": "wrist_flex", "5": "wrist_roll"}
        upper = text.upper()
        if upper in mapping:
            return mapping[upper]
        raise ValueError(f"未知关节：{value}")

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
        except Exception:
            return None

    def _joint_delta_base_deg(self, joint_key: str, current_deg: float, state_data: dict[str, Any]) -> float:
        recent_target = self._joint_command_targets.get(joint_key)
        updated_at = self._joint_command_updated_at.get(joint_key, 0.0)
        if recent_target is not None and time.monotonic() - updated_at <= 2.0:
            return float(recent_target)

        goal_joints = state_data.get("goal_joints_deg", {})
        if isinstance(goal_joints, dict) and joint_key in goal_joints:
            goal_deg = float(goal_joints[joint_key])
            if abs(goal_deg - float(current_deg)) > 0.05:
                return goal_deg
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
        callback = self.motion_update_callback
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

    def _sanitize_action_name(self, name: str) -> str:
        text = str(name).strip()
        if not text:
            text = f"GUI录制_{time.strftime('%Y%m%d_%H%M%S')}"
        for char in '/\\:*?"<>|':
            text = text.replace(char, "_")
        return text[:80]

    def _recording_summary(self) -> dict[str, Any]:
        sequence = self.recording_sequence or {}
        return {
            "active": self.recording_sequence is not None,
            "name": self.recording_name,
            "source": self.recording_source,
            "pose_count": len(sequence.get("poses", [])) if isinstance(sequence, dict) else 0,
        }

    def _normalize_result(self, result: Any, default_message: str, data: Any | None = None) -> dict[str, Any]:
        if isinstance(result, dict) and "ok" in result:
            return result
        if hasattr(result, "成功"):
            success = bool(getattr(result, "成功"))
            message = str(getattr(result, "消息", default_message))
            return ok(message, data) if success else fail(message, data=data)
        if isinstance(result, bool):
            return ok(default_message, data) if result else fail(default_message, data=data)
        return ok(default_message, data)

    def _resolve_gui_path(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return self.base_dir / path

    def _resolve_config(self, key: str) -> Path:
        value = self.config.get("controller", {}).get(key)
        if not value:
            raise KeyError(f"GUI 配置缺少 controller.{key}")
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    def _read_structured(self, path: str | Path) -> dict[str, Any]:
        text = Path(path).read_text(encoding="utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import yaml  # type: ignore

            data = yaml.safe_load(text) or {}
            if not isinstance(data, dict):
                raise ValueError(f"配置最外层必须是对象：{path}")
            return data

    def _write_json(self, path: str | Path, data: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _make_runtime_real_config(self, real_config_path: Path, dry_run: bool) -> Path:
        data = self._read_structured(real_config_path)
        transport = data.setdefault("transport", {})
        transport["dry_run"] = bool(dry_run)
        if self.serial_port_override:
            transport["port"] = self.serial_port_override
        calibration = data.setdefault("calibration", {})
        calibration_path = Path(calibration.get("path", "标定文件.json"))
        if not calibration_path.is_absolute():
            calibration["path"] = str((real_config_path.parent / calibration_path).resolve())
        data.setdefault("files", {})["runtime_state"] = str(self.base_dir / "运行日志" / "dry_run_runtime_state.json")
        temp_dir = Path(tempfile.gettempdir()) / "arm_gui"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = temp_dir / ("dry_run_真实配置_runtime.json" if dry_run else "real_真实配置_runtime.json")
        self._write_json(target, data)
        self._dry_run_config_path = target
        return target

    def _install_stage_paths(self) -> None:
        for path in (
            self.project_root / "仿真控制系统",
            self.project_root / "仿真控制系统" / "姿态管理",
            self.project_root / "真实舵机控制",
            self.project_root / "URDF运动学仿真",
            self.project_root / "动作录制与回放增强",
        ):
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)

    def _log(self, level: str, event: str, message: str, **extra: Any) -> None:
        payload = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "event": event,
            "message": message,
        }
        payload.update(extra)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False)
            file.write("\n")

    def _exception(self, message: str, exc: Exception) -> dict[str, Any]:
        self.last_error = str(exc)
        error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        self._log("error", "exception", f"{message}：{exc}", traceback=traceback.format_exc())
        return fail(f"{message}：{exc}", error_text)

    def copy_log_path_to(self, target: str | Path) -> Path:
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.log_path, target_path)
        return target_path
