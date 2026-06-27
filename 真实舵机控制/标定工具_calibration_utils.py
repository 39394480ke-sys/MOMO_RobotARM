"""标定脚本共用工具。

这些工具只服务于真实硬件标定和应用标定，不参与普通 dry-run 控制。
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from 真实路径工具_real_path_utils import PROJECT_ROOT, REAL_CONTROL_DIR, ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    GRIPPER_JOINT,
    SERVO_IDS,
    JOINT_ORDER as COMMON_JOINT_ORDER,
    MULTI_TURN_JOINTS as COMMON_MULTI_TURN_JOINTS,
    joint_label as common_joint_label,
)
from 通用_io import env_value, read_structured  # noqa: E402


JOINTS = list(COMMON_JOINT_ORDER)
MULTI_TURN_JOINTS = list(COMMON_MULTI_TURN_JOINTS)

SINGLE_TURN_CALIBRATION_JOINTS = [
    GRIPPER_JOINT,  # J16_夹爪
]

ARM_MOTOR_IDS = dict(SERVO_IDS)

DEFAULT_MOTOR_MODEL = "sts3215"
RAW_COUNTS_PER_REV = 4096
POSITION_MODE_VALUE = 0
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_DISABLED_LIMIT_RAW = 0
GRIPPER_MIDPOINT_HOMING_OFFSET = 2047


def joint_label(joint_name: str) -> str:
    """返回可读关节名。"""

    return common_joint_label(joint_name, compact=True)


def load_config(config_path: str | Path) -> dict[str, Any]:
    """读取真实配置。"""

    config = read_structured(config_path)
    env_paths = (PROJECT_ROOT / ".env", REAL_CONTROL_DIR / "环境变量.env", PROJECT_ROOT / "系统集成" / "环境变量.env")
    port = str(env_value("ARM_ROBOT_PORT", "", env_paths=env_paths) or "").strip()
    if port:
        config.setdefault("transport", {})["port"] = port
    backend = str(env_value("ARM_SERVO_BACKEND", "", env_paths=env_paths) or "").strip()
    if backend:
        config.setdefault("transport", {})["driver_backend"] = backend
    return config


def import_feetech_classes():
    """导入 LeRobot / Feetech 依赖，缺失时给中文提示。"""

    try:
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError as error:
        raise RuntimeError(
            "缺少 LeRobot 真实舵机依赖。开发板默认推荐轻量 SDK；"
            "只有 transport.driver_backend=lerobot 时才需要安装这些包。\n"
            "如确认要使用 LeRobot 后端，请执行：\n"
            "  mamba run -n momo_rebot python -m pip install lerobot feetech-servo-sdk pyserial pyyaml\n"
            "dry-run 主程序和轻量 SDK 标定不需要 LeRobot/Torch。"
        ) from error
    return Motor, MotorNormMode, FeetechMotorsBus


def create_feetech_bus(port: str, include_gripper: bool = True, backend: str = "sdk", baudrate: int = 1_000_000):
    """创建 FeetechMotorsBus。"""

    backend = str(backend or "sdk").strip().lower()
    if backend in {"sdk", "lightweight", "scservo", "feetech-sdk"}:
        from 轻量舵机驱动_lightweight_feetech_driver import LightweightFeetechBus

        joint_names = list(JOINTS)
        if include_gripper:
            joint_names.append(GRIPPER_JOINT)
        motor_ids = {joint_name: ARM_MOTOR_IDS[joint_name] for joint_name in joint_names}
        return LightweightFeetechBus(port, motor_ids, baudrate=int(baudrate))

    Motor, MotorNormMode, FeetechMotorsBus = import_feetech_classes()
    joint_names = list(JOINTS)
    if include_gripper:
        joint_names.append(GRIPPER_JOINT)
    motors = {
        joint_name: Motor(ARM_MOTOR_IDS[joint_name], DEFAULT_MOTOR_MODEL, MotorNormMode.DEGREES)
        for joint_name in joint_names
    }
    return FeetechMotorsBus(port=port, motors=motors)


def connect_feetech_bus(port: str, include_gripper: bool = True, backend: str = "sdk", baudrate: int = 1_000_000):
    """创建并连接 Feetech 总线，失败时补充硬件排查提示。"""

    bus = create_feetech_bus(port, include_gripper=include_gripper, backend=backend, baudrate=baudrate)
    try:
        bus.connect()
    except Exception as error:
        raise RuntimeError(build_feetech_connect_error(error, port, include_gripper)) from error
    return bus


def available_serial_ports() -> list[str]:
    """返回当前系统可见的常见串口设备。"""

    patterns = [
        "/dev/cu.usbmodem*",
        "/dev/tty.usbmodem*",
        "/dev/cu.usbserial*",
        "/dev/tty.usbserial*",
        "/dev/cu.wchusbserial*",
        "/dev/tty.wchusbserial*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
    ]
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    return sorted(set(ports))


def build_feetech_connect_error(error: Exception, port: str, include_gripper: bool = True) -> str:
    """把 LeRobot/Feetech 的连接错误转成更可操作的中文说明。"""

    message = str(error)
    expected_ids = [ARM_MOTOR_IDS[joint_name] for joint_name in JOINTS]
    if include_gripper:
        expected_ids.append(ARM_MOTOR_IDS[GRIPPER_JOINT])

    lines = [
        message,
        "",
        "软件侧诊断：",
        f"- 当前串口：{port}",
        f"- 本次期望舵机 ID：{expected_ids}",
    ]
    ports = available_serial_ports()
    if ports:
        lines.append(f"- 系统当前可见串口：{', '.join(ports)}")
    else:
        lines.append("- 系统当前没有发现常见 USB 串口设备。")

    if "Full found motor list" in message and "{}" in message:
        lines.extend(
            [
                "",
                "Feetech 总线没有收到任何舵机响应。请优先检查：",
                "1. 舵机外部电源是否已打开，USB 只给控制板供电通常不够。",
                "2. 舵机电源 GND 是否和控制板 GND 共地。",
                "3. Feetech 总线 DATA/V+/GND 线序是否接对，DATA 是否插在总线口。",
                "4. 是否选错串口；可用 诊断舵机总线_diagnose_bus.py 自动尝试可见 usbmodem/usbserial 端口。",
                "5. 舵机 ID 是否已按当前项目设置为 10-16；如果舵机 ID 没改好，当前配置会全部报 Missing。",
            ]
        )
    elif "Missing motor IDs" in message:
        lines.extend(
            [
                "",
                "只缺少部分舵机时，请检查缺失 ID 对应的舵机供电、线缆串接、ID 设置和接头接触。",
            ]
        )
    return "\n".join(lines)


def single_turn_calibration_joints(include_gripper: bool = True) -> list[str]:
    """返回需要单圈标定的关节。J14 已统一为多圈，只剩可选夹爪。"""

    if include_gripper:
        return list(SINGLE_TURN_CALIBRATION_JOINTS)
    return [joint_name for joint_name in SINGLE_TURN_CALIBRATION_JOINTS if joint_name != GRIPPER_JOINT]


def bus_read(bus: Any, register_name: str, joint_name: str) -> int:
    """兼容不同 LeRobot 版本读取 raw。"""

    try:
        return int(bus.read(register_name, joint_name, normalize=False))
    except TypeError:
        return int(bus.read(register_name, joint_name))


def bus_write(bus: Any, register_name: str, joint_name: str, value: int) -> None:
    """兼容不同 LeRobot 版本写入 raw。"""

    try:
        bus.write(register_name, joint_name, int(value), normalize=False)
    except TypeError:
        bus.write(register_name, joint_name, int(value))


def bus_sync_read_positions(bus: Any, joint_names: list[str]) -> dict[str, int]:
    """优先批量读取 Present_Position，失败则逐个读取。"""

    if hasattr(bus, "sync_read"):
        try:
            values = bus.sync_read("Present_Position", joint_names, normalize=False)
            return {joint_name: int(values[joint_name]) for joint_name in joint_names}
        except TypeError:
            try:
                values = bus.sync_read("Present_Position", joint_names)
                return {joint_name: int(values[joint_name]) for joint_name in joint_names}
            except Exception:
                pass
        except Exception:
            pass
    return {joint_name: bus_read(bus, "Present_Position", joint_name) for joint_name in joint_names}


def confirm_or_abort(prompt: str, expected_text: str) -> None:
    """要求用户输入固定确认文本。"""

    actual = input(f"{prompt}\n请输入：{expected_text}\n确认 > ").strip()
    if actual != expected_text:
        raise RuntimeError("确认文本不匹配，已取消。")


def has_complete_single_turn_calibration(calibration: dict[str, Any], include_gripper: bool = True) -> bool:
    """检查夹爪是否已有可复用单圈标定。"""

    required = {
        GRIPPER_JOINT: ["id", "zero_present_raw", "range_min", "range_max", "homing_offset"],
    }
    for joint_name in single_turn_calibration_joints(include_gripper):
        fields = required[joint_name]
        entry = calibration.get(joint_name)
        if not isinstance(entry, dict):
            return False
        for field in fields:
            if field not in entry:
                return False
    return True
