"""应用已有标定文件到真实舵机。

这个脚本不会重新标定：
- 不重新读取 home_present_raw
- 不重新计算 zero_present_raw
- 不重新记录 range_min/range_max
- 不修改标定文件
"""

from __future__ import annotations

import argparse
from typing import Any

from 真实路径工具_real_path_utils import real_config_path, resolve_real_path
from 标定工具_calibration_utils import (
    JOINTS,
    MULTI_TURN_DISABLED_LIMIT_RAW,
    MULTI_TURN_JOINTS,
    MULTI_TURN_PHASE_VALUE,
    POSITION_MODE_VALUE,
    bus_write,
    connect_feetech_bus,
    confirm_or_abort,
    joint_label,
    load_config,
    single_turn_calibration_joints,
)
from 通用_io import read_json_object  # noqa: E402


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    port = args.port or config.get("transport", {}).get("port")
    if not port:
        raise SystemExit("没有串口。请在真实配置.yaml 中设置 transport.port，或传入 --port。")

    calibration_path = resolve_real_path(args.calibration)
    calibration = read_json_object(calibration_path) if calibration_path.exists() else None
    if not isinstance(calibration, dict):
        raise SystemExit(f"标定文件不存在或格式错误：{calibration_path}")

    print("标定应用程序")
    print(f"串口：{port}")
    print(f"标定文件：{calibration_path}")
    print("该程序会把已有标定文件中的寄存器配置写入真实舵机。")
    print("它不会重新生成标定文件，也不会重新计算零点或限位。")

    if not args.yes:
        confirm_or_abort("确认继续应用已有标定。", "我确认应用标定")

    include_gripper = should_include_gripper(config, calibration)
    if not include_gripper:
        print("夹爪不可用或未标定：只会应用主臂 J10-J15 的寄存器配置。")

    bus = connect_feetech_bus(port, include_gripper=include_gripper)
    try:
        print("已连接 Feetech 舵机总线。")
        apply_calibration(bus, calibration, include_gripper=include_gripper)
        print("\n标定寄存器应用完成。")
    finally:
        try:
            bus.disable_torque()
        except Exception:
            pass
        try:
            bus.disconnect()
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把已有 标定文件.json 应用到真实舵机")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置文件路径")
    parser.add_argument("--port", default=None, help="串口，例如 /dev/tty.usbmodemXXXX")
    parser.add_argument("--calibration", default="标定文件.json", help="已有标定文件")
    parser.add_argument("--yes", action="store_true", help="跳过固定文本确认，适合自动化但不推荐真机首次使用")
    return parser.parse_args()


def should_include_gripper(config: dict[str, Any], calibration: dict[str, Any]) -> bool:
    """根据配置和标定文件判断是否操作夹爪。"""

    if not config.get("transport", {}).get("gripper_available", True):
        return False
    meta = calibration.get("_meta", {})
    if isinstance(meta, dict) and meta.get("gripper_available") is False:
        return False
    return isinstance(calibration.get("gripper"), dict)


def apply_calibration(bus: Any, calibration: dict[str, Any], include_gripper: bool = True) -> None:
    """按规则写入寄存器。"""

    for joint_name in single_turn_calibration_joints(include_gripper):
        entry = require_entry(calibration, joint_name)
        operating_mode = int(entry.get("operating_mode", POSITION_MODE_VALUE))
        homing_offset = int(entry.get("homing_offset", 0))
        range_min = int(entry["range_min"])
        range_max = int(entry["range_max"])

        bus_write(bus, "Operating_Mode", joint_name, operating_mode)
        bus_write(bus, "Homing_Offset", joint_name, homing_offset)
        bus_write(bus, "Min_Position_Limit", joint_name, range_min)
        bus_write(bus, "Max_Position_Limit", joint_name, range_max)
        print(
            f"  单圈 {joint_label(joint_name)} ({joint_name})："
            f"Operating_Mode={operating_mode}, Homing_Offset={homing_offset}, "
            f"Limit=[{range_min}, {range_max}]"
        )

    for joint_name in MULTI_TURN_JOINTS:
        require_entry(calibration, joint_name)
        bus_write(bus, "Operating_Mode", joint_name, POSITION_MODE_VALUE)
        bus_write(bus, "Homing_Offset", joint_name, 0)
        bus_write(bus, "Phase", joint_name, MULTI_TURN_PHASE_VALUE)
        bus_write(bus, "Min_Position_Limit", joint_name, MULTI_TURN_DISABLED_LIMIT_RAW)
        bus_write(bus, "Max_Position_Limit", joint_name, MULTI_TURN_DISABLED_LIMIT_RAW)
        print(
            f"  多圈 {joint_label(joint_name)} ({joint_name})："
            f"Operating_Mode=0, Homing_Offset=0, Phase=28, Limit=[0, 0]"
        )


def require_entry(calibration: dict[str, Any], joint_name: str) -> dict[str, Any]:
    """获取必需标定项。"""

    entry = calibration.get(joint_name)
    if not isinstance(entry, dict):
        raise RuntimeError(f"标定文件缺少 {joint_label(joint_name)} ({joint_name})。")
    return entry


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"应用标定失败：{error}") from error
