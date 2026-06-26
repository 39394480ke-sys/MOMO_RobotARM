"""阶段八 Web 专用 ControllerBridge。

这一层只做“Web API 到已有阶段控制器”的适配：
- dry-run / real 复用阶段四 RealArmController。
- sim 复用阶段三机械臂模型。
- TCP / IK 复用阶段五运动学模型。
- 动作库和动作回放复用阶段六 ActionLibrary / SequencePlayer。

注意：这里不直接导入 Feetech 底层驱动，也不提供 raw 舵机写入接口。
"""

from __future__ import annotations

import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Mapping

from .path_utils import WEB_DIR, ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    JOINT_ORDER,
    build_exception_context,
    check_python_modules,
    clamp_percent,
    clamp_symmetric,
    compute_fk_payload,
    compute_ik_payload,
    compute_tcp_pose_payload,
    current_joints_for_controller,
    delete_pose_from_manager,
    install_stage_paths,
    load_action_library,
    load_calibration_raw_items,
    load_calibration_report,
    load_kinematics_model,
    list_action_items,
    list_pose_items,
    load_action_detail,
    load_pose_manager,
    load_real_controller,
    load_sequence_player,
    load_sim_controller,
    make_config_resolver,
    normalize_bridge_result,
    normalize_control_mode,
    normalize_joint_key,
    normalize_joint_targets,
    normalize_playback_speed,
    normalize_robot_state_payload,
    play_action_from_library,
    read_controller_state,
    result_fail as bridge_fail,
    result_ok as bridge_ok,
    save_pose_from_state,
    set_controller_gripper,
    state_tcp_pose,
)
from 系统集成.integration.dependency_checker import DependencyChecker  # noqa: E402


class ControllerBridge:
    """Web 后端统一控制入口。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None, logger: Any | None = None):
        self.base_dir = Path(base_dir or WEB_DIR).resolve()
        self.project_root = self.base_dir.parent
        self.config = config
        self._config_resolver = make_config_resolver(self.config, self.base_dir, "Web", require_exists=True)
        self.logger = logger
        self.mode = normalize_control_mode(config.get("app", {}).get("default_mode", "dry_run"), simulation_value="sim")
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
        install_stage_paths(self.project_root)

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
                normalized = normalize_bridge_result(result, "连接完成。")
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
                normalized = normalize_bridge_result(result, "已断开。")
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
            normalized_mode = normalize_control_mode(mode, simulation_value="sim")
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
            state = read_controller_state(self.controller, prefer_detailed=True)
            normalized = self._normalize_state(state)
            normalized["tcp_pose"] = state_tcp_pose(self.kinematics_model, normalized.get("joints_deg", {}))
            normalized["mode"] = self.mode
            normalized["connected"] = self.is_connected()
            normalized["action"] = dict(self.action_status)
            return bridge_ok("状态已刷新。", normalized)
        except Exception as exc:
            return self._exception("读取状态失败", exc)

    def get_tcp_pose(self) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            joints = current_joints_for_controller(self.controller, prefer_detailed=False)
            return bridge_ok("TCP 已计算。", compute_tcp_pose_payload(model, joints))
        except Exception as exc:
            return bridge_fail("TCP 计算失败。", exc)

    def get_calibration_status(self) -> dict[str, Any]:
        try:
            if self.mode in {"dry_run", "real"}:
                self._ensure_controller()
                if self.controller is not None and hasattr(self.controller, "calibration_report"):
                    report = self.controller.calibration_report()
                else:
                    report = load_calibration_report(self._resolve_config("real_config_path"))
            else:
                report = load_calibration_report(self._resolve_config("real_config_path"))

            # 前端需要展示每个关节的 id / range / phase 等原始标定字段，这里补充 raw_items。
            raw_items = load_calibration_raw_items(self._resolve_config("real_config_path"))
            report["raw_items"] = raw_items
            return bridge_ok("标定状态已刷新。", {"calibration": report})
        except Exception as exc:
            return self._exception("读取标定状态失败", exc)

    def check_dependencies(self) -> dict[str, Any]:
        """检查依赖；dry-run 不要求 lerobot 可用。"""

        modules = ["fastapi", "uvicorn", "pydantic", "yaml", "numpy", "pybullet", "lerobot", "serial"]
        data: dict[str, Any] = check_python_modules(modules)
        real_hardware = DependencyChecker(self.config).check_real_hardware_dependencies()
        data["dry_run_requires_real_deps"] = False
        data["real_hardware"] = real_hardware
        data["real_mode_ready"] = all(real_hardware.values())
        data["real_mode_requires"] = list(real_hardware.keys())
        return bridge_ok("依赖检查完成。", data)

    # ------------------------------------------------------------------
    # 运动控制
    # ------------------------------------------------------------------
    def move_joint_delta(self, joint_key: str, delta_deg: float) -> dict[str, Any]:
        try:
            self._ensure_connected_for_motion()
            joint = normalize_joint_key(joint_key)
            max_step_key = "max_real_step_deg" if self.mode == "real" else "max_manual_step_deg"
            max_step = float(self.config.get("safety", {}).get(max_step_key, 5.0))
            delta = clamp_symmetric(float(delta_deg), max_step)
            self._ensure_controller()
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "jog_joint"):
                result = self.controller.jog_joint(joint, delta)
                normalized = normalize_bridge_result(result, "关节微调完成。", {"joint_key": joint, "delta_deg": delta})
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
            targets = normalize_joint_targets(targets_deg)
            if self.mode in {"dry_run", "real"} and hasattr(self.controller, "move_joints"):
                result = self.controller.move_joints(targets)
            elif hasattr(self.controller, "移动到关节角度"):
                result = self.controller.移动到关节角度([targets[joint] for joint in JOINT_ORDER])
            else:
                return bridge_fail("当前控制器不支持关节移动。")
            normalized = normalize_bridge_result(result, "关节移动完成。", {"targets_deg": targets})
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
            normalized = normalize_bridge_result(result, "Home 完成。")
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
                normalized = normalize_bridge_result(result, "已急停。")
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
            open_percent = clamp_percent(float(open_ratio) * 100.0)
            normalized = set_controller_gripper(
                self.controller,
                open_percent,
                connected=self.is_connected(),
                mode=self.mode,
                real_config_path=self._resolve_config("real_config_path"),
                include_open_ratio=True,
            )
            self._log("info" if normalized["ok"] else "error", "gripper", normalized["message"], open_percent=open_percent)
            return normalized
        except Exception as exc:
            return self._exception("夹爪控制失败", exc)

    # ------------------------------------------------------------------
    # 姿态
    # ------------------------------------------------------------------
    def list_poses(self) -> dict[str, Any]:
        try:
            return bridge_ok("姿态列表已加载。", {"poses": list_pose_items(self._get_pose_manager(), include_description=True)})
        except Exception as exc:
            return self._exception("读取姿态列表失败", exc)

    def save_pose(self, name: str, description: str = "") -> dict[str, Any]:
        try:
            state_result = self.get_state()
            if not state_result.get("ok"):
                return state_result
            state = state_result["data"]
            payload = save_pose_from_state(self._get_pose_manager(), name, state, description or "Web 控制台保存的当前姿态")
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
                normalized = normalize_bridge_result(result, f"已前往姿态：{name}", {"pose": pose})
            elif hasattr(self.controller, "应用姿态"):
                normalized = normalize_bridge_result(self.controller.应用姿态(pose), f"已前往姿态：{name}", {"pose": pose})
            else:
                normalized = self.move_joints(normalize_joint_targets(pose.get("关节角度", [])))
            self._log("info" if normalized["ok"] else "error", "goto_pose", normalized["message"], name=name)
            return normalized
        except Exception as exc:
            return self._exception("前往姿态失败", exc)

    def delete_pose(self, name: str) -> dict[str, Any]:
        try:
            deleted = delete_pose_from_manager(self._get_pose_manager(), name)
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
            return bridge_ok("动作列表已加载。", {"actions": list_action_items(self._get_action_library())})
        except Exception as exc:
            return self._exception("读取动作库失败", exc)

    def get_action(self, name: str) -> dict[str, Any]:
        try:
            return bridge_ok("动作已加载。", load_action_detail(self._get_action_library(), name))
        except Exception as exc:
            return self._exception("读取动作详情失败", exc)

    def play_action(self, name: str, speed: float = 1.0, loop: bool = False) -> dict[str, Any]:
        """阻塞式动作播放；service 会把它放到后台线程里执行。"""

        try:
            playback_speed = normalize_playback_speed(speed)
            self._ensure_connected_for_motion()
            self._ensure_controller()
            library = self._get_action_library()
            player = self._get_sequence_player()
            self._set_action_status("playing", name, f"播放中：{name}")
            ok = play_action_from_library(library, player, name, speed=playback_speed, loop=loop)
            message = f"动作播放完成：{name}" if ok else f"动作播放未完成：{name}"
            self._set_action_status("idle" if ok else "stopped", name, message)
            self._log("info" if ok else "warning", "play_action", message, name=name, speed=playback_speed, loop=loop)
            data = {"name": name, "speed": playback_speed}
            return bridge_ok(message, data) if ok else bridge_fail(message, data=data)
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
            return bridge_ok("FK 计算完成。", compute_fk_payload(model, joints_deg, allow_approx=True))
        except Exception as exc:
            return self._exception("FK 计算失败", exc)

    def compute_ik(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        try:
            model = self._get_kinematics_model()
            if model is None:
                return bridge_fail("运动学模型不可用，无法计算 IK。")
            current = current_joints_for_controller(self.controller, prefer_detailed=False)
            return bridge_ok("IK 计算完成。", compute_ik_payload(model, xyz, rpy, current))
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
        config_path = self._resolve_config("sim_config_path", fallback_names=["配置_config.yaml"])
        return load_sim_controller(config_path)

    def _create_real_controller(self, dry_run: bool) -> Any:
        config_path = self._resolve_config("real_config_path")
        runtime_name = "dry_run_hardware_state.json" if dry_run else "real_hardware_state.json"
        return load_real_controller(
            config_path,
            dry_run=dry_run,
            runtime_state_path=self.base_dir / "runtime" / "state" / runtime_name,
            temp_dir_name="arm_web_control",
        )

    def _get_pose_manager(self) -> Any:
        if self.pose_manager is None:
            sim_config_path = self._resolve_config("sim_config_path", fallback_names=["配置_config.yaml"])
            self.pose_manager = load_pose_manager(self.project_root, sim_config_path)
        return self.pose_manager

    def _get_action_library(self) -> Any:
        if self.action_library is None:
            self.action_library = load_action_library(self._resolve_config("action_config_path"))
        return self.action_library

    def _get_sequence_player(self) -> Any:
        if self.sequence_player is None:
            self.sequence_player = load_sequence_player(self.controller, self._resolve_config("action_config_path"))
        return self.sequence_player

    def _get_kinematics_model(self) -> Any | None:
        if self.kinematics_model is not None:
            return self.kinematics_model
        self.kinematics_model, self.last_error = load_kinematics_model(self._resolve_config("kinematics_config_path"))
        return self.kinematics_model

    # ------------------------------------------------------------------
    # 数据整理
    # ------------------------------------------------------------------
    def _normalize_state(self, state: Any) -> dict[str, Any]:
        state = state if isinstance(state, dict) else {}
        payload = normalize_robot_state_payload(
            state,
            self.mode,
            self.is_connected(),
            self._resolve_config("real_config_path"),
            include_gripper_state=True,
            include_open_ratio=True,
        )
        payload["raw_present_position"] = state.get("raw_present_position", {})
        payload["multi_turn_state"] = state.get("multi_turn_state", {})
        return payload

    # ------------------------------------------------------------------
    # 配置 / 路径 / 标定
    # ------------------------------------------------------------------
    def _resolve_config(self, key: str, fallback_names: list[str] | None = None) -> Path:
        return self._config_resolver(key, fallback_names)

    # ------------------------------------------------------------------
    # 安全 / 日志
    # ------------------------------------------------------------------
    def _ensure_connected_for_motion(self) -> None:
        if not self.is_connected():
            raise RuntimeError("尚未连接。请先通过 session/connect 连接控制器。")

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
        context = build_exception_context(message, exc)
        self.last_error = context["last_error"]
        self._log("error", "exception", context["message"], traceback=context["traceback"])
        return bridge_fail(context["message"], context["error"])

    def copy_log_path_to(self, target: str | Path) -> Path:
        if self.logger is None:
            raise RuntimeError("logger 未初始化。")
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.logger.log_path, target_path)
        return target_path
