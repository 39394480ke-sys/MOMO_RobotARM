"""轻量 Feetech SDK 总线诊断。

只执行 ping 和 Present_Position 读取，不写入 Goal_Position、Torque_Enable 或其他寄存器。
适合 ARM 开发板上绕开 lerobot/torch 依赖做真实舵机只读验证。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from 真实路径工具_real_path_utils import real_config_path, resolve_real_path
from 标定工具_calibration_utils import JOINTS, available_serial_ports, joint_label, load_config
from 轻量舵机驱动_lightweight_feetech_driver import EXPECTED_STS3215_MODEL, LightweightFeetechBus, build_motor_ids
from 通用_io import read_json_object_or_default


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    calibration = read_json_object_or_default(resolve_calibration_path(config, args.config))
    include_gripper = bool(config.get("transport", {}).get("gripper_available", True))
    if args.include_gripper:
        include_gripper = True
    if args.no_gripper:
        include_gripper = False

    joint_keys = list(JOINTS)
    if include_gripper and "gripper" in calibration:
        joint_keys.append("gripper")
    motor_ids_by_joint = build_motor_ids(config, calibration, joint_keys)
    ports = resolve_ports(args, config)
    baudrate = int(args.baudrate or config.get("transport", {}).get("baudrate", 1_000_000))

    print("轻量 Feetech SDK 总线诊断")
    print("说明：本工具只 ping 和读取 Present_Position，不写任何寄存器。")
    print(f"后端：scservo_sdk  baudrate={baudrate}")
    print(f"待测试串口：{', '.join(ports) if ports else '无'}")
    print(f"期望舵机：{motor_ids_by_joint}")
    if not ports:
        raise SystemExit("没有可测试串口。请检查 USB 连接，或用 --port 指定。")

    any_success = False
    for port in ports:
        print(f"\n== 测试串口：{port} ==")
        if try_port(port, motor_ids_by_joint, baudrate):
            any_success = True

    if not any_success:
        raise SystemExit("\n诊断结论：没有串口完整检测到期望的 Feetech 舵机。")
    print("\n诊断结论：至少一个串口完整检测到期望舵机，并完成只读位置读取。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="轻量 Feetech SDK 只读诊断")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置文件路径")
    parser.add_argument("--port", action="append", default=None, help="指定串口；可重复传入多个")
    parser.add_argument("--all-ports", action="store_true", help="测试当前可见的所有常见 USB 串口")
    parser.add_argument("--baudrate", type=int, default=None, help="串口波特率，默认读配置或 1000000")
    parser.add_argument("--include-gripper", action="store_true", help="强制包含已标定夹爪")
    parser.add_argument("--no-gripper", action="store_true", help="强制不包含夹爪")
    return parser.parse_args()


def resolve_calibration_path(config: dict[str, Any], config_path: str | Path) -> Path:
    value = config.get("calibration", {}).get("path", "标定文件.json")
    path = Path(str(value))
    if path.is_absolute():
        return path
    base = resolve_real_path(config_path).parent
    return base / path


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
        serial_by_id = Path("/dev/serial/by-id")
        if serial_by_id.exists():
            ports.extend(str(item) for item in sorted(serial_by_id.iterdir()))
    return sorted(dict.fromkeys(ports))


def try_port(port: str, motor_ids_by_joint: dict[str, int], baudrate: int) -> bool:
    bus = LightweightFeetechBus(port, motor_ids_by_joint, baudrate=baudrate)
    try:
        found = bus.connect()
        expected_ids = set(motor_ids_by_joint.values())
        found_ids = set(found)
        print(f"ping 结果：{found}")
        missing = sorted(expected_ids - found_ids)
        if missing:
            print(f"缺少舵机 ID：{missing}")
        wrong_model = {
            motor_id: model
            for motor_id, model in found.items()
            if motor_id in expected_ids and int(model) != EXPECTED_STS3215_MODEL
        }
        if wrong_model:
            print(f"型号异常：{wrong_model}，期望 STS3215 model={EXPECTED_STS3215_MODEL}")

        readable_joints = [
            joint_key
            for joint_key, motor_id in motor_ids_by_joint.items()
            if motor_id in found_ids and motor_id not in wrong_model
        ]
        if readable_joints:
            print("当前位置：")
            positions = bus.read_many("Present_Position", readable_joints)
            for joint_key in readable_joints:
                print(
                    f"  {joint_label(joint_key)} ({joint_key}, ID {motor_ids_by_joint[joint_key]}) "
                    f"Present_Position={positions.get(joint_key)}"
                )
        return not missing and not wrong_model
    except Exception as error:
        print("连接或读取失败：")
        print(error)
        return False
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
