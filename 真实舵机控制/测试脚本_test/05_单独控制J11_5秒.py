"""单独控制 J11 舵机多圈旋转。

适合只连接 J11 / ID 11，并且 J11 已经加了 1:5 行星减速器时做真机测试。
只改本脚本的 J11 控制逻辑，不依赖项目全局 J11 标定。
"""

from __future__ import annotations

import time

import 真实测试路径_test_paths  # noqa: F401
from 真实路径工具_real_path_utils import real_config_path
from 标定工具_calibration_utils import bus_read, bus_write, import_feetech_classes, load_config


# 配置文件路径：从这里读取串口 port，例如 /dev/cu.usbmodem...
CONFIG_PATH = real_config_path()

# 关节名和舵机 ID：J11 = 底盘/底座旋转 = 舵机 ID 11。
JOINT_KEY = "j11"
SERVO_ID = 11

# 是否在本脚本里临时把 J11 写成多圈位置模式。
# 第一次把 J11 从单圈改为多圈时必须为 True；后面保持 True 也可以。
APPLY_MULTI_TURN_REGISTERS = True

# 行星减速比。1:5 表示：电机转 5 圈，底盘输出端转 1 圈。
GEAR_RATIO = 5.0

# 你真正想让底盘输出端相对当前位置转多少度。
# 例：OUTPUT_DELTA_DEG=90 时，电机本体会转 90*5=450 度。
OUTPUT_DELTA_DEG = 90

# 方向。1 是当前方向，-1 是反方向。
DIRECTION = -1

# 运动持续时间，越小越快。高速测试建议先用 0.8，再慢慢减小。
DURATION_S = 5

# 分几步写入目标位置。越小越直接；越大越平滑。
# 高速测试可用 4~8；调试平滑运动可用 20~50。
STEPS = 300

# STS3215 一圈约 4096 个 raw 计数。
RAW_COUNTS_PER_REV = 4096

# 项目里多圈 signed absolute raw 的保守安全边界，约等于电机 +-7.5 圈。
MAX_ABS_GOAL_RAW = 30719

# STS3215 多圈位置模式需要的寄存器值，沿用项目里多圈关节的规则。
POSITION_MODE_VALUE = 0
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_DISABLED_LIMIT_RAW = 0


def main() -> None:
    config = load_config(CONFIG_PATH)
    port = str(config["transport"]["port"])
    motor_delta_deg = OUTPUT_DELTA_DEG * GEAR_RATIO * DIRECTION
    delta_raw = round(RAW_COUNTS_PER_REV * motor_delta_deg / 360.0)

    Motor, MotorNormMode, FeetechMotorsBus = import_feetech_classes()
    bus = FeetechMotorsBus(
        port=port,
        motors={JOINT_KEY: Motor(SERVO_ID, "sts3215", MotorNormMode.DEGREES)},
    )

    try:
        bus.connect()
        if APPLY_MULTI_TURN_REGISTERS:
            apply_j11_multi_turn_registers(bus)

        current_raw = bus_read(bus, "Present_Position", JOINT_KEY)
        target_raw = current_raw + delta_raw
        if abs(target_raw) > MAX_ABS_GOAL_RAW:
            print(
                f"目标 raw={target_raw} 超出安全边界 +- {MAX_ABS_GOAL_RAW}，已取消。"
                "请减小 OUTPUT_DELTA_DEG，或先反方向转回中间区域。"
            )
            return

        actual_motor_delta_deg = (target_raw - current_raw) * 360.0 / RAW_COUNTS_PER_REV
        actual_output_delta_deg = actual_motor_delta_deg / GEAR_RATIO
        print(f"已连接 J11(ID {SERVO_ID})：Present_Position={current_raw}")
        print(
            f"计划：{DURATION_S:.2f}s 内从 raw {current_raw} 写到 {target_raw}。"
            f"电机约 {actual_motor_delta_deg:+.1f}°，底盘输出约 {actual_output_delta_deg:+.1f}°。"
        )
        if target_raw == current_raw:
            print("目标位置等于当前位置，不会转动。请改 OUTPUT_DELTA_DEG 或 DIRECTION。")
            return

        enable_torque(bus)
        start = time.monotonic()
        for index in range(1, STEPS + 1):
            alpha = index / STEPS
            goal_raw = round(current_raw + (target_raw - current_raw) * alpha)
            bus_write(bus, "Goal_Position", JOINT_KEY, goal_raw)
            print(f"[{index:02d}/{STEPS}] Goal_Position={goal_raw}")
            sleep_until(start + DURATION_S * index / STEPS)

        final_raw = bus_read(bus, "Present_Position", JOINT_KEY)
        print(f"完成：J11 当前 Present_Position={final_raw}")
    finally:
        try:
            disable_torque(bus)
        finally:
            disconnect(bus)
            print("已断开 J11 总线连接。")


def apply_j11_multi_turn_registers(bus) -> None:
    """把 J11 临时按多圈位置关节配置。"""

    bus_write(bus, "Operating_Mode", JOINT_KEY, POSITION_MODE_VALUE)
    bus_write(bus, "Homing_Offset", JOINT_KEY, 0)
    bus_write(bus, "Phase", JOINT_KEY, MULTI_TURN_PHASE_VALUE)
    bus_write(bus, "Min_Position_Limit", JOINT_KEY, MULTI_TURN_DISABLED_LIMIT_RAW)
    bus_write(bus, "Max_Position_Limit", JOINT_KEY, MULTI_TURN_DISABLED_LIMIT_RAW)
    print("已写入 J11 多圈寄存器：Operating_Mode=0, Homing_Offset=0, Phase=28, Limit=0/0")


def enable_torque(bus) -> None:
    try:
        if hasattr(bus, "enable_torque"):
            bus.enable_torque(JOINT_KEY)
        else:
            bus_write(bus, "Torque_Enable", JOINT_KEY, 1)
    except Exception as error:
        print(f"开启扭矩提示：{error}")


def disable_torque(bus) -> None:
    try:
        if hasattr(bus, "disable_torque"):
            bus.disable_torque(JOINT_KEY)
        else:
            bus_write(bus, "Torque_Enable", JOINT_KEY, 0)
    except Exception as error:
        print(f"关闭扭矩提示：{error}")


def disconnect(bus) -> None:
    try:
        bus.disconnect(disable_torque=True)
    except TypeError:
        bus.disconnect()


def sleep_until(target_time: float) -> None:
    sleep_s = target_time - time.monotonic()
    if sleep_s > 0:
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
