"""Feetech 舵机总线诊断工具。

只连接和读取，不写入任何寄存器或目标位置。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from 真实路径工具_real_path_utils import real_config_path, resolve_real_path
from 标定工具_calibration_utils import (
    ARM_MOTOR_IDS,
    JOINTS,
    available_serial_ports,
    bus_read,
    connect_feetech_bus,
    joint_label,
    load_config,
)
from 标定管理_calibration_manager import CalibrationManager


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    calibration_path = resolve_calibration_path(config, args.config)
    if calibration_path.exists():
        CalibrationManager(
            calibration_path,
            config,
            require_real_variant=True,
        )
    include_gripper = bool(config.get("transport", {}).get("gripper_available", True))
    if args.include_gripper:
        include_gripper = True
    if args.no_gripper:
        include_gripper = False

    ports = resolve_ports(args, config)
    print("Feetech 舵机总线诊断")
    print("说明：本工具只读取，不写入寄存器。")
    print(f"夹爪：{'参与诊断' if include_gripper else '不参与诊断'}")
    print(f"待测试串口：{', '.join(ports) if ports else '无'}")
    if not ports:
        raise SystemExit("没有可测试串口。请检查 USB 连接，或用 --port 指定。")

    any_success = False
    for port in ports:
        print(f"\n== 测试串口：{port} ==")
        if try_port(port, include_gripper):
            any_success = True

    if not any_success:
        raise SystemExit("\n诊断结论：所有串口都没有成功连接到期望的 Feetech 舵机。请按上面的提示检查电源、共地、线序、ID 和串口。")
    print("\n诊断结论：至少一个串口连接成功。请把成功的串口写入 真实配置.local.yaml 的 transport.port。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="诊断 Feetech 舵机总线连接")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置文件路径")
    parser.add_argument("--port", action="append", default=None, help="指定串口；可重复传入多个")
    parser.add_argument("--all-ports", action="store_true", help="测试系统当前可见的所有 usbmodem/usbserial 串口")
    parser.add_argument("--include-gripper", action="store_true", help="强制包含夹爪 ID16")
    parser.add_argument("--no-gripper", action="store_true", help="强制不包含夹爪 ID16")
    return parser.parse_args()


def resolve_ports(args: argparse.Namespace, config: dict[str, Any]) -> list[str]:
    ports: list[str] = []
    if args.port:
        ports.extend(str(port) for port in args.port)
    else:
        config_port = config.get("transport", {}).get("port")
        if config_port:
            ports.append(str(config_port))
    if args.all_ports:
        ports.extend(available_serial_ports())
    return sorted(dict.fromkeys(ports))


def resolve_calibration_path(config: dict[str, Any], config_path: str | Path) -> Path:
    value = config.get("calibration", {}).get("path", "标定/current.local.json")
    path = Path(str(value))
    if path.is_absolute():
        return path
    return resolve_real_path(config_path).parent / path


def try_port(port: str, include_gripper: bool) -> bool:
    bus = None
    try:
        bus = connect_feetech_bus(port, include_gripper=include_gripper)
        print("连接成功。")
        joint_names = list(JOINTS)
        if include_gripper:
            joint_names.append("gripper")
        health = read_joint_health(bus, joint_names)
        print("只读状态：")
        for joint_name in joint_names:
            item = health[joint_name]
            print(
                f"  {joint_label(joint_name)} ({joint_name}) ID={item['id']} "
                f"Present_Position={item['present_position_raw']} "
                f"Voltage={item['voltage_v']:.1f}V "
                f"Temperature={item['temperature_c']}C"
            )
        return True
    except Exception as error:
        print("连接失败：")
        print(error)
        return False
    finally:
        if bus is not None:
            try:
                bus.disconnect()
            except Exception:
                pass


def read_joint_health(bus: Any, joint_names: list[str]) -> dict[str, dict[str, int | float]]:
    """Read position, voltage, and temperature without writing any register."""

    health: dict[str, dict[str, int | float]] = {}
    for joint_name in joint_names:
        present_position_raw = bus_read(bus, "Present_Position", joint_name)
        voltage_raw = bus_read(bus, "Present_Voltage", joint_name)
        temperature_c = bus_read(bus, "Present_Temperature", joint_name)
        health[joint_name] = {
            "id": int(ARM_MOTOR_IDS[joint_name]),
            "present_position_raw": present_position_raw,
            "voltage_raw": voltage_raw,
            "voltage_v": float(voltage_raw) / 10.0,
            "temperature_c": temperature_c,
        }
    return health


if __name__ == "__main__":
    main()
