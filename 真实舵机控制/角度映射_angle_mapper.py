"""逻辑角度和真实舵机 raw 值之间的映射。

上层统一使用逻辑关节角度，单位是度。
底层 Feetech 舵机写入和读取的是 Present_Position / Goal_Position raw 值。

注意：
- shoulder_pan = J1_底座旋转，单圈
- shoulder_lift = J2_肩部抬升，多圈
- elbow_flex = J3_肘部弯曲，多圈
- wrist_flex = J4_腕部俯仰，单圈
- wrist_roll = J5_腕部旋转，多圈
"""

from __future__ import annotations

from typing import Any


RAW_COUNTS_PER_REV = 4096
RAW_DEGREES_PER_REV = 360.0
HALF_RAW_COUNTS_PER_REV = 2048
SINGLE_TURN_RAW_MIN = 0
SINGLE_TURN_RAW_MAX = 4095
MULTI_TURN_ABSOLUTE_RAW_LIMIT = 30719
POSITION_MODE_VALUE = 0
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_DISABLED_LIMIT_RAW = 0

JOINT_ORDER = [
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

SINGLE_TURN_JOINTS = [
    "shoulder_pan",  # J1_底座旋转
    "wrist_flex",    # J4_腕部俯仰
]

JOINT_LABELS = {
    "shoulder_pan": "J1_底座旋转",
    "shoulder_lift": "J2_肩部抬升",
    "elbow_flex": "J3_肘部弯曲",
    "wrist_flex": "J4_腕部俯仰",
    "wrist_roll": "J5_腕部旋转",
    "gripper": "夹爪_ID6",
}


def joint_label(joint_key: str) -> str:
    """返回带 J 编号的显示名。"""

    return JOINT_LABELS.get(joint_key, joint_key)


def wrap_single_turn_raw(raw: float | int) -> int:
    """单圈 raw 包裹到 0-4095。"""

    return int(round(raw)) % RAW_COUNTS_PER_REV


def signed_single_turn_delta(current_raw: float | int, startup_raw: float | int) -> int:
    """计算单圈当前位置相对参考 raw 的最短差值。

    返回范围约为 -2048 到 2048。
    """

    当前 = wrap_single_turn_raw(current_raw)
    参考 = wrap_single_turn_raw(startup_raw)
    差值 = (当前 - 参考 + HALF_RAW_COUNTS_PER_REV) % RAW_COUNTS_PER_REV
    return int(差值 - HALF_RAW_COUNTS_PER_REV)


def multi_turn_relative_raw(current_raw: float | int, startup_raw: float | int) -> int:
    """多圈关节直接使用 signed absolute raw 差值，不做 4096 包裹。"""

    return int(round(current_raw)) - int(round(startup_raw))


def joint_deg_to_relative_raw(
    joint_name: str,
    joint_deg: float,
    joint_scale: float,
    direction: int | float = 1,
) -> int:
    """逻辑关节角度 deg 转成相对 raw。

    公式基于舵机 raw 计数、标定零点和关节减速比：
        motor_deg = joint_deg * joint_scale
        relative_raw = motor_deg / 360.0 * 4096

    direction 是标定文件中的额外方向修正，默认 1。
    """

    if float(joint_scale) == 0:
        raise ValueError(f"{joint_label(joint_name)} 的 joint_scale 不能为 0。")

    motor_deg = float(joint_deg) * float(joint_scale) * float(direction)
    return int(round(motor_deg / RAW_DEGREES_PER_REV * RAW_COUNTS_PER_REV))


def relative_raw_to_joint_deg(
    joint_name: str,
    relative_raw: float | int,
    joint_scale: float,
    direction: int | float = 1,
) -> float:
    """相对 raw 转成逻辑关节角度 deg。"""

    if float(joint_scale) == 0:
        raise ValueError(f"{joint_label(joint_name)} 的 joint_scale 不能为 0。")
    if float(direction) == 0:
        raise ValueError(f"{joint_label(joint_name)} 的 direction 不能为 0。")

    motor_deg = float(relative_raw) * RAW_DEGREES_PER_REV / RAW_COUNTS_PER_REV
    return motor_deg / (float(joint_scale) * float(direction))


def single_turn_relative_to_goal_raw(startup_raw: float | int, relative_raw: float | int) -> int:
    """单圈目标 raw：参考 raw + 相对 raw，然后包裹到 0-4095。"""

    return wrap_single_turn_raw(float(startup_raw) + float(relative_raw))


def multi_turn_relative_to_goal_raw(startup_raw: float | int, relative_raw: float | int) -> int:
    """多圈目标 raw：参考 raw + 相对 raw，不做 4096 包裹。"""

    goal_raw = int(round(float(startup_raw) + float(relative_raw)))
    if abs(goal_raw) > MULTI_TURN_ABSOLUTE_RAW_LIMIT:
        raise ValueError(
            f"多圈目标 raw={goal_raw} 超出 signed absolute raw 安全范围 "
            f"[-{MULTI_TURN_ABSOLUTE_RAW_LIMIT}, {MULTI_TURN_ABSOLUTE_RAW_LIMIT}]。"
        )
    return goal_raw


def joint_deg_to_goal_raw(
    joint_key: str,
    joint_deg: float,
    joint_config: dict[str, Any],
    calibration_entry: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> int:
    """角度到目标 raw 的总入口。"""

    return joint_deg_to_goal_detail(
        joint_key,
        joint_deg,
        joint_config,
        calibration_entry,
        runtime_state,
    )["goal_raw"]


def present_raw_to_joint_deg(
    joint_key: str,
    present_raw: float | int,
    joint_config: dict[str, Any],
    calibration_entry: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> float:
    """present raw 到逻辑角度的总入口。"""

    return present_raw_to_joint_detail(
        joint_key,
        present_raw,
        joint_config,
        calibration_entry,
        runtime_state,
    )["joint_deg"]


def joint_deg_to_goal_detail(
    joint_key: str,
    joint_deg: float,
    joint_config: dict[str, Any],
    calibration_entry: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回角度到 raw 的完整计算过程，便于 dry-run 检查。"""

    runtime_state = runtime_state or {}
    模式 = 获取关节模式(joint_key, joint_config, calibration_entry)
    joint_scale = 获取关节比例(joint_key, joint_config)
    direction = 获取方向(calibration_entry)
    reference_raw = 获取参考raw(joint_key, 模式, calibration_entry, runtime_state)
    relative_raw = joint_deg_to_relative_raw(joint_key, joint_deg, joint_scale, direction)

    if 模式 == "单圈":
        goal_raw = single_turn_relative_to_goal_raw(reference_raw, relative_raw)
    elif 模式 == "多圈":
        goal_raw = multi_turn_relative_to_goal_raw(reference_raw, relative_raw)
    else:
        raise ValueError(f"{joint_label(joint_key)} 的模式不支持：{模式}")

    return {
        "joint_key": joint_key,
        "show_name": joint_label(joint_key),
        "模式": 模式,
        "joint_deg": float(joint_deg),
        "joint_scale": float(joint_scale),
        "direction": direction,
        "reference_raw": int(round(reference_raw)),
        "relative_raw": int(round(relative_raw)),
        "goal_raw": int(round(goal_raw)),
    }


def present_raw_to_joint_detail(
    joint_key: str,
    present_raw: float | int,
    joint_config: dict[str, Any],
    calibration_entry: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回 present raw 到逻辑角度的完整计算过程。"""

    runtime_state = runtime_state or {}
    模式 = 获取关节模式(joint_key, joint_config, calibration_entry)
    joint_scale = 获取关节比例(joint_key, joint_config)
    direction = 获取方向(calibration_entry)
    reference_raw = 获取参考raw(joint_key, 模式, calibration_entry, runtime_state)

    if 模式 == "单圈":
        relative_raw = signed_single_turn_delta(present_raw, reference_raw)
    elif 模式 == "多圈":
        relative_raw = multi_turn_relative_raw(present_raw, reference_raw)
    else:
        raise ValueError(f"{joint_label(joint_key)} 的模式不支持：{模式}")

    joint_deg = relative_raw_to_joint_deg(joint_key, relative_raw, joint_scale, direction)
    return {
        "joint_key": joint_key,
        "show_name": joint_label(joint_key),
        "模式": 模式,
        "joint_scale": float(joint_scale),
        "direction": direction,
        "reference_raw": int(round(reference_raw)),
        "present_raw": int(round(present_raw)),
        "relative_raw": int(round(relative_raw)),
        "joint_deg": float(joint_deg),
    }


def 获取关节模式(
    joint_key: str,
    joint_config: dict[str, Any],
    calibration_entry: dict[str, Any] | None = None,
) -> str:
    """从配置和标定中获取单圈/多圈模式。"""

    if calibration_entry and calibration_entry.get("模式"):
        return str(calibration_entry["模式"])
    if joint_config.get("模式"):
        return str(joint_config["模式"])
    if joint_key in MULTI_TURN_JOINTS:
        return "多圈"
    return "单圈"


def 获取关节比例(joint_key: str, joint_config: dict[str, Any]) -> float:
    """读取 joint_scale，必须包含每个关节的减速比和方向。"""

    if "joint_scale" in joint_config:
        return float(joint_config["joint_scale"])
    if "scale" in joint_config:
        return float(joint_config["scale"])
    raise KeyError(f"{joint_label(joint_key)} 缺少 joint_scale。")


def 获取方向(calibration_entry: dict[str, Any] | None) -> int:
    """读取标定方向。旧模板没有 direction 时默认 1。"""

    if not calibration_entry:
        return 1
    return int(calibration_entry.get("direction", 1))


def 获取参考raw(
    joint_key: str,
    模式: str,
    calibration_entry: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> int:
    """获取角度映射参考 raw。

    单圈优先使用 zero_present_raw，多圈优先使用 home_present_raw。
    runtime_state 只作为兜底，不能把启动姿态当成真实零点。
    """

    runtime_state = runtime_state or {}
    if 模式 == "单圈":
        if "zero_present_raw" in calibration_entry:
            return int(calibration_entry["zero_present_raw"])
    elif 模式 == "多圈":
        if "home_present_raw" in calibration_entry:
            return int(calibration_entry["home_present_raw"])

    startup = runtime_state.get("startup_present_raw", {})
    if joint_key in startup:
        return int(startup[joint_key])
    raise KeyError(f"{joint_label(joint_key)} 缺少映射参考 raw。")


def gripper_open_value_to_raw(open_value: float, calibration_entry: dict[str, Any]) -> int:
    """夹爪 0-100 开合值映射到 raw。

    0 对应 range_min，100 对应 range_max。
    """

    value = max(0.0, min(100.0, float(open_value)))
    range_min = int(calibration_entry["range_min"])
    range_max = int(calibration_entry["range_max"])
    return int(round(range_min + (range_max - range_min) * value / 100.0))


def gripper_raw_to_open_value(raw: float | int, calibration_entry: dict[str, Any]) -> float:
    """夹爪 raw 反算 0-100 开合值。"""

    range_min = int(calibration_entry["range_min"])
    range_max = int(calibration_entry["range_max"])
    if range_max == range_min:
        return 0.0
    return (float(raw) - range_min) * 100.0 / (range_max - range_min)
