"""按当前真实姿态的指定逻辑角度修正多圈关节标定。

示例：
  python 标定当前角度_calibrate_current_angle.py --port /dev/momo-servo --joint j12 --angle 30

本工具只读取 Present_Position 并修改标定文件，不写 Goal_Position，不移动舵机。
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import Any

from 真实路径工具_real_path_utils import real_config_path, resolve_real_path
from 标定工具_calibration_utils import MULTI_TURN_JOINTS, joint_label, load_config
from 轻量舵机驱动_lightweight_feetech_driver import LightweightFeetechBus, build_motor_ids
from 角度映射_angle_mapper import (
    RAW_COUNTS_PER_REV,
    joint_deg_to_relative_raw,
    present_raw_to_joint_detail,
    获取关节比例,
    获取方向,
)
from 通用_io import atomic_write_json, read_json_object_or_default, timestamped_json_path


def main() -> None:
    args = parse_args()
    joint = normalize_joint(args.joint)
    config = load_config(args.config)
    port = args.port or config.get("transport", {}).get("port")
    if not port:
        raise SystemExit("没有串口。请传入 --port，或设置真实配置 transport.port / ARM_ROBOT_PORT。")

    calibration_path = resolve_calibration_path(config, args.config)
    calibration = read_json_object_or_default(calibration_path)
    entry = calibration.get(joint)
    if not isinstance(entry, dict):
        raise SystemExit(f"{joint_label(joint)} 缺少标定项：{calibration_path}")
    joint_config = joint_config_for(config, joint)
    present_raw = read_present_raw(config, calibration, str(port), joint, int(args.baudrate or config.get("transport", {}).get("baudrate", 1_000_000)))
    old_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, entry)

    relative_raw = joint_deg_to_relative_raw(
        joint,
        float(args.angle),
        获取关节比例(joint, joint_config),
        获取方向(entry),
    )
    new_home_raw = int(round(int(present_raw) - int(relative_raw)))
    new_entry = dict(entry)
    new_entry["home_present_raw"] = new_home_raw
    new_entry["home_present_wrapped_raw"] = new_home_raw % RAW_COUNTS_PER_REV
    new_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, new_entry)

    print("当前角度标定修正")
    print(f"关节：{joint_label(joint)} ({joint})")
    print(f"串口：{port}")
    print(f"标定文件：{calibration_path}")
    print(f"当前 Present_Position：{present_raw}")
    print(f"旧换算角度：{old_detail['joint_deg']:.3f}")
    print(f"指定当前角度：{float(args.angle):.3f}")
    print(f"旧 home_present_raw：{entry.get('home_present_raw')}")
    print(f"新 home_present_raw：{new_home_raw}")

    if args.dry_run:
        print("dry-run：不写入标定文件。")
        return
    if not args.yes:
        answer = input("确认写入标定文件？输入 yes 继续：").strip()
        if answer != "yes":
            raise SystemExit("已取消。")

    backup_dir = calibration_path.parent / "标定备份_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = timestamped_json_path(backup_dir, f"{calibration_path.stem}_backup")
    if calibration_path.exists():
        shutil.copy2(calibration_path, backup_path)
    calibration[joint] = new_entry
    meta = dict(calibration.get("_meta", {})) if isinstance(calibration.get("_meta"), dict) else {}
    meta["updated_at_unix_s"] = time.time()
    meta["updated_by"] = Path(__file__).name
    meta["last_current_angle_update"] = {
        "joint_key": joint,
        "present_raw": int(present_raw),
        "assigned_angle_deg": float(args.angle),
        "old_home_present_raw": entry.get("home_present_raw"),
        "new_home_present_raw": new_home_raw,
    }
    calibration["_meta"] = meta
    atomic_write_json(calibration_path, calibration)
    print(f"已备份：{backup_path}")
    print(f"已写入：{calibration_path}")
    print(f"新换算角度：{new_detail['joint_deg']:.3f}")
    print("说明：本工具未写 Goal_Position，机械臂不会移动。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按当前真实姿态的指定逻辑角度修正多圈关节标定")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置文件路径")
    parser.add_argument("--port", default=None, help="串口，例如 /dev/momo-servo")
    parser.add_argument("--baudrate", type=int, default=None, help="串口波特率，默认读真实配置")
    parser.add_argument("--joint", default="j12", help="多圈关节，例如 j12")
    parser.add_argument("--angle", type=float, required=True, help="当前真实姿态应对应的逻辑角度")
    parser.add_argument("--dry-run", action="store_true", help="只打印计算结果，不写文件")
    parser.add_argument("--yes", action="store_true", help="不交互，直接写入")
    return parser.parse_args()


def normalize_joint(value: str) -> str:
    joint = str(value).strip().lower()
    aliases = {"j10": "j10", "j11": "j11", "j12": "j12", "j13": "j13", "j15": "j15"}
    joint = aliases.get(joint, joint)
    if joint not in MULTI_TURN_JOINTS:
        raise SystemExit(f"当前工具只支持多圈关节：{', '.join(MULTI_TURN_JOINTS)}")
    return joint


def resolve_calibration_path(config: dict[str, Any], config_path: str | Path) -> Path:
    value = config.get("calibration", {}).get("path", "标定文件.json")
    path = Path(str(value))
    if path.is_absolute():
        return path
    return resolve_real_path(config_path).parent / path


def joint_config_for(config: dict[str, Any], joint: str) -> dict[str, Any]:
    for item in config.get("robot", {}).get("joints", []):
        if item.get("key") == joint:
            result = dict(item)
            scales = config.get("robot", {}).get("joint_scales", {}) or config.get("robot", {}).get("关节减速比_joint_scales", {})
            if joint in scales:
                result["joint_scale"] = float(scales[joint])
            return result
    raise SystemExit(f"真实配置里找不到关节：{joint}")


def read_present_raw(config: dict[str, Any], calibration: dict[str, Any], port: str, joint: str, baudrate: int) -> int:
    motor_ids = build_motor_ids(config, calibration, [joint])
    bus = LightweightFeetechBus(port, motor_ids, baudrate=baudrate)
    try:
        found = bus.connect()
        motor_id = motor_ids[joint]
        if int(motor_id) not in {int(item) for item in found}:
            raise RuntimeError(f"{joint_label(joint)} ID {motor_id} 未响应。")
        return int(bus.read("Present_Position", joint))
    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
