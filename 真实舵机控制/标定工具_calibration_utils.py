"""标定脚本共用工具。

这些工具只服务于真实硬件标定和应用标定，不参与普通 dry-run 控制。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


JOINTS = [
    "shoulder_pan",   # J1_底座旋转
    "shoulder_lift",  # J2_肩部抬升
    "elbow_flex",     # J3_肘部弯曲
    "wrist_flex",     # J4_腕部俯仰
    "wrist_roll",     # J5_腕部旋转
]

MULTI_TURN_JOINTS = [
    "shoulder_lift",  # J2_肩部抬升
    "elbow_flex",     # J3_肘部弯曲
    "wrist_roll",     # J5_腕部旋转
]

SINGLE_TURN_CALIBRATION_JOINTS = [
    "shoulder_pan",  # J1_底座旋转
    "wrist_flex",    # J4_腕部俯仰
    "gripper",       # 夹爪_ID6
]

ARM_MOTOR_IDS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

JOINT_LABELS = {
    "shoulder_pan": "J1_底座旋转",
    "shoulder_lift": "J2_肩部抬升",
    "elbow_flex": "J3_肘部弯曲",
    "wrist_flex": "J4_腕部俯仰",
    "wrist_roll": "J5_腕部旋转",
    "gripper": "夹爪_ID6",
}

DEFAULT_MOTOR_MODEL = "sts3215"
RAW_COUNTS_PER_REV = 4096
POSITION_MODE_VALUE = 0
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_DISABLED_LIMIT_RAW = 0
GRIPPER_MIDPOINT_HOMING_OFFSET = 2047


def joint_label(joint_name: str) -> str:
    """返回可读关节名。"""

    return JOINT_LABELS.get(joint_name, joint_name)


def load_json(path: str | Path, default: Any = None) -> Any:
    """读取 JSON 文件。"""

    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: str | Path, payload: Any) -> None:
    """保存中文 JSON。"""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def load_config(config_path: str | Path) -> dict[str, Any]:
    """读取真实配置。"""

    text = Path(config_path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as error:
            raise RuntimeError("读取 YAML 配置需要安装 pyyaml。请在 arm_rebot 环境内运行脚本。") from error
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("配置文件最外层必须是对象。")
    return data


def import_feetech_classes():
    """导入 LeRobot / Feetech 依赖，缺失时给中文提示。"""

    try:
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError as error:
        raise RuntimeError(
            "缺少真实舵机依赖。请先执行：\n"
            "  mamba activate arm_rebot\n"
            "  python -m pip install lerobot feetech-servo-sdk pyserial pyyaml\n"
            "dry-run 主程序不需要这些依赖，但标定程序和真实控制需要。"
        ) from error
    return Motor, MotorNormMode, FeetechMotorsBus


def create_feetech_bus(port: str, include_gripper: bool = True):
    """创建 FeetechMotorsBus。"""

    Motor, MotorNormMode, FeetechMotorsBus = import_feetech_classes()
    joint_names = list(JOINTS)
    if include_gripper:
        joint_names.append("gripper")
    motors = {
        joint_name: Motor(ARM_MOTOR_IDS[joint_name], DEFAULT_MOTOR_MODEL, MotorNormMode.DEGREES)
        for joint_name in joint_names
    }
    return FeetechMotorsBus(port=port, motors=motors)


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


def has_complete_single_turn_calibration(calibration: dict[str, Any]) -> bool:
    """检查 J1/J4/夹爪 是否已有可复用单圈标定。"""

    required = {
        "shoulder_pan": ["id", "zero_present_raw", "range_min", "range_max", "homing_offset"],
        "wrist_flex": ["id", "zero_present_raw", "range_min", "range_max", "homing_offset"],
        "gripper": ["id", "zero_present_raw", "range_min", "range_max", "homing_offset"],
    }
    for joint_name, fields in required.items():
        entry = calibration.get(joint_name)
        if not isinstance(entry, dict):
            return False
        for field in fields:
            if field not in entry:
                return False
    return True
