"""阶段八 Web 专用 ControllerBridge。

这一层只做“Web API 到已有阶段控制器”的适配：
- dry-run / real 复用阶段四 RealArmController。
- sim 复用阶段三机械臂模型。
- TCP / IK 复用阶段五运动学模型。
- 动作库和动作回放复用阶段六 ActionLibrary / SequencePlayer。

注意：这里不直接导入 Feetech 底层驱动，也不提供 raw 舵机写入接口。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
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
    cinematic_real_speed_percent,
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
    resolve_base_path,
    result_fail as bridge_fail,
    result_ok as bridge_ok,
    save_pose_from_state,
    sanitize_action_name,
    set_controller_gripper,
    state_tcp_pose,
)
from 系统集成.integration.dependency_checker import DependencyChecker  # noqa: E402
from 通用_io import atomic_write_json, env_value, read_json_object_or_default, timestamped_json_path  # noqa: E402


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

    def check_real_hardware(self) -> dict[str, Any]:
        """真实硬件只读检查，不写舵机寄存器。"""

        data: dict[str, Any] = {
            "checked_at": time.time(),
            "port": self._real_hardware_port(),
            "expected_ids": [10, 11, 12, 13, 14, 15],
            "dependencies": {},
            "calibration": {},
            "serial": {},
            "driver": {},
            "readonly_scan": {},
            "ok": False,
            "errors": [],
        }

        deps = self.check_dependencies().get("data", {})
        data["dependencies"] = {
            "real_mode_ready": bool(deps.get("real_mode_ready")),
            "real_hardware": deps.get("real_hardware", {}),
        }
        if not data["dependencies"]["real_mode_ready"]:
            data["errors"].append("真实硬件依赖未就绪。")

        data["calibration"] = self._hardware_calibration_summary()
        if not data["calibration"].get("exists"):
            data["errors"].append("标定文件不存在。")

        data["serial"] = self._hardware_serial_summary(data["port"])
        if not data["serial"].get("exists"):
            data["errors"].append(f"串口不存在：{data['port']}")

        data["driver"] = self._hardware_driver_summary()
        if platform.system() == "Linux" and Path("/dev").exists() and str(data["port"]).startswith("/dev/"):
            if not data["driver"].get("usb_ch343"):
                data["errors"].append("CH343 驱动未加载或未接管 1a86:55d3。")

        if data["dependencies"]["real_mode_ready"] and data["serial"].get("exists"):
            if self.mode == "real" and self.is_connected() and self.controller is not None:
                data["readonly_scan"] = self._hardware_readonly_from_connected_controller()
            else:
                data["readonly_scan"] = self._hardware_readonly_scan(str(data["port"]))
            if not data["readonly_scan"].get("ok"):
                data["errors"].append(data["readonly_scan"].get("message", "只读扫描失败。"))

        data["ok"] = not data["errors"]
        message = "真实硬件检查通过。" if data["ok"] else "真实硬件检查未通过。"
        return bridge_ok(message, data)

    def get_joint_diagnostics(self, joint_key: str = "j12") -> dict[str, Any]:
        """只读诊断某个关节的 raw -> 逻辑角度 -> 限位状态。"""

        try:
            joint = normalize_joint_key(joint_key)
            config_path = self._resolve_config("real_config_path")
            config, calibration, calibration_path = self._load_real_calibration(config_path)
            joint_config = self._joint_config(config, joint)
            calibration_entry = calibration.get(joint)
            if not isinstance(calibration_entry, dict):
                return bridge_fail(f"{joint} 缺少标定项。")

            present_raw = self._read_present_raw_for_joint(config, calibration, joint)
            from 角度映射_angle_mapper import joint_deg_to_goal_detail, present_raw_to_joint_detail

            detail = present_raw_to_joint_detail(joint, present_raw, joint_config, calibration_entry)
            min_deg = float(joint_config.get("最小角度", -180.0))
            max_deg = float(joint_config.get("最大角度", 180.0))
            current_deg = float(detail["joint_deg"])
            in_limit = min_deg <= current_deg <= max_deg
            zero_goal = joint_deg_to_goal_detail(joint, 0.0, joint_config, calibration_entry)
            return bridge_ok(
                "关节诊断已完成。",
                {
                    "joint_key": joint,
                    "label": detail.get("show_name"),
                    "calibration_path": str(calibration_path),
                    "present_raw": int(present_raw),
                    "current_angle_deg": current_deg,
                    "min_angle_deg": min_deg,
                    "max_angle_deg": max_deg,
                    "in_limit": in_limit,
                    "reason": "当前角度在软件限位内。" if in_limit else f"当前角度 {current_deg:.2f} 超出 [{min_deg:.2f}, {max_deg:.2f}]。",
                    "mapping": detail,
                    "zero_goal": zero_goal,
                    "calibration_entry": calibration_entry,
                },
            )
        except Exception as exc:
            return self._exception("关节诊断失败", exc)

    def set_calibration_current_angle(self, joint_key: str, current_angle_deg: float) -> dict[str, Any]:
        """把当前 Present_Position 标记为指定逻辑角度，不移动舵机。"""

        return self.set_calibration_current_angles({joint_key: current_angle_deg})

    def set_calibration_current_angles(self, joint_angles_deg: Mapping[str, float]) -> dict[str, Any]:
        """批量把当前 Present_Position 标记为指定逻辑角度，不移动舵机。"""

        try:
            assignments = {normalize_joint_key(joint): float(angle) for joint, angle in dict(joint_angles_deg).items()}
            if not assignments:
                return bridge_fail("没有可保存的标定修正项。")
            config_path = self._resolve_config("real_config_path")
            config, calibration, calibration_path = self._load_real_calibration(config_path)

            updates: dict[str, dict[str, Any]] = {}
            for joint, angle in assignments.items():
                updates[joint] = self._build_current_angle_calibration_update(config, calibration, joint, angle)
                calibration[joint] = updates[joint]["updated_entry"]

            meta = dict(calibration.get("_meta", {})) if isinstance(calibration.get("_meta"), dict) else {}
            meta["updated_at_unix_s"] = time.time()
            meta["updated_by"] = "Web set_calibration_current_angles"
            meta["last_current_angle_update"] = [
                {
                    "joint_key": joint,
                    "present_raw": int(item["present_raw"]),
                    "assigned_angle_deg": float(item["assigned_angle_deg"]),
                    "old_home_present_raw": item["old_home_present_raw"],
                    "new_home_present_raw": item["new_home_present_raw"],
                }
                for joint, item in updates.items()
            ]
            calibration["_meta"] = meta

            backup_dir = calibration_path.parent / "标定备份_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = timestamped_json_path(backup_dir, f"{calibration_path.stem}_backup")
            if calibration_path.exists():
                shutil.copy2(calibration_path, backup_path)
            atomic_write_json(calibration_path, calibration)

            self._log(
                "warning",
                "calibration_current_angles_updated",
                f"已批量更新 {len(updates)} 个多圈关节标定。",
                joints=list(updates),
                backup_path=str(backup_path),
            )
            return bridge_ok(
                "标定修正已保存；未写 Goal_Position，舵机未移动。",
                {
                    "updates": {
                        joint: {
                            "joint_key": joint,
                            "present_raw": int(item["present_raw"]),
                            "assigned_angle_deg": float(item["assigned_angle_deg"]),
                            "old_mapping": item["old_detail"],
                            "new_mapping": item["new_detail"],
                            "old_home_present_raw": item["old_home_present_raw"],
                            "new_home_present_raw": item["new_home_present_raw"],
                        }
                        for joint, item in updates.items()
                    },
                    "calibration_path": str(calibration_path),
                    "backup_path": str(backup_path),
                },
            )
        except Exception as exc:
            return self._exception("保存标定修正失败", exc)

    def _build_current_angle_calibration_update(
        self,
        config: dict[str, Any],
        calibration: dict[str, Any],
        joint: str,
        current_angle_deg: float,
    ) -> dict[str, Any]:
        joint_config = self._joint_config(config, joint)
        calibration_entry = calibration.get(joint)
        if not isinstance(calibration_entry, dict):
            raise RuntimeError(f"{joint} 缺少标定项。")
        if str(calibration_entry.get("模式", joint_config.get("模式", ""))) != "多圈":
            raise RuntimeError("当前 Web 修正入口只支持 J10/J11/J12/J13/J15 多圈关节。")

        present_raw = self._read_present_raw_for_joint(config, calibration, joint)
        from 角度映射_angle_mapper import (
            RAW_COUNTS_PER_REV,
            joint_deg_to_relative_raw,
            present_raw_to_joint_detail,
            获取关节比例,
            获取方向,
        )

        old_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, calibration_entry)
        relative_raw = joint_deg_to_relative_raw(
            joint,
            float(current_angle_deg),
            获取关节比例(joint, joint_config),
            获取方向(calibration_entry),
        )
        new_home_raw = int(round(int(present_raw) - int(relative_raw)))
        updated_entry = dict(calibration_entry)
        updated_entry["home_present_raw"] = new_home_raw
        updated_entry["home_present_wrapped_raw"] = new_home_raw % RAW_COUNTS_PER_REV
        new_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, updated_entry)
        return {
            "present_raw": int(present_raw),
            "assigned_angle_deg": float(current_angle_deg),
            "old_detail": old_detail,
            "new_detail": new_detail,
            "old_home_present_raw": calibration_entry.get("home_present_raw"),
            "new_home_present_raw": new_home_raw,
            "updated_entry": updated_entry,
        }

    def _real_hardware_port(self) -> str:
        env_paths = (self.project_root / ".env", self.base_dir / "环境变量.env", self.project_root / "系统集成" / "环境变量.env")
        env_port = str(env_value("ARM_ROBOT_PORT", "", env_paths=env_paths) or "").strip()
        if env_port:
            return env_port
        try:
            real_config = self._resolve_config("real_config_path")
            ensure_project_root_on_path()
            from 真实机械臂控制器_real_arm_controller import 读取配置

            return str(读取配置(real_config).get("transport", {}).get("port", ""))
        except Exception:
            return ""

    def _load_real_calibration(self, config_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
        from 真实机械臂控制器_real_arm_controller import 读取配置
        from 真实路径工具_real_path_utils import resolve_real_path

        config = 读取配置(config_path)
        calibration_value = config.get("calibration", {}).get("path", "标定文件.json")
        calibration_path = resolve_real_path(calibration_value, Path(config_path).parent)
        calibration = read_json_object_or_default(calibration_path)
        return config, calibration, calibration_path

    @staticmethod
    def _joint_config(config: dict[str, Any], joint_key: str) -> dict[str, Any]:
        joint_config: dict[str, Any] = {}
        for item in config.get("robot", {}).get("joints", []):
            if item.get("key") == joint_key:
                joint_config = dict(item)
                break
        scales = config.get("robot", {}).get("joint_scales", {}) or config.get("robot", {}).get("关节减速比_joint_scales", {})
        if joint_key in scales:
            joint_config["joint_scale"] = float(scales[joint_key])
        if not joint_config:
            raise KeyError(f"未知关节：{joint_key}")
        return joint_config

    def _read_present_raw_for_joint(self, config: dict[str, Any], calibration: dict[str, Any], joint_key: str) -> int:
        port = self._real_hardware_port()
        if not port:
            raise RuntimeError("没有真实串口；请设置 ARM_ROBOT_PORT 或真实配置 transport.port。")
        from 轻量舵机驱动_lightweight_feetech_driver import LightweightFeetechBus, build_motor_ids

        motor_ids_by_joint = build_motor_ids(config, calibration, [joint_key])
        bus = LightweightFeetechBus(
            port,
            motor_ids_by_joint,
            baudrate=int(config.get("transport", {}).get("baudrate", 1_000_000)),
        )
        try:
            found = bus.connect()
            motor_id = motor_ids_by_joint[joint_key]
            if int(motor_id) not in {int(item) for item in found}:
                raise RuntimeError(f"{joint_key} ID {motor_id} 未响应。")
            return int(bus.read("Present_Position", joint_key))
        finally:
            bus.disconnect()

    def _hardware_calibration_summary(self) -> dict[str, Any]:
        try:
            report = load_calibration_report(self._resolve_config("real_config_path"))
            return {
                "exists": bool(report.get("是否存在")),
                "allowed": bool(report.get("允许真机移动")),
                "path": report.get("标定文件", ""),
            }
        except Exception as exc:
            return {"exists": False, "allowed": False, "path": "", "error": str(exc)}

    def _hardware_serial_summary(self, port: str) -> dict[str, Any]:
        path = Path(str(port)) if port else Path("")
        exists = bool(port) and path.exists()
        return {
            "port": port,
            "exists": exists,
            "is_symlink": bool(port) and path.is_symlink(),
            "target": str(path.resolve()) if exists else "",
            "parent_exists": bool(port) and path.parent.exists(),
        }

    def _hardware_driver_summary(self) -> dict[str, Any]:
        lsusb_tree = self._run_command(["lsusb", "-t"])
        lsmod = self._run_command(["lsmod"])
        return {
            "usb_ch343": "Driver=usb_ch343" in lsusb_tree or "\nch343 " in f"\n{lsmod}",
            "option_bound": "Driver=option" in lsusb_tree,
            "lsusb_tree": lsusb_tree,
            "ch343_loaded": "\nch343 " in f"\n{lsmod}",
        }

    def _hardware_readonly_scan(self, port: str) -> dict[str, Any]:
        try:
            ensure_project_root_on_path()
            from 真实机械臂控制器_real_arm_controller import 读取配置
            from 真实路径工具_real_path_utils import resolve_real_path
            from 标定工具_calibration_utils import JOINTS
            from 轻量舵机驱动_lightweight_feetech_driver import (
                EXPECTED_STS3215_MODEL,
                LightweightFeetechBus,
                build_motor_ids,
            )
            from 通用_io import read_json_object_or_default

            config_path = self._resolve_config("real_config_path")
            config = 读取配置(config_path)
            calibration_value = config.get("calibration", {}).get("path", "标定文件.json")
            calibration_path = resolve_real_path(calibration_value, Path(config_path).parent)
            calibration = read_json_object_or_default(calibration_path)
            joint_keys = list(JOINTS)
            motor_ids_by_joint = build_motor_ids(config, calibration, joint_keys)
            bus = LightweightFeetechBus(
                port,
                motor_ids_by_joint,
                baudrate=int(config.get("transport", {}).get("baudrate", 1_000_000)),
            )
            try:
                found = bus.connect()
                positions = bus.read_many("Present_Position", list(motor_ids_by_joint))
            finally:
                bus.disconnect()

            expected_ids = set(motor_ids_by_joint.values())
            found_ids = set(found)
            missing = sorted(expected_ids - found_ids)
            wrong_model = {
                motor_id: model
                for motor_id, model in found.items()
                if motor_id in expected_ids and int(model) != EXPECTED_STS3215_MODEL
            }
            ok = not missing and not wrong_model
            return {
                "ok": ok,
                "message": "只读扫描通过。" if ok else "只读扫描未完整通过。",
                "expected_ids": sorted(expected_ids),
                "found_models": found,
                "missing_ids": missing,
                "wrong_model": wrong_model,
                "present_position": positions,
            }
        except Exception as exc:
            return {"ok": False, "message": f"只读扫描失败：{exc}"}

    def _hardware_readonly_from_connected_controller(self) -> dict[str, Any]:
        try:
            state = read_controller_state(self.controller, prefer_detailed=True)
            if "错误" in state:
                return {"ok": False, "source": "connected_controller", "message": str(state["错误"])}
            raw = state.get("raw_present_position") or {}
            found = {
                str(self._motor_id_for_joint(joint_key)): 777
                for joint_key, value in raw.items()
                if joint_key in JOINT_ORDER and value is not None
            }
            missing = [str(motor_id) for motor_id in (10, 11, 12, 13, 14, 15) if str(motor_id) not in found]
            return {
                "ok": not missing,
                "source": "connected_controller",
                "message": "已复用当前 real 控制器读取状态。" if not missing else f"已连接控制器缺少 ID：{', '.join(missing)}",
                "expected_ids": [10, 11, 12, 13, 14, 15],
                "found_models": found,
                "missing_ids": missing,
                "wrong_model": {},
                "present_position": {key: int(value) for key, value in raw.items() if key in JOINT_ORDER},
            }
        except Exception as exc:
            return {"ok": False, "source": "connected_controller", "message": f"复用当前控制器读取失败：{exc}"}

    def _motor_id_for_joint(self, joint_key: str) -> int:
        try:
            joint_config = getattr(self.controller, "joint_config_by_key", {}).get(joint_key, {})
            if "舵机ID" in joint_config:
                return int(joint_config["舵机ID"])
        except Exception:
            pass
        defaults = {"j10": 10, "j11": 11, "j12": 12, "j13": 13, "j14": 14, "j15": 15}
        return defaults.get(joint_key, -1)

    @staticmethod
    def _run_command(command: list[str], timeout: float = 2.0) -> str:
        try:
            return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout).stdout
        except Exception:
            return ""

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

    def home_precheck(self) -> dict[str, Any]:
        """只计算 Home 目标和安全检查，不写真实舵机。"""

        try:
            self._ensure_controller()
            controller = self.controller
            if controller is None:
                return bridge_fail("控制器不可用，无法检查 Home。")
            joint_order = list(getattr(controller, "joint_order", JOINT_ORDER))
            joint_config_by_key = getattr(controller, "joint_config_by_key", {})
            calibration_manager = getattr(controller, "calibration_manager", None)
            safety_checker = getattr(controller, "safety_checker", None)
            runtime_state = getattr(controller, "runtime_state", {})
            if calibration_manager is None or safety_checker is None:
                return bridge_fail("当前控制器缺少标定或安全检查器。")

            targets = {
                joint_key: float(joint_config_by_key[joint_key].get("默认角度", 0.0))
                for joint_key in joint_order
            }
            angle_check = safety_checker.check_all_joint_angles(targets, joint_config_by_key)
            calibration_check = safety_checker.check_calibration_for_move(list(targets))

            from 角度映射_angle_mapper import joint_deg_to_goal_detail

            details: dict[str, Any] = {}
            goal_raw_by_joint: dict[str, int] = {}
            calibration_by_joint: dict[str, dict[str, Any]] = {}
            errors: list[str] = []
            for joint_key, target_deg in targets.items():
                try:
                    entry = controller._calibration_entry_for_move(joint_key)
                    calibration_by_joint[joint_key] = entry
                    detail = joint_deg_to_goal_detail(
                        joint_key,
                        target_deg,
                        joint_config_by_key[joint_key],
                        entry,
                        runtime_state,
                    )
                    details[joint_key] = detail
                    goal_raw_by_joint[joint_key] = int(detail["goal_raw"])
                except Exception as exc:
                    errors.append(f"{joint_key}: {exc}")

            raw_check = safety_checker.check_goal_raws(goal_raw_by_joint, calibration_by_joint) if not errors else None
            ok = bool(angle_check.成功 and calibration_check.成功 and not errors and (raw_check is None or raw_check.成功))
            messages = [angle_check.消息, calibration_check.消息]
            if raw_check is not None:
                messages.append(raw_check.消息)
            messages.extend(errors)
            return bridge_ok(
                "Home 预检查通过。" if ok else "Home 预检查未通过。",
                {
                    "ok": ok,
                    "mode": self.mode,
                    "connected": self.is_connected(),
                    "targets_deg": targets,
                    "goal_raw_by_joint": goal_raw_by_joint,
                    "details": details,
                    "messages": messages,
                },
            )
        except Exception as exc:
            return self._exception("Home 预检查失败", exc)

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
    # AI 运镜
    # ------------------------------------------------------------------
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
            return bridge_ok("AI 运镜试拍分析完成。", {"project_path": str(project_path), "project": project})
        except Exception as exc:
            return self._exception("AI 运镜分析失败", exc)

    def cinematic_select_keyframes(self, project_path: str, min_count: int = 3, max_count: int = 8) -> dict[str, Any]:
        try:
            from 运镜导演_cinematic_director import CinematicDirector, DirectorDefaults, load_project

            path = self._resolve_project_path(project_path)
            director = CinematicDirector(
                self.project_root,
                DirectorDefaults(target_fps=float(self.config.get("motion", {}).get("playback_update_hz", 20.0))),
            )
            project = load_project(path)
            keyframes = director.select_keyframes(project, min_count=min_count, max_count=max_count)
            project["director_keyframes"] = keyframes
            project["workflow_stage"] = "director_keyframes"
            atomic_write_json(path, project)
            self._log("info", "cinematic_keyframes", "AI 运镜关键帧已生成。", project_path=str(path), keyframe_count=len(keyframes))
            return bridge_ok("AI 运镜关键帧已生成。", {"project_path": str(path), "project": project, "keyframes": keyframes})
        except Exception as exc:
            return self._exception("AI 运镜关键帧生成失败", exc)

    def cinematic_generate_action(self, project_path: str, action_name: str = "") -> dict[str, Any]:
        try:
            from 运镜导演_cinematic_director import CinematicDirector, DirectorDefaults, load_project

            path = self._resolve_project_path(project_path)
            motion = self.config.get("motion", {})
            speed_percent = float(motion.get("default_speed_percent", 50.0))
            director = CinematicDirector(
                self.project_root,
                DirectorDefaults(
                    target_fps=float(motion.get("playback_update_hz", 20.0)),
                    dry_run_speed_percent=speed_percent,
                    real_speed_percent=cinematic_real_speed_percent(speed_percent),
                ),
            )
            project = load_project(path)
            keyframes = project.get("director_keyframes", [])
            if not isinstance(keyframes, list) or len(keyframes) < 2:
                keyframes = director.select_keyframes(project)
                project["director_keyframes"] = keyframes
            if any(not item.get("pose", {}).get("joints_deg") for item in keyframes if isinstance(item, dict)):
                return bridge_fail("关键帧缺少同步关节状态，不能生成可执行动作。")
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
            return bridge_ok(
                f"AI 运镜动作已生成：{name}",
                {
                    "project_path": str(path),
                    "project": project,
                    "action_name": name,
                    "action_path": str(saved_path),
                    "pose_count": payload.get("pose_count", 0),
                },
            )
        except Exception as exc:
            return self._exception("AI 运镜动作生成失败", exc)

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

    def _resolve_project_path(self, path_value: str | Path) -> Path:
        return resolve_base_path(path_value, self.project_root)

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
