"""舵机驱动层。

这个文件只负责和舵机总线通信：
- 读取 Present_Position raw
- 写入 Goal_Position raw
- 读写寄存器
- 开关扭矩

它不负责角度换算、标定策略、姿态管理或动作播放。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from 标定工具_calibration_utils import ARM_MOTOR_IDS, build_feetech_connect_error
from 角度映射_angle_mapper import JOINT_ORDER, joint_label


class BaseServoDriver(ABC):
    """舵机驱动统一接口。"""

    @abstractmethod
    def connect(self) -> None:
        """连接舵机总线。"""

    @abstractmethod
    def disconnect(self, disable_torque: bool = True) -> None:
        """断开舵机总线。"""

    @abstractmethod
    def read_present_position(self, joint_key: str) -> int:
        """读取单个关节 Present_Position raw。"""

    @abstractmethod
    def read_all_present_positions(self) -> dict[str, int]:
        """读取全部关节 Present_Position raw。"""

    @abstractmethod
    def write_goal_position(self, joint_key: str, goal_raw: int) -> None:
        """写入单个关节 Goal_Position raw。"""

    @abstractmethod
    def write_many_goal_positions(self, goal_raw_by_joint: dict[str, int]) -> None:
        """批量写入 Goal_Position raw。"""

    @abstractmethod
    def read_register(self, register_name: str, joint_key: str) -> int:
        """读取寄存器。"""

    @abstractmethod
    def write_register(self, register_name: str, joint_key: str, raw_value: int) -> None:
        """写入寄存器。"""

    @abstractmethod
    def enable_torque(self, joint_key: str | None = None) -> None:
        """开启扭矩。"""

    @abstractmethod
    def disable_torque(self, joint_key: str | None = None) -> None:
        """关闭扭矩。"""

    @abstractmethod
    def stop(self) -> None:
        """保持当前位置。"""


class 仿真_MockServoDriver(BaseServoDriver):
    """dry-run 和无硬件测试用驱动。

    不连接真实硬件，所有 raw 值存在内存中。写入时打印将要写入的 raw。
    """

    def __init__(self, config: dict[str, Any], calibration_data: dict[str, Any]):
        self.config = config
        self.calibration_data = calibration_data
        self.connected = False
        self.present_raw: dict[str, int] = {}
        self.registers: dict[str, dict[str, int]] = {}
        self.joint_keys = self._build_joint_keys()
        self._init_raw_from_calibration()

    def connect(self) -> None:
        self.connected = True
        print("[DRY-RUN] Mock 舵机驱动已连接，不会访问真实硬件。")

    def disconnect(self, disable_torque: bool = True) -> None:
        if disable_torque:
            self.disable_torque()
        self.connected = False
        print("[DRY-RUN] Mock 舵机驱动已断开。")

    def read_present_position(self, joint_key: str) -> int:
        self._ensure_known_joint(joint_key)
        return int(self.present_raw[joint_key])

    def read_all_present_positions(self) -> dict[str, int]:
        return {joint_key: int(self.present_raw[joint_key]) for joint_key in self.joint_keys}

    def write_goal_position(self, joint_key: str, goal_raw: int) -> None:
        self._ensure_known_joint(joint_key)
        print(f"[DRY-RUN] 写入 Goal_Position: joint={joint_key} ({joint_label(joint_key)}) raw={int(goal_raw)}")
        self.present_raw[joint_key] = int(goal_raw)
        self.registers.setdefault(joint_key, {})["Goal_Position"] = int(goal_raw)

    def write_many_goal_positions(self, goal_raw_by_joint: dict[str, int]) -> None:
        for joint_key, goal_raw in goal_raw_by_joint.items():
            self.write_goal_position(joint_key, int(goal_raw))

    def read_register(self, register_name: str, joint_key: str) -> int:
        self._ensure_known_joint(joint_key)
        if register_name == "Present_Position":
            return self.read_present_position(joint_key)
        return int(self.registers.setdefault(joint_key, {}).get(register_name, 0))

    def write_register(self, register_name: str, joint_key: str, raw_value: int) -> None:
        self._ensure_known_joint(joint_key)
        print(
            f"[DRY-RUN] 写入寄存器: joint={joint_key} ({joint_label(joint_key)}) "
            f"register={register_name} raw={int(raw_value)}"
        )
        self.registers.setdefault(joint_key, {})[register_name] = int(raw_value)
        if register_name in {"Goal_Position", "Present_Position"}:
            self.present_raw[joint_key] = int(raw_value)

    def enable_torque(self, joint_key: str | None = None) -> None:
        targets = [joint_key] if joint_key else self.joint_keys
        for key in targets:
            self._ensure_known_joint(key)
            self.registers.setdefault(key, {})["Torque_Enable"] = 1
        print("[DRY-RUN] 已模拟开启扭矩。")

    def disable_torque(self, joint_key: str | None = None) -> None:
        targets = [joint_key] if joint_key else self.joint_keys
        for key in targets:
            self._ensure_known_joint(key)
            self.registers.setdefault(key, {})["Torque_Enable"] = 0
        print("[DRY-RUN] 已模拟关闭扭矩。")

    def stop(self) -> None:
        current = self.read_all_present_positions()
        self.write_many_goal_positions(current)
        print("[DRY-RUN] 已保持当前位置。")

    def _build_joint_keys(self) -> list[str]:
        joint_keys = list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))
        if self.config.get("transport", {}).get("gripper_available", True) and "gripper" in self.calibration_data:
            joint_keys.append("gripper")
        return joint_keys

    def _init_raw_from_calibration(self) -> None:
        for joint_key in self.joint_keys:
            entry = self.calibration_data.get(joint_key, {})
            if joint_key == "gripper":
                raw = entry.get("zero_present_raw", entry.get("range_min", 0))
            elif entry.get("模式") == "多圈":
                raw = entry.get("home_present_raw", 0)
            else:
                raw = entry.get("zero_present_raw", 2048)
            self.present_raw[joint_key] = int(raw)
            self.registers[joint_key] = {
                "Present_Position": int(raw),
                "Goal_Position": int(raw),
                "Torque_Enable": 0,
            }

    def _ensure_known_joint(self, joint_key: str | None) -> None:
        if joint_key is None:
            return
        if joint_key not in self.present_raw:
            raise KeyError(f"未知舵机：{joint_key}")


class 真实_FeetechServoDriver(BaseServoDriver):
    """真实 Feetech STS3215 舵机驱动。

    依赖：
        pip install lerobot feetech-servo-sdk

    真实 raw 读写必须使用 normalize=False，避免 LeRobot 把数据转成归一化或角度。
    """

    def __init__(self, config: dict[str, Any], calibration_data: dict[str, Any]):
        self.config = config
        self.calibration_data = calibration_data
        self.port = str(config.get("transport", {}).get("port", ""))
        self.bus = None
        self.motors: dict[str, Any] = {}
        self.joint_keys = self._build_joint_keys()
        self.gripper_available = "gripper" in self.joint_keys
        self.gripper_detection_message = "夹爪参与连接。" if self.gripper_available else "夹爪未配置或未标定。"

    def connect(self) -> None:
        Motor, MotorNormMode, FeetechMotorsBus = self._import_lerobot()
        try:
            self._connect_with_joint_keys(self.joint_keys, Motor, MotorNormMode, FeetechMotorsBus)
        except Exception as error:
            if "gripper" in self.joint_keys and self._looks_like_only_gripper_missing(error):
                self._disconnect_after_failed_connect()
                arm_joint_keys = [joint_key for joint_key in self.joint_keys if joint_key != "gripper"]
                try:
                    self._connect_with_joint_keys(arm_joint_keys, Motor, MotorNormMode, FeetechMotorsBus)
                except Exception as arm_error:
                    raise RuntimeError(
                        build_feetech_connect_error(
                            arm_error,
                            self.port,
                            include_gripper=False,
                        )
                    ) from arm_error
                self.joint_keys = arm_joint_keys
                self.gripper_available = False
                self.gripper_detection_message = "未检测到 J16 夹爪，已自动切换为无夹爪模式。"
                print(self.gripper_detection_message)
                print(f"真实 Feetech 舵机总线已连接：{self.port}")
                return
            raise RuntimeError(
                build_feetech_connect_error(
                    error,
                    self.port,
                    include_gripper=self.config.get("transport", {}).get("gripper_available", True),
                )
            ) from error
        self.gripper_available = "gripper" in self.joint_keys
        self.gripper_detection_message = "已检测到 J16 夹爪。" if self.gripper_available else "夹爪未参与连接。"
        print(f"真实 Feetech 舵机总线已连接：{self.port}")

    def disconnect(self, disable_torque: bool = True) -> None:
        if self.bus is not None:
            try:
                self.bus.disconnect(disable_torque=disable_torque)
            except TypeError:
                if disable_torque:
                    self.disable_torque()
                self.bus.disconnect()
        self.bus = None
        print("真实 Feetech 舵机总线已断开。")

    def read_present_position(self, joint_key: str) -> int:
        self._ensure_connected()
        self._ensure_known_joint(joint_key)
        return int(self._bus_read("Present_Position", joint_key))

    def read_all_present_positions(self) -> dict[str, int]:
        self._ensure_connected()
        try:
            values = self._bus_sync_read("Present_Position", self.joint_keys)
            return {joint_key: int(values[joint_key]) for joint_key in self.joint_keys if joint_key in values}
        except Exception:
            return {joint_key: self.read_present_position(joint_key) for joint_key in self.joint_keys}

    def write_goal_position(self, joint_key: str, goal_raw: int) -> None:
        self._ensure_connected()
        self._ensure_known_joint(joint_key)
        self._bus_write("Goal_Position", joint_key, int(goal_raw))

    def write_many_goal_positions(self, goal_raw_by_joint: dict[str, int]) -> None:
        self._ensure_connected()
        values = {joint_key: int(goal_raw) for joint_key, goal_raw in goal_raw_by_joint.items()}
        try:
            self._bus_sync_write("Goal_Position", values)
        except Exception:
            for joint_key, goal_raw in values.items():
                self.write_goal_position(joint_key, goal_raw)

    def read_register(self, register_name: str, joint_key: str) -> int:
        self._ensure_connected()
        self._ensure_known_joint(joint_key)
        return int(self._bus_read(register_name, joint_key))

    def write_register(self, register_name: str, joint_key: str, raw_value: int) -> None:
        self._ensure_connected()
        self._ensure_known_joint(joint_key)
        self._bus_write(register_name, joint_key, int(raw_value))

    def enable_torque(self, joint_key: str | None = None) -> None:
        self._ensure_connected()
        if hasattr(self.bus, "enable_torque"):
            self.bus.enable_torque(joint_key)
            return
        targets = [joint_key] if joint_key else self.joint_keys
        for key in targets:
            self._bus_write("Torque_Enable", key, 1)

    def disable_torque(self, joint_key: str | None = None) -> None:
        self._ensure_connected()
        if hasattr(self.bus, "disable_torque"):
            self.bus.disable_torque(joint_key)
            return
        targets = [joint_key] if joint_key else self.joint_keys
        for key in targets:
            self._bus_write("Torque_Enable", key, 0)

    def stop(self) -> None:
        current = self.read_all_present_positions()
        self.write_many_goal_positions(current)
        print("已把当前位置写回 Goal_Position，机械臂保持当前位置。")

    def _build_joint_keys(self) -> list[str]:
        joint_keys = list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))
        if self.config.get("transport", {}).get("gripper_available", True) and "gripper" in self.calibration_data:
            joint_keys.append("gripper")
        return joint_keys

    def _config_motor_id(self, joint_key: str) -> int:
        if joint_key == "gripper":
            return ARM_MOTOR_IDS["gripper"]
        for joint in self.config.get("robot", {}).get("joints", []):
            if joint.get("key") == joint_key:
                return int(joint.get("舵机ID", 0))
        raise KeyError(f"配置中找不到 {joint_label(joint_key)} 的舵机 ID。")

    def _connect_with_joint_keys(self, joint_keys: list[str], Motor: Any, MotorNormMode: Any, FeetechMotorsBus: Any) -> None:
        self.motors = {}
        for joint_key in joint_keys:
            entry = self.calibration_data.get(joint_key, {})
            motor_id = int(entry.get("id", self._config_motor_id(joint_key)))
            self.motors[joint_key] = Motor(motor_id, "sts3215", MotorNormMode.DEGREES)
        self.bus = FeetechMotorsBus(port=self.port, motors=self.motors)
        self.bus.connect()

    def _disconnect_after_failed_connect(self) -> None:
        if self.bus is None:
            return
        try:
            self.bus.disconnect(disable_torque=False)
        except TypeError:
            try:
                self.bus.disconnect()
            except Exception:
                pass
        except Exception:
            pass
        self.bus = None

    @staticmethod
    def _looks_like_only_gripper_missing(error: Exception) -> bool:
        message = str(error)
        match = re.search(r"Missing motor IDs[^0-9]*(?P<ids>[\[\]\d,\s]+)", message)
        if not match:
            return False
        missing_ids = {int(item) for item in re.findall(r"\d+", match.group("ids"))}
        return missing_ids == {16}

    def _ensure_connected(self) -> None:
        if self.bus is None:
            raise RuntimeError("真实舵机驱动尚未连接。")

    def _ensure_known_joint(self, joint_key: str) -> None:
        if joint_key not in self.joint_keys:
            raise KeyError(f"未知舵机：{joint_key}")

    def _bus_read(self, register_name: str, joint_key: str):
        """兼容 LeRobot 不同版本的 raw 读取参数。"""

        try:
            return self.bus.read(register_name, joint_key, normalize=False)
        except TypeError:
            try:
                return self.bus.read(register_name, joint_key)
            except TypeError:
                return self.bus.read(register_name, [joint_key])[joint_key]

    def _bus_write(self, register_name: str, joint_key: str, raw_value: int) -> None:
        """兼容 LeRobot 不同版本的 raw 写入参数。"""

        try:
            self.bus.write(register_name, joint_key, int(raw_value), normalize=False)
            return
        except TypeError:
            pass
        try:
            self.bus.write(register_name, joint_key, int(raw_value))
            return
        except TypeError:
            self.bus.write(register_name, {joint_key: int(raw_value)})

    def _bus_sync_read(self, register_name: str, joint_keys: list[str]):
        """兼容批量 raw 读取。"""

        if hasattr(self.bus, "sync_read"):
            try:
                return self.bus.sync_read(register_name, joint_keys, normalize=False)
            except TypeError:
                return self.bus.sync_read(register_name, joint_keys)
        return {joint_key: self._bus_read(register_name, joint_key) for joint_key in joint_keys}

    def _bus_sync_write(self, register_name: str, values: dict[str, int]) -> None:
        """兼容批量 raw 写入。"""

        if hasattr(self.bus, "sync_write"):
            try:
                self.bus.sync_write(register_name, values, normalize=False)
                return
            except TypeError:
                self.bus.sync_write(register_name, values)
                return
        for joint_key, value in values.items():
            self._bus_write(register_name, joint_key, value)

    @staticmethod
    def _import_lerobot():
        try:
            from lerobot.motors import Motor, MotorNormMode
            from lerobot.motors.feetech import FeetechMotorsBus
        except ImportError as 错误:
            raise RuntimeError(
                "真实模式需要安装 lerobot 和 feetech-servo-sdk。"
                "请先执行：pip install lerobot feetech-servo-sdk"
            ) from 错误
        return Motor, MotorNormMode, FeetechMotorsBus


MockServoDriver = 仿真_MockServoDriver
RealServoDriver = 真实_FeetechServoDriver
