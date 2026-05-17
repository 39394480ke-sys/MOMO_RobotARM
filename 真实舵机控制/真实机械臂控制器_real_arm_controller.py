"""真实机械臂控制器。

这个控制器把配置、标定、安全检查、角度映射和舵机驱动串起来。
它按 Feetech 舵机控制、标定和安全检查流程组织，保留小白可读结构。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 安全检查_safety_checker import SafetyChecker
from 标定管理_calibration_manager import CalibrationManager
from 舵机驱动_servo_driver import BaseServoDriver, RealServoDriver, MockServoDriver
from 角度映射_angle_mapper import (
    JOINT_ORDER,
    MULTI_TURN_JOINTS,
    gripper_open_value_to_raw,
    gripper_raw_to_open_value,
    joint_deg_to_goal_detail,
    joint_label,
    present_raw_to_joint_detail,
)


@dataclass(frozen=True)
class 操作结果:
    """和阶段三保持一致的简单结果对象。"""

    成功: bool
    消息: str


class RealArmController:
    """真实机械臂控制器。"""

    def __init__(self, config_path: str | Path | None = None):
        self.base_dir = Path(__file__).resolve().parent
        self.config_path = Path(config_path) if config_path else self.base_dir / "真实配置.yaml"
        if not self.config_path.is_absolute():
            self.config_path = self.base_dir / self.config_path

        self.config = 读取配置(self.config_path)
        self.joint_order = list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))
        self.joint_config_by_key = self._build_joint_config_by_key()

        calibration_path = self._resolve_path(self.config.get("calibration", {}).get("path", "标定文件.json"))
        self.calibration_manager = CalibrationManager(calibration_path, self.config)
        self.safety_checker = SafetyChecker(self.config, self.calibration_manager)

        self.runtime_state_path = self._resolve_path(
            self.config.get("files", {}).get("runtime_state", "硬件状态记录_runtime_state.json")
        )
        self.runtime_state: dict[str, Any] = self._load_runtime_state()
        self.driver: BaseServoDriver = self._create_driver()
        self.connected = False

        self.current_raw: dict[str, int] = {}
        self.current_joint_deg: dict[str, float] = {
            joint_key: float(self.joint_config_by_key[joint_key].get("默认角度", 0))
            for joint_key in self.joint_order
        }
        self.current_gripper = float(self.config.get("gripper", {}).get("默认开合", 50))

    def connect(self) -> 操作结果:
        """连接驱动并读取当前位置。"""

        try:
            self._reload_config_and_calibration()
            report = self.calibration_manager.calibration_report()
            if not report["允许真机移动"] and not self.is_dry_run():
                return 操作结果(
                    False,
                    "缺少标定文件或标定不完整，请先运行 标定程序_calibrate.py。",
                )

            print(self.safety_checker.startup_warning())
            self.driver.connect()
            self.connected = True
            self.current_raw = self.driver.read_all_present_positions()
            self.runtime_state["connected"] = True
            self.runtime_state["dry_run"] = self.is_dry_run()
            self.runtime_state["calibration_path"] = str(self.calibration_manager.path)
            self.runtime_state["startup_present_raw"] = self._build_calibrated_startup_raw()
            self._refresh_state_from_raw(self.current_raw)
            self._save_runtime_state()
            if self.is_dry_run():
                return 操作结果(True, "连接成功，已加载标定文件并读取 dry-run 舵机状态。")
            return 操作结果(
                True,
                f"已连接真实机械臂。已加载标定文件：{self.calibration_manager.path.name}。"
                "当前状态已根据 zero_present_raw / home_present_raw 计算。"
                "如果机械零点不正确，请运行 标定程序_calibrate.py。",
            )
        except Exception as 错误:
            self.connected = False
            return 操作结果(False, f"连接失败：{错误}")

    def disconnect(self, disable_torque: bool = True) -> 操作结果:
        """断开驱动。"""

        try:
            self.driver.disconnect(disable_torque=disable_torque)
            self.connected = False
            self.runtime_state["connected"] = False
            self._save_runtime_state()
            return 操作结果(True, "已断开。")
        except Exception as 错误:
            return 操作结果(False, f"断开失败：{错误}")

    def is_dry_run(self) -> bool:
        """当前是否 dry-run。"""

        return bool(self.config.get("transport", {}).get("dry_run", True))

    def set_dry_run(self, enabled: bool, persist: bool = True) -> 操作结果:
        """切换 dry-run。切换后需要重新连接。"""

        was_connected = self.connected
        if was_connected:
            self.driver.disconnect(disable_torque=False)
            self.connected = False

        self.config.setdefault("transport", {})["dry_run"] = bool(enabled)
        self.safety_checker = SafetyChecker(self.config, self.calibration_manager)
        self.driver = self._create_driver()
        self.runtime_state["dry_run"] = bool(enabled)
        self.runtime_state["connected"] = False
        self._save_runtime_state()

        if persist:
            写入_json(self.config_path, self.config)

        模式 = "dry-run" if enabled else "真实模式"
        suffix = "，请重新执行“连接”。" if was_connected else ""
        return 操作结果(True, f"已切换为 {模式}{suffix}")

    def get_state(self) -> dict[str, Any]:
        """返回当前状态。"""

        if self.connected:
            try:
                self.current_raw = self.driver.read_all_present_positions()
                self._refresh_state_from_raw(self.current_raw)
                self._save_runtime_state()
            except Exception as 错误:
                return {"错误": f"读取状态失败：{错误}"}

        return {
            "模式": "dry-run" if self.is_dry_run() else "真实模式",
            "已连接": self.connected,
            "关节角度": dict(self.current_joint_deg),
            "goal_joint_targets_deg": dict(self.runtime_state.get("goal_joint_targets_deg", {})),
            "goal_raw_by_joint": dict(self.runtime_state.get("goal_raw_by_joint", {})),
            "raw_present_position": dict(self.current_raw),
            "multi_turn_state": dict(self.runtime_state.get("multi_turn_state", {})) if self.current_raw else {},
            "夹爪": dict(self.runtime_state.get("gripper", {"开合": self.current_gripper}))
            if "gripper" in self.current_raw
            else {"open_value": self.current_gripper},
        }

    def move_joints(self, target_deg_by_joint: dict[str, float]) -> 操作结果:
        """移动一组关节。输入为 joint_key -> 逻辑角度。"""

        if not self.connected:
            return 操作结果(False, "尚未连接。请先输入：连接")

        try:
            target_deg_by_joint = {key: float(value) for key, value in target_deg_by_joint.items()}
            angle_check = self.safety_checker.check_all_joint_angles(target_deg_by_joint, self.joint_config_by_key)
            if not angle_check.成功:
                return 操作结果(False, angle_check.消息)

            calibration_check = self.safety_checker.check_calibration_for_move()
            if not calibration_check.成功:
                return 操作结果(False, calibration_check.消息)

            detail_by_joint: dict[str, dict[str, Any]] = {}
            goal_raw_by_joint: dict[str, int] = {}
            calibration_by_joint: dict[str, dict[str, Any]] = {}
            for joint_key, target_deg in target_deg_by_joint.items():
                entry = self.calibration_manager.get(joint_key)
                calibration_by_joint[joint_key] = entry
                detail = joint_deg_to_goal_detail(
                    joint_key,
                    target_deg,
                    self.joint_config_by_key[joint_key],
                    entry,
                    self.runtime_state,
                )
                detail_by_joint[joint_key] = detail
                goal_raw_by_joint[joint_key] = int(detail["goal_raw"])

            raw_check = self.safety_checker.check_goal_raws(goal_raw_by_joint, calibration_by_joint)
            if not raw_check.成功:
                return 操作结果(False, raw_check.消息)

            self._print_goal_raw_plan(detail_by_joint)
            if not self.is_dry_run():
                self.driver.enable_torque()
            self.driver.write_many_goal_positions(goal_raw_by_joint)
            self.current_raw.update(goal_raw_by_joint)
            for joint_key, target_deg in target_deg_by_joint.items():
                self.current_joint_deg[joint_key] = float(target_deg)
            self.runtime_state["goal_joint_targets_deg"] = {
                **dict(self.runtime_state.get("goal_joint_targets_deg", {})),
                **{joint_key: float(target_deg) for joint_key, target_deg in target_deg_by_joint.items()},
            }
            self.runtime_state["goal_raw_by_joint"] = {
                **dict(self.runtime_state.get("goal_raw_by_joint", {})),
                **{joint_key: int(goal_raw) for joint_key, goal_raw in goal_raw_by_joint.items()},
            }
            self._refresh_state_from_raw(self.driver.read_all_present_positions())
            self._save_runtime_state()
            return 操作结果(True, "移动命令已完成。" if self.is_dry_run() else "真实移动命令已写入舵机。")
        except Exception as 错误:
            return 操作结果(False, f"移动失败：{错误}")

    def move_joint(self, joint_key: str, target_deg: float) -> 操作结果:
        """移动单个关节。"""

        if joint_key not in self.joint_config_by_key:
            return 操作结果(False, f"未知关节：{joint_key}")
        return self.move_joints({joint_key: float(target_deg)})

    def jog_joint(self, joint_key: str, delta_deg: float) -> 操作结果:
        """相对当前位置微调单个关节。"""

        if joint_key not in self.joint_config_by_key:
            return 操作结果(False, f"未知关节：{joint_key}")
        if not self.connected:
            return 操作结果(False, "尚未连接。请先输入：连接")

        state = self.get_state()
        if "错误" in state:
            return 操作结果(False, state["错误"])
        current_deg = float(state.get("关节角度", {}).get(joint_key, self.current_joint_deg.get(joint_key, 0.0)))
        target_deg = current_deg + float(delta_deg)
        print(
            f"{joint_label(joint_key)} 当前角度={current_deg:.2f} 度，"
            f"微调={float(delta_deg):+.2f} 度，目标角度={target_deg:.2f} 度。"
        )
        return self.move_joint(joint_key, target_deg)

    def move_home(self) -> 操作结果:
        """回到配置默认姿态。"""

        targets = {
            joint_key: float(self.joint_config_by_key[joint_key].get("默认角度", 0))
            for joint_key in self.joint_order
        }
        result = self.move_joints(targets)
        if result.成功:
            gripper_result = self.set_gripper(float(self.config.get("gripper", {}).get("默认开合", 50)))
            if not gripper_result.成功:
                return gripper_result
        return result

    def set_gripper(self, open_value: float) -> 操作结果:
        """设置夹爪开合，0 到 100。"""

        if not self.connected:
            return 操作结果(False, "尚未连接。请先输入：连接")

        if not self.config.get("transport", {}).get("gripper_available", True):
            return 操作结果(False, "配置中 gripper_available=false，夹爪不可用。")

        if not self.calibration_manager.has("gripper"):
            return 操作结果(False, "标定文件缺少夹爪 gripper，禁止移动夹爪。")

        try:
            value = float(open_value)
            if value < 0 or value > 100:
                return 操作结果(False, "夹爪开合值必须在 0 到 100 之间。")

            calibration_check = self.safety_checker.check_calibration_for_move()
            if not calibration_check.成功:
                return 操作结果(False, calibration_check.消息)

            entry = self.calibration_manager.get("gripper")
            goal_raw = gripper_open_value_to_raw(value, entry)
            raw_check = self.safety_checker.check_goal_raw("gripper", goal_raw, entry)
            if not raw_check.成功:
                return 操作结果(False, raw_check.消息)

            print(f"夹爪目标：{value:.1f}% -> raw={goal_raw}")
            self.driver.write_goal_position("gripper", goal_raw)
            self.current_raw["gripper"] = goal_raw
            self.current_gripper = value
            self.runtime_state["gripper"] = {
                "open_value": value,
                "goal_raw": goal_raw,
                "present_raw": goal_raw,
            }
            self._save_runtime_state()
            return 操作结果(True, f"夹爪已设置为 {value:.1f}%。")
        except Exception as 错误:
            return 操作结果(False, f"夹爪移动失败：{错误}")

    def stop(self) -> 操作结果:
        """急停 / 保持当前位置。"""

        if not self.connected:
            return 操作结果(False, "尚未连接，无需急停。")
        try:
            self.driver.stop()
            self.current_raw = self.driver.read_all_present_positions()
            self._refresh_state_from_raw(self.current_raw)
            self._save_runtime_state()
            return 操作结果(True, "已保持当前位置。")
        except Exception as 错误:
            return 操作结果(False, f"急停失败：{错误}")

    def apply_pose(self, pose: dict[str, Any]) -> 操作结果:
        """应用阶段三姿态格式。"""

        if "关节角度" not in pose:
            return 操作结果(False, "姿态缺少“关节角度”。")
        try:
            target_angles = [float(value) for value in pose["关节角度"]]
        except (TypeError, ValueError):
            return 操作结果(False, "姿态中的关节角度必须是数字。")
        if len(target_angles) != len(self.joint_order):
            return 操作结果(False, f"姿态关节数量不对，需要 {len(self.joint_order)} 个。")

        target = {joint_key: target_angles[index] for index, joint_key in enumerate(self.joint_order)}
        result = self.move_joints(target)
        if not result.成功:
            return result

        if "夹爪" in pose:
            return self.set_gripper(float(pose["夹爪"]))
        return result

    def calibration_report(self) -> dict[str, Any]:
        """返回标定状态报告。"""

        try:
            self.calibration_manager.reload()
        except Exception:
            pass
        return self.calibration_manager.calibration_report()

    # 阶段三动作播放器兼容接口
    def 获取当前状态(self) -> dict[str, Any]:
        """返回阶段三动作播放器需要的状态格式。"""

        self.get_state()
        return {
            "关节角度": [self.current_joint_deg.get(joint_key, 0.0) for joint_key in self.joint_order],
            "夹爪": self.current_gripper,
        }

    def 获取详细状态(self) -> dict[str, Any]:
        """返回接近阶段三模型的详细状态。"""

        state = self.get_state()
        return {
            "关节": [
                {
                    "编号": index + 1,
                    "名称": joint_label(joint_key),
                    "key": joint_key,
                    "角度": state.get("关节角度", {}).get(joint_key, 0.0),
                    "最小角度": float(self.joint_config_by_key[joint_key].get("最小角度", -180)),
                    "最大角度": float(self.joint_config_by_key[joint_key].get("最大角度", 180)),
                    "模式": self.joint_config_by_key[joint_key].get("模式", "单圈"),
                    "raw": state.get("raw_present_position", {}).get(joint_key),
                }
                for index, joint_key in enumerate(self.joint_order)
            ],
            "夹爪": self.current_gripper,
            "夹爪最小": 0,
            "夹爪最大": 100,
        }

    def 移动到关节角度(self, 目标角度: list[float]) -> 操作结果:
        """阶段三兼容：按固定顺序移动 J1-J5。"""

        if len(目标角度) != len(self.joint_order):
            return 操作结果(False, f"角度数量不对：需要 {len(self.joint_order)} 个。")
        target = {joint_key: float(目标角度[index]) for index, joint_key in enumerate(self.joint_order)}
        return self.move_joints(target)

    def 移动单个关节(self, 关节编号: int, 目标角度: float) -> 操作结果:
        """阶段三兼容：按 1-5 编号移动单个关节。"""

        if 关节编号 < 1 or 关节编号 > len(self.joint_order):
            return 操作结果(False, f"关节编号必须在 1 到 {len(self.joint_order)} 之间。")
        return self.move_joint(self.joint_order[关节编号 - 1], float(目标角度))

    def 设置夹爪(self, 开合值: float) -> 操作结果:
        """阶段三兼容：设置夹爪。"""

        return self.set_gripper(float(开合值))

    def 张开夹爪(self) -> 操作结果:
        """张开夹爪。"""

        return self.set_gripper(float(self.config.get("gripper", {}).get("张开值", 100)))

    def 闭合夹爪(self) -> 操作结果:
        """闭合夹爪。"""

        return self.set_gripper(float(self.config.get("gripper", {}).get("闭合值", 0)))

    def 回到默认姿态(self) -> 操作结果:
        """阶段三兼容：回家。"""

        return self.move_home()

    def 应用姿态(self, 姿态: dict[str, Any]) -> 操作结果:
        """阶段三兼容：应用姿态。"""

        return self.apply_pose(姿态)

    def _create_driver(self) -> BaseServoDriver:
        if self.is_dry_run():
            return MockServoDriver(self.config, self.calibration_manager.data)
        return RealServoDriver(self.config, self.calibration_manager.data)

    def _reload_config_and_calibration(self) -> None:
        """连接前重新读取配置和标定文件。

        connect() 只加载标定，不重新标定，不覆盖 home_present_raw / zero_present_raw。
        """

        self.config = 读取配置(self.config_path)
        self.joint_order = list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))
        self.joint_config_by_key = self._build_joint_config_by_key()
        calibration_path = self._resolve_path(self.config.get("calibration", {}).get("path", "标定文件.json"))
        self.calibration_manager = CalibrationManager(calibration_path, self.config)
        self.safety_checker = SafetyChecker(self.config, self.calibration_manager)
        self.driver = self._create_driver()

    def _build_calibrated_startup_raw(self) -> dict[str, int]:
        """按标定零点建立 runtime startup_raw。

        单圈使用 zero_present_raw，多圈使用 home_present_raw，夹爪使用 zero_present_raw 或 range_min。
        """

        startup_raw: dict[str, int] = {}
        for joint_key in self.joint_order:
            if not self.calibration_manager.has(joint_key):
                continue
            entry = self.calibration_manager.get(joint_key)
            if entry.get("模式") == "多圈":
                startup_raw[joint_key] = int(entry["home_present_raw"])
            else:
                startup_raw[joint_key] = int(entry["zero_present_raw"])
        if self.calibration_manager.has("gripper"):
            entry = self.calibration_manager.get("gripper")
            startup_raw["gripper"] = int(entry.get("zero_present_raw", entry.get("range_min", 0)))
        return startup_raw

    def _build_joint_config_by_key(self) -> dict[str, dict[str, Any]]:
        robot = self.config.get("robot", {})
        joint_scales = robot.get("joint_scales", robot.get("关节减速比_joint_scales", {}))
        by_key: dict[str, dict[str, Any]] = {}
        for joint in robot.get("joints", []):
            joint_key = joint.get("key")
            if not joint_key:
                continue
            item = dict(joint)
            item["joint_scale"] = float(joint_scales[joint_key])
            by_key[joint_key] = item
        for joint_key in self.joint_order:
            if joint_key not in by_key:
                by_key[joint_key] = {
                    "key": joint_key,
                    "中文名": joint_label(joint_key),
                    "模式": "多圈" if joint_key in MULTI_TURN_JOINTS else "单圈",
                    "最小角度": -180,
                    "最大角度": 180,
                    "默认角度": 0,
                    "joint_scale": float(joint_scales[joint_key]),
                }
        return by_key

    def _refresh_state_from_raw(self, raw_by_joint: dict[str, int]) -> None:
        details: dict[str, Any] = {}
        multi_turn_state: dict[str, Any] = {}

        for joint_key in self.joint_order:
            if joint_key not in raw_by_joint or not self.calibration_manager.has(joint_key):
                continue
            detail = present_raw_to_joint_detail(
                joint_key,
                raw_by_joint[joint_key],
                self.joint_config_by_key[joint_key],
                self.calibration_manager.get(joint_key),
                self.runtime_state,
            )
            details[joint_key] = detail
            self.current_joint_deg[joint_key] = float(detail["joint_deg"])
            if joint_key in MULTI_TURN_JOINTS:
                multi_turn_state[joint_key] = {
                    "show_name": joint_label(joint_key),
                    "home_present_raw": detail["reference_raw"],
                    "current_raw": detail["present_raw"],
                    "relative_raw": detail["relative_raw"],
                    "joint_deg": detail["joint_deg"],
                    "goal_raw": raw_by_joint.get(joint_key),
                }

        if "gripper" in raw_by_joint and self.calibration_manager.has("gripper"):
            gripper_entry = self.calibration_manager.get("gripper")
            self.current_gripper = gripper_raw_to_open_value(raw_by_joint["gripper"], gripper_entry)
            self.runtime_state["gripper"] = {
                "present_raw": int(raw_by_joint["gripper"]),
                "open_value": self.current_gripper,
                "range_min": gripper_entry.get("range_min"),
                "range_max": gripper_entry.get("range_max"),
            }

        self.runtime_state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.runtime_state["raw_present_position"] = {key: int(value) for key, value in raw_by_joint.items()}
        self.runtime_state["关节角度"] = {
            joint_key: self.current_joint_deg[joint_key]
            for joint_key in self.joint_order
        }
        self.runtime_state["mapping_details"] = details
        self.runtime_state["multi_turn_state"] = multi_turn_state

    def _print_goal_raw_plan(self, detail_by_joint: dict[str, dict[str, Any]]) -> None:
        title = "[DRY-RUN] 如果是真实模式，将写入以下 Goal_Position：" if self.is_dry_run() else "将写入以下 Goal_Position："
        print(title)
        for joint_key in self.joint_order:
            if joint_key not in detail_by_joint:
                continue
            detail = detail_by_joint[joint_key]
            print(
                f"  {detail['show_name']} ({joint_key}) "
                f"角度={detail['joint_deg']:.2f} deg "
                f"relative_raw={detail['relative_raw']} "
                f"goal_raw={detail['goal_raw']} "
                f"模式={detail['模式']} scale={detail['joint_scale']}"
            )

    def _load_runtime_state(self) -> dict[str, Any]:
        if not self.runtime_state_path.exists():
            return {
                "connected": False,
                "dry_run": self.is_dry_run(),
                "startup_present_raw": {},
                "raw_present_position": {},
                "关节角度": {},
                "goal_joint_targets_deg": {},
                "goal_raw_by_joint": {},
                "multi_turn_state": {},
                "gripper": {},
            }
        try:
            with self.runtime_state_path.open("r", encoding="utf-8") as 文件:
                data = json.load(文件)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        return {}

    def _save_runtime_state(self) -> None:
        self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.runtime_state_path.open("w", encoding="utf-8") as 文件:
            json.dump(self.runtime_state, 文件, ensure_ascii=False, indent=2)
            文件.write("\n")

    def _resolve_path(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return self.base_dir / path


def 读取配置(path: str | Path) -> dict[str, Any]:
    """读取 JSON 兼容 YAML。没有 PyYAML 时也能运行。"""

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as 错误:
            raise RuntimeError(
                "配置不是 JSON 兼容格式，并且当前环境没有安装 PyYAML。"
                "请把配置保持为 JSON 兼容 YAML，或执行：pip install pyyaml"
            ) from 错误
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("配置文件最外层必须是对象。")
    return data


def 写入_json(path: str | Path, data: Any) -> None:
    """写入支持中文的 JSON 文件。"""

    path = Path(path)
    with path.open("w", encoding="utf-8") as 文件:
        json.dump(data, 文件, ensure_ascii=False, indent=2)
        文件.write("\n")


真实机械臂控制器 = RealArmController
