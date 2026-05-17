"""阶段八 Web 专用 ControllerBridge。

这一层只做“Web API 到已有阶段控制器”的适配：
- dry-run / real 复用阶段四 RealArmController。
- sim 复用阶段三机械臂模型。
- TCP / IK 复用阶段五运动学模型。
- 动作库和动作回放复用阶段六 ActionLibrary / SequencePlayer。

注意：这里不直接导入 Feetech 底层驱动，也不提供 raw 舵机写入接口。
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Mapping


JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
MULTI_TURN_JOINTS = ["shoulder_lift", "elbow_flex", "wrist_roll"]
JOINT_LABELS = {
    "shoulder_pan": "J1 底座旋转",
    "shoulder_lift": "J2 肩部抬升",
    "elbow_flex": "J3 肘部弯曲",
    "wrist_flex": "J4 腕部俯仰",
    "wrist_roll": "J5 腕部旋转",
}


def bridge_ok(message: str = "成功", data: Any | None = None) -> dict[str, Any]:
    return {"ok": True, "message": message, "data": data if data is not None else {}}


def bridge_fail(message: str, error: Any | None = None, data: Any | None = None) -> dict[str, Any]:
    return {"ok": False, "message": str(message), "error": str(error or message), "data": data if data is not None else {}}


class ControllerBridge:
    """Web 后端统一控制入口。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None, logger: Any | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1]).resolve()
        self.project_root = self.base_dir.parent
        self.config = config
        self.logger = logger
        self.mode = self._normalize_mode(config.get("app", {}).get("default_mode", "dry_run"))
        self.connected = False
        self.controller: Any | None = None
        self.pose_manager: Any | None = None
        self.action_library: Any | None = None
        self.sequence_player: Any | None = None
        self.kinematics_model: Any | None = None
        self.last_error = ""
        self.action_status: dict[str, Any] = {
            "state": "idle",
            "name": "",
            "message": "空闲",
            "started_at": None,
            "finished_at": None,
        }
        self._runtime_real_config_path: Path | None = None
        self._install_stage_paths()

    # ------------------------------------------------------------------
    # 会话 / 控制器生命周期
    # ------------------------------------------------------------------
    def connect(self, mode: str | None = None) -> dict[str, Any]:
        """连接当前模式的控制器。

        dry-run 会连接 MockServoDriver，不访问真实串口；real 才会检查真实依赖。
        """

        try:
            if mode is not None:
                self.set_mode(mode)
            self._ensure_controller()
            if self.controller is None:
                return bridge_fail("控制器创建失败。")
            if hasattr(self.controller, "connect"):
                result = self.controller.connect()
                normalized = self._normalize_result(result, "连接完成。")
            else:
                normalized = bridge_ok("仿真控制器已就绪。")
            self.connected = bool(normalized["ok"])
            self._log("info" if normalized["ok"] else "error", "connect", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("连接失败", exc)

    def disconnect(self) -> dict[str, Any]:
        try:
            if self.sequence_player is not None:
                try:
                    self.sequence_player.stop()
                except Exception:
                    pass
            if self.controller is not None and hasattr(self.controller, "disconnect"):
                result = self.controller.disconnect()
                normalized = self._normalize_result(result, "已断开。")
            else:
                normalized = bridge_ok("已断开。")
            self.connected = False
            self._set_action_status("idle", "", "空闲")
            self._log("info", "disconnect", normalized["message"], mode=self.mode)
            return normalized
        except Exception as exc:
            return self._exception("断开失败", exc)

    def set_mode(self, mode: str) -> dict[str, Any]:
        try:
            normalized_mode = self._normalize_mode(mode)
        except ValueError as exc:
            return bridge_fail(str(exc))
        if normalized_mode == self.mode and self.controller is not None and not self.is_connected():
            return bridge_ok(f"当前已是 {self.mode} 模式。", {"mode": self.mode})
        if self.is_connected():
            self.disconnect()
        self.mode = normalized_mode
        self.controller = None
        self.sequence_player = None
        self.connected = False
        self._log("info", "set_mode", f"已切换模式：{self.mode}", mode=self.mode)
        return bridge_ok(f"已切换模式：{self.mode}", {"mode": self.mode})

    def is_connected(self) -> bool:
        if self.controller is not None and hasattr(self.controller, "connected"):
            return bool(getattr(self.controller, "connected"))
        return bool(self.connected)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_state(self) -> dict[str, Any]:
        try:
            if self.controller is None:
                self._ensure_controller()
            state: Any = {}
            if self.controller is not None:
                if hasattr(self.controller, "get_state"):
                    state = self.controller.get_state()
                elif hasattr(self.controller, "获取详细状态"):
                    state = self.controller.获取详细状态()
                elif hasattr(self.controller, "获取当前状态"):
                    state = self.controller.获取当前状态()
            normalized = self._normalize_state(state)
            tcp_result = self.get_tcp_pose()
            if tcp_result.get("ok"):
                normalized["tcp_pose"] = tcp_result.get("data", {}).get("tcp_pose")
            normalized["mode"] = self.mode
            normalized["connected"] = self.is_connected()
            normalized["action"] = dict(self.action_status)
            return bridge_ok("状态已刷新。", normalized)
        except Exception as exc:
            return self._exception("读取状态失败", exc)

    def get_tcp_pose(self) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            joints = self._current_joints_for_tcp()
            q_rad = [math.radians(float(joints.get(joint, 0.0))) for joint in JOINT_ORDER]
            if model is not None:
                pose = model.forward(q_rad)
                pose["source"] = pose.get("source", "stage5_fk")
            else:
                pose = self._approximate_tcp_pose(joints)
            return bridge_ok("TCP 已计算。", {"tcp_pose": pose})
        except Exception as exc:
            return bridge_fail("TCP 计算失败。", exc)

    def get_calibration_status(self) -> dict[str, Any]:
        try:
            if self.mode in {"dry_run", "real"}:
                self._ensure_controller()
                if self.controller is not None and hasattr(self.controller, "calibration_report"):
                    report = self.controller.calibration_report()
                else:
                    report = self._load_calibration_report_from_file()
            else:
                report = self._load_calibration_report_from_file()

            # 前端需要展示每个关节的 id / range / phase 等原始标定字段，这里补充 raw_items。
            raw_items = self._load_calibration_raw_items()
            report["raw_items"] = raw_items
            return bridge_ok("标定状态已刷新。", {"calibration": report})
        except Exception as exc:
            return self._exception("读取标定状态失败", exc)

    def check_dependencies(self) -> dict[str, Any]:
        """检查依赖；dry-run 不要求 lerobot 可用。"""

        modules = ["fastapi", "uvicorn", "pydantic", "yaml", "numpy", "pybullet", "lerobot", "serial"]
        data: dict[str, Any] = {}
        for module_name in modules:
            try:
                __import__(module_name)
                data[module_name] = {"available": True, "message": "可用"}
            except Exception as exc:
                data[module_name] = {"available": False, "message": str(exc)}
        data["dry_run_requires_real_deps"] = False
        data["real_mode_requires"] = ["lerobot", "feetech-servo-sdk", "pyserial"]
        return bridge_ok("依赖检查完成。", data)

    # ------------------------------------------------------------------
    # 运动控制
    # ------------------------------------------------------------------
    def move_joint_delta(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            joint = self._normalize_joint_key(joint_key)
            max_step = self._max_step_deg()
            delta = max(-max_step, min(max_step, float(delta_deg)))
            self._ensure_controller()
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "jog_joint"):
                result = self.controller.jog_joint(joint, delta)
                normalized = self._normalize_result(result, "关节微调完成。", {"joint_key": joint, "delta_deg": delta})
            else:
                state_result = self.get_state()
                if not state_result.get("ok"):
                    return state_result
                current = state_result.get("data", {}).get("joints_deg", {})
                targets = {key: float(current.get(key, 0.0)) for key in JOINT_ORDER}
                targets[joint] = targets[joint] + delta
                normalized = self.move_joints(targets)
            self._log("info" if normalized["ok"] else "error", "joint_step", normalized["message"], joint_key=joint, delta_deg=delta)
            return normalized
        except Exception as exc:
            return self._exception("关节微调失败", exc)

    def move_joints(self, targets_deg: Mapping[str, float]) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            self._ensure_controller()
            targets = self._normalize_targets(targets_deg)
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints(targets)
            elif hasattr(self.controller, "移动到关节角度"):
                result = self.controller.移动到关节角度([targets[joint] for joint in JOINT_ORDER])
            else:
                return bridge_fail("当前控制器不支持关节移动。")
            normalized = self._normalize_result(result, "关节移动完成。", {"targets_deg": targets})
            self._log("info" if normalized["ok"] else "error", "move_joints", normalized["message"], targets_deg=targets)
            return normalized
        except Exception as exc:
            return self._exception("关节移动失败", exc)

    def move_delta(self, dx: float, dy: float, dz: float, drx: float, dry: float, drz: float, frame: str) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            model = self._get_kinematics_model()
            if model is None:
                return bridge_fail("运动学模型不可用，无法执行末端增量移动。")
            tcp = self.get_tcp_pose()
            if not tcp.get("ok"):
                return tcp
            pose = tcp["data"]["tcp_pose"]
            target_xyz, target_rpy = model.compose_delta_target(
                current_xyz=pose["xyz"],
                current_rpy=pose.get("rpy", [0.0, 0.0, 0.0]),
                delta_xyz=[dx, dy, dz],
                delta_rpy=[drx, dry, drz],
                frame=frame,
            )
            # 如果没有旋转增量，只约束位置，沿用阶段五的容差策略。
            rpy = target_rpy if any(abs(value) > 1e-12 for value in (drx, dry, drz)) else None
            result = self.move_pose(target_xyz, rpy)
            if result.get("ok"):
                result.setdefault("data", {})["target_pose"] = {"xyz": target_xyz, "rpy": target_rpy, "frame": frame}
            return result
        except Exception as exc:
            return self._exception("末端增量移动失败", exc)

    def move_pose(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            ik = self.compute_ik(xyz, rpy)
            if not ik.get("ok"):
                return ik
            targets = ik["data"]["target_joints_deg"]
            result = self.move_joints(targets)
            if result.get("ok"):
                result.setdefault("data", {})["ik"] = ik["data"].get("ik")
                result["data"]["target_xyz"] = [float(value) for value in xyz]
                result["data"]["target_rpy"] = [float(value) for value in rpy] if rpy is not None else None
            return result
        except Exception as exc:
            return self._exception("末端位姿移动失败", exc)

    def home(self) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            self._ensure_controller()
            if hasattr(self.controller, "move_home"):
                result = self.controller.move_home()
            elif hasattr(self.controller, "回到默认姿态"):
                result = self.controller.回到默认姿态()
            else:
                return bridge_fail("当前控制器不支持 Home。")
            normalized = self._normalize_result(result, "Home 完成。")
            self._log("info" if normalized["ok"] else "error", "home", normalized["message"])
            return normalized
        except Exception as exc:
            return self._exception("Home 失败", exc)

    def stop(self) -> dict[str, Any]:
        """急停必须尽最大努力成功；未连接时也返回安全结果。"""

        try:
            if self.sequence_player is not None:
                try:
                    self.sequence_player.stop()
                except Exception:
                    pass
            if self.controller is not None and hasattr(self.controller, "stop") and self.is_connected():
                result = self.controller.stop()
                normalized = self._normalize_result(result, "已急停。")
            else:
                normalized = bridge_ok("已急停：当前未连接真实硬件或无需下发停止。")
            self._set_action_status("stopped", self.action_status.get("name", ""), "已停止")
            self._log("warning", "stop", normalized["message"])
            return normalized
        except Exception as exc:
            self.last_error = str(exc)
            self._log("error", "stop_failed", f"急停异常：{exc}", traceback=traceback.format_exc())
            return bridge_ok("急停请求已接收，但底层返回异常；请检查机械臂状态。", {"error": str(exc)})

    def set_gripper(self, open_ratio: float) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            self._ensure_controller()
            open_percent = max(0.0, min(100.0, float(open_ratio) * 100.0))
            if hasattr(self.controller, "set_gripper"):
                result = self.controller.set_gripper(open_percent)
            elif hasattr(self.controller, "设置夹爪"):
                result = self.controller.设置夹爪(open_percent)
            else:
                return bridge_fail("当前控制器不支持夹爪控制。")
            normalized = self._normalize_result(result, "夹爪控制完成。", {"open_ratio": open_percent / 100.0, "open_percent": open_percent})
            self._log("info" if normalized["ok"] else "error", "gripper", normalized["message"], open_percent=open_percent)
            return normalized
        except Exception as exc:
            return self._exception("夹爪控制失败", exc)

    # ------------------------------------------------------------------
    # 姿态
    # ------------------------------------------------------------------
    def list_poses(self) -> dict[str, Any]:
        try:
            manager = self._get_pose_manager()
            poses = []
            for name in manager.列出姿态():
                pose = manager.获取姿态(name)
                poses.append({"name": name, "pose": pose, "description": (pose or {}).get("说明", "")})
            return bridge_ok("姿态列表已加载。", {"poses": poses})
        except Exception as exc:
            return self._exception("读取姿态列表失败", exc)

    def save_pose(self, name: str, description: str = "") -> dict[str, Any]:
        try:
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state = state_result["data"]
            payload = {
                "关节角度": [float(state.get("joints_deg", {}).get(joint, 0.0)) for joint in JOINT_ORDER],
                "夹爪": float(state.get("gripper", {}).get("open_percent", 50.0)),
            }
            self._get_pose_manager().保存姿态(name, payload, description or "Web 控制台保存的当前姿态")
            self._log("info", "save_pose", f"已保存姿态：{name}", name=name)
            return bridge_ok(f"已保存姿态：{name}", {"pose": payload})
        except Exception as exc:
            return self._exception("保存姿态失败", exc)

    def goto_pose(self, name: str) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            pose = self._get_pose_manager().获取姿态(name)
            if pose is None:
                return bridge_fail(f"姿态不存在：{name}")
            self._ensure_controller()
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "apply_pose"):
                result = self.controller.apply_pose(pose)
                normalized = self._normalize_result(result, f"已前往姿态：{name}", {"pose": pose})
            elif hasattr(self.controller, "应用姿态"):
                normalized = self._normalize_result(self.controller.应用姿态(pose), f"已前往姿态：{name}", {"pose": pose})
            else:
                normalized = self.move_joints(self._pose_to_targets(pose))
            self._log("info" if normalized["ok"] else "error", "goto_pose", normalized["message"], name=name)
            return normalized
        except Exception as exc:
            return self._exception("前往姿态失败", exc)

    def delete_pose(self, name: str) -> dict[str, Any]:
        try:
            deleted = self._get_pose_manager().删除姿态(name)
            if not deleted:
                return bridge_fail(f"姿态不存在：{name}")
            self._log("info", "delete_pose", f"已删除姿态：{name}", name=name)
            return bridge_ok(f"已删除姿态：{name}")
        except Exception as exc:
            return self._exception("删除姿态失败", exc)

    # ------------------------------------------------------------------
    # 动作库
    # ------------------------------------------------------------------
    def list_actions(self) -> dict[str, Any]:
        try:
            library = self._get_action_library()
            actions = []
            for name in library.list_actions():
                summary = library.summarize_action(name)
                actions.append({"name": name, "summary": summary})
            return bridge_ok("动作列表已加载。", {"actions": actions})
        except Exception as exc:
            return self._exception("读取动作库失败", exc)

    def get_action(self, name: str) -> dict[str, Any]:
        try:
            library = self._get_action_library()
            action = library.load_action(name)
            summary = library.summarize_action(action)
            return bridge_ok("动作已加载。", {"name": name, "summary": summary, "action": action})
        except Exception as exc:
            return self._exception("读取动作详情失败", exc)

    def play_action(self, name: str, speed: float = 1.0, loop: bool = False) -> dict[str, Any]:
        """阻塞式动作播放；service 会把它放到后台线程里执行。"""

        try:
            self._ensure_connected_for_motion()
            self._ensure_controller()
            library = self._get_action_library()
            sequence = library.load_action(name)
            player = self._get_sequence_player()
            self._set_action_status("playing", name, f"播放中：{name}")
            ok = bool(player.play(sequence, loop=loop, speed=float(speed)))
            message = f"动作播放完成：{name}" if ok else f"动作播放未完成：{name}"
            self._set_action_status("idle" if ok else "stopped", name, message)
            self._log("info" if ok else "warning", "play_action", message, name=name, speed=speed, loop=loop)
            return bridge_ok(message, {"name": name}) if ok else bridge_fail(message, data={"name": name})
        except Exception as exc:
            self._set_action_status("error", name, f"动作播放失败：{exc}")
            return self._exception("动作播放失败", exc)

    def pause_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.pause()
        self._set_action_status("paused", self.action_status.get("name", ""), "动作已暂停。")
        return bridge_ok("动作已暂停。")

    def resume_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.resume()
        name = self.action_status.get("name", "")
        self._set_action_status("playing", name, f"继续播放：{name}" if name else "动作已继续。")
        return bridge_ok("动作已继续。")

    def stop_action(self) -> dict[str, Any]:
        if self.sequence_player is not None:
            self.sequence_player.stop()
        self._set_action_status("stopped", self.action_status.get("name", ""), "动作已停止。")
        return bridge_ok("动作已停止。")

    # ------------------------------------------------------------------
    # 运动学计算
    # ------------------------------------------------------------------
    def compute_fk(self, joints_deg: list[float]) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            targets = self._normalize_targets(joints_deg)
            q_rad = [math.radians(float(targets[joint])) for joint in JOINT_ORDER]
            if model is not None:
                pose = model.forward(q_rad)
                pose["source"] = pose.get("source", "stage5_fk")
            else:
                pose = self._approximate_tcp_pose(targets)
            return bridge_ok("FK 计算完成。", {"tcp_pose": pose})
        except Exception as exc:
            return self._exception("FK 计算失败", exc)

    def compute_ik(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return bridge_fail("运动学模型不可用，无法计算 IK。")
            current = self._current_joints_for_tcp()
            seed = [math.radians(float(current.get(joint, 0.0))) for joint in JOINT_ORDER]
            ik = model.inverse(
                target_xyz=[float(value) for value in xyz[:3]],
                target_rpy=[float(value) for value in rpy] if rpy is not None else None,
                seed_q_user=seed,
            )
            targets = {joint: math.degrees(float(ik["q_user_rad"][idx])) for idx, joint in enumerate(JOINT_ORDER)}
            return bridge_ok("IK 计算完成。", {"ik": ik, "target_joints_deg": targets})
        except Exception as exc:
            return self._exception("IK 计算失败", exc)

    # ------------------------------------------------------------------
    # 内部对象创建
    # ------------------------------------------------------------------
    def _ensure_controller(self) -> None:
        if self.controller is not None:
            return
        if self.mode == "sim":
            self.controller = self._create_sim_controller()
            return
        self.controller = self._create_real_controller(dry_run=(self.mode == "dry_run"))

    def _create_sim_controller(self) -> Any:
        from 机械臂模型_robot_arm import 机械臂模型

        config_path = self._resolve_config("sim_config_path", fallback_names=["配置_config.yaml"])
        config = self._read_structured(config_path)
        return 机械臂模型(config)

    def _create_real_controller(self, dry_run: bool) -> Any:
        from 真实机械臂控制器_real_arm_controller import RealArmController

        config_path = self._resolve_config("real_config_path")
        runtime_config = self._make_runtime_real_config(config_path, dry_run=dry_run)
        return RealArmController(runtime_config)

    def _get_pose_manager(self) -> Any:
        if self.pose_manager is None:
            from 姿态管理_pose_manager import 姿态管理器

            sim_config_path = self._resolve_config("sim_config_path", fallback_names=["配置_config.yaml"])
            sim_config = self._read_structured(sim_config_path)
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

            action_config = load_config(self._resolve_config("action_config_path"))
            # Web/service 已经做真实模式确认，禁止在后台线程 input() 阻塞服务。
            action_config.setdefault("safety", {})["require_confirm_before_real_replay"] = False
            self.sequence_player = SequencePlayer(self.controller, action_config)
        return self.sequence_player

    def _get_kinematics_model(self) -> Any | None:
        if self.kinematics_model is not None:
            return self.kinematics_model
        try:
            from 运动学模型_kinematics_model import 创建运动学模型

            self.kinematics_model = 创建运动学模型(self._resolve_config("kinematics_config_path"), use_gui=False)
            return self.kinematics_model
        except Exception as exc:
            # 运动学依赖缺失不应该让 Web 控制台整体不可用。
            self.last_error = str(exc)
            return None

    # ------------------------------------------------------------------
    # 数据整理
    # ------------------------------------------------------------------
    def _normalize_state(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            state = {}
        joints_raw = state.get("关节角度", state.get("joints_deg", state.get("joint_targets_deg", {})))
        if isinstance(joints_raw, Mapping):
            joints = {joint: float(joints_raw.get(joint, 0.0)) for joint in JOINT_ORDER}
        elif isinstance(joints_raw, list):
            joints = {joint: float(joints_raw[idx]) if idx < len(joints_raw) else 0.0 for idx, joint in enumerate(JOINT_ORDER)}
        else:
            joints = {joint: 0.0 for joint in JOINT_ORDER}

        gripper_raw = state.get("夹爪", state.get("gripper", state.get("gripper_state", {})))
        if isinstance(gripper_raw, Mapping):
            open_percent = gripper_raw.get("open_percent", gripper_raw.get("open_value", gripper_raw.get("开合", 50.0)))
        elif gripper_raw is None:
            open_percent = 50.0
        else:
            open_percent = gripper_raw

        return {
            "mode": self.mode,
            "connected": self.is_connected(),
            "joints_deg": joints,
            "joint_labels": dict(JOINT_LABELS),
            "gripper": {
                "open_percent": float(open_percent),
                "open_ratio": max(0.0, min(1.0, float(open_percent) / 100.0)),
            },
            "raw_present_position": state.get("raw_present_position", {}),
            "multi_turn_state": state.get("multi_turn_state", {}),
            "raw": state,
        }

    def _normalize_targets(self, targets: Mapping[str, float] | list[float]) -> dict[str, float]:
        if isinstance(targets, Mapping):
            return {self._normalize_joint_key(str(key)): float(value) for key, value in targets.items()}
        return {joint: float(targets[idx]) if idx < len(targets) else 0.0 for idx, joint in enumerate(JOINT_ORDER)}

    def _pose_to_targets(self, pose: Mapping[str, Any]) -> dict[str, float]:
        angles = pose.get("关节角度", [])
        return self._normalize_targets(angles)

    def _normalize_joint_key(self, value: str) -> str:
        text = str(value).strip()
        if text in JOINT_ORDER:
            return text
        mapping = {
            "J1": "shoulder_pan",
            "J2": "shoulder_lift",
            "J3": "elbow_flex",
            "J4": "wrist_flex",
            "J5": "wrist_roll",
            "1": "shoulder_pan",
            "2": "shoulder_lift",
            "3": "elbow_flex",
            "4": "wrist_flex",
            "5": "wrist_roll",
        }
        upper = text.upper()
        if upper in mapping:
            return mapping[upper]
        raise ValueError(f"未知关节：{value}")

    def _normalize_result(self, result: Any, default_message: str, data: Any | None = None) -> dict[str, Any]:
        if isinstance(result, dict) and "ok" in result:
            return result
        if hasattr(result, "成功"):
            success = bool(getattr(result, "成功"))
            message = str(getattr(result, "消息", default_message))
            return bridge_ok(message, data) if success else bridge_fail(message, data=data)
        if isinstance(result, bool):
            return bridge_ok(default_message, data) if result else bridge_fail(default_message, data=data)
        return bridge_ok(default_message, data)

    def _current_joints_for_tcp(self) -> dict[str, float]:
        try:
            if self.controller is not None:
                if hasattr(self.controller, "get_state"):
                    state = self.controller.get_state()
                elif hasattr(self.controller, "获取当前状态"):
                    state = self.controller.获取当前状态()
                else:
                    state = {}
                return self._normalize_state(state).get("joints_deg", {})
        except Exception:
            pass
        return {joint: 0.0 for joint in JOINT_ORDER}

    @staticmethod
    def _approximate_tcp_pose(joints: Mapping[str, float]) -> dict[str, Any]:
        """没有 pybullet / numpy 时的只读兜底，不能替代阶段五 IK。"""

        base = math.radians(float(joints.get("shoulder_pan", 0.0)))
        shoulder = math.radians(float(joints.get("shoulder_lift", 0.0)))
        elbow = math.radians(float(joints.get("elbow_flex", 0.0)))
        wrist = math.radians(float(joints.get("wrist_flex", 0.0)))
        l1, l2, l3 = 0.12, 0.12, 0.08
        reach = l1 * math.cos(shoulder) + l2 * math.cos(shoulder + elbow) + l3 * math.cos(shoulder + elbow + wrist)
        z = 0.08 + l1 * math.sin(shoulder) + l2 * math.sin(shoulder + elbow) + l3 * math.sin(shoulder + elbow + wrist)
        return {
            "xyz": [round(reach * math.cos(base), 6), round(reach * math.sin(base), 6), round(z, 6)],
            "rpy": [0.0, round(shoulder + elbow + wrist, 6), round(base + math.radians(float(joints.get("wrist_roll", 0.0))), 6)],
            "source": "approximate_fk_without_stage5",
        }

    # ------------------------------------------------------------------
    # 配置 / 路径 / 标定
    # ------------------------------------------------------------------
    def _resolve_config(self, key: str, fallback_names: list[str] | None = None) -> Path:
        value = self.config.get("controller", {}).get(key)
        if not value:
            raise KeyError(f"Web 配置缺少 controller.{key}")
        path = Path(value)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        if path.exists():
            return path
        for name in fallback_names or []:
            fallback = path.parent / name
            if fallback.exists():
                return fallback
        raise FileNotFoundError(f"配置文件不存在：{path}")

    def _read_structured(self, path: str | Path) -> dict[str, Any]:
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(text)
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
        data.setdefault("transport", {})["dry_run"] = bool(dry_run)
        calibration = data.setdefault("calibration", {})
        calibration_path = Path(calibration.get("path", "标定文件.json"))
        if not calibration_path.is_absolute():
            calibration["path"] = str((real_config_path.parent / calibration_path).resolve())
        runtime_name = "dry_run_hardware_state.json" if dry_run else "real_hardware_state.json"
        data.setdefault("files", {})["runtime_state"] = str(self.base_dir / "runtime" / "state" / runtime_name)
        temp_dir = Path(tempfile.gettempdir()) / "arm_web_control"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = temp_dir / ("dry_run_真实配置_runtime.json" if dry_run else "real_真实配置_runtime.json")
        self._write_json(target, data)
        self._runtime_real_config_path = target
        return target

    def _load_calibration_report_from_file(self) -> dict[str, Any]:
        from 标定管理_calibration_manager import CalibrationManager
        from 真实机械臂控制器_real_arm_controller import 读取配置

        real_config_path = self._resolve_config("real_config_path")
        config = 读取配置(real_config_path)
        cal_path = Path(config.get("calibration", {}).get("path", "标定文件.json"))
        if not cal_path.is_absolute():
            cal_path = real_config_path.parent / cal_path
        return CalibrationManager(cal_path, config).calibration_report()

    def _load_calibration_raw_items(self) -> dict[str, Any]:
        real_config_path = self._resolve_config("real_config_path")
        real_config = self._read_structured(real_config_path)
        cal_path = Path(real_config.get("calibration", {}).get("path", "标定文件.json"))
        if not cal_path.is_absolute():
            cal_path = real_config_path.parent / cal_path
        if not cal_path.exists():
            return {}
        try:
            data = json.loads(cal_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if isinstance(value, dict)}

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

    # ------------------------------------------------------------------
    # 安全 / 日志
    # ------------------------------------------------------------------
    def _ensure_connected_for_motion(self) -> None:
        if not self.is_connected():
            raise RuntimeError("尚未连接。请先通过 session/connect 连接控制器。")

    def _max_step_deg(self) -> float:
        key = "max_real_step_deg" if self.mode == "real" else "max_manual_step_deg"
        return float(self.config.get("safety", {}).get(key, 5.0))

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        value = str(mode).strip().lower()
        aliases = {"simulation": "sim", "模拟": "sim", "仿真": "sim", "dryrun": "dry_run", "dry-run": "dry_run", "真实": "real"}
        value = aliases.get(value, value)
        if value not in {"sim", "dry_run", "real"}:
            raise ValueError(f"未知模式：{mode}")
        return value

    def _set_action_status(self, state: str, name: str, message: str) -> None:
        now = time.time()
        started_at = self.action_status.get("started_at")
        if state == "playing" and self.action_status.get("state") != "playing":
            started_at = now
        self.action_status = {
            "state": state,
            "name": str(name or ""),
            "message": str(message),
            "started_at": started_at,
            "finished_at": now if state in {"idle", "stopped", "error"} else None,
        }

    def _log(self, level: str, event: str, message: str, **extra: Any) -> None:
        if self.logger is not None:
            self.logger.log(level, event, message, **extra)

    def _exception(self, message: str, exc: Exception) -> dict[str, Any]:
        self.last_error = str(exc)
        self._log("error", "exception", f"{message}：{exc}", traceback=traceback.format_exc())
        return bridge_fail(f"{message}：{exc}", exc)

    def copy_log_path_to(self, target: str | Path) -> Path:
        if self.logger is None:
            raise RuntimeError("logger 未初始化。")
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.logger.log_path, target_path)
        return target_path
