"""按当前真实姿态的指定逻辑角度修正多圈关节标定。

单关节示例：
  python 标定当前角度_calibrate_current_angle.py --port /dev/momo-servo --joint j12 --angle 30

批量示例：
  python 标定当前角度_calibrate_current_angle.py --port /dev/momo-servo \
    --joint-angle j12=30 --joint-angle j13=-15 --joint-angle j15=0

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
    config = load_config(args.config)
    port = args.port or config.get("transport", {}).get("port")
    if not port:
        raise SystemExit("没有串口。请传入 --port，或设置真实配置 transport.port / ARM_ROBOT_PORT。")

    calibration_path = resolve_calibration_path(config, args.config)
    calibration = read_json_object_or_default(calibration_path)
    assignments = parse_angle_assignments(args)
    baudrate = int(args.baudrate or config.get("transport", {}).get("baudrate", 1_000_000))
    present_raw_by_joint = read_present_raws(config, calibration, str(port), list(assignments), baudrate)
    updates = build_updates(config, calibration, assignments, present_raw_by_joint)

    print("当前角度标定修正")
    print(f"串口：{port}")
    print(f"标定文件：{calibration_path}")
    for item in updates:
        print("")
        print(f"关节：{joint_label(item['joint'])} ({item['joint']})")
        print(f"当前 Present_Position：{item['present_raw']}")
        print(f"旧换算角度：{item['old_detail']['joint_deg']:.3f}")
        print(f"指定当前角度：{item['assigned_angle_deg']:.3f}")
        print(f"旧 home_present_raw：{item['old_home_present_raw']}")
        print(f"新 home_present_raw：{item['new_home_present_raw']}")

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
    for item in updates:
        calibration[item["joint"]] = item["new_entry"]
    meta = dict(calibration.get("_meta", {})) if isinstance(calibration.get("_meta"), dict) else {}
    meta["updated_at_unix_s"] = time.time()
    meta["updated_by"] = Path(__file__).name
    meta["last_current_angle_update"] = [
        {
            "joint_key": item["joint"],
            "present_raw": int(item["present_raw"]),
            "assigned_angle_deg": float(item["assigned_angle_deg"]),
            "old_home_present_raw": item["old_home_present_raw"],
            "new_home_present_raw": item["new_home_present_raw"],
        }
        for item in updates
    ]
    calibration["_meta"] = meta
    atomic_write_json(calibration_path, calibration)
    print(f"已备份：{backup_path}")
    print(f"已写入：{calibration_path}")
    for item in updates:
        print(f"{joint_label(item['joint'])} 新换算角度：{item['new_detail']['joint_deg']:.3f}")
    print("说明：本工具未写 Goal_Position，机械臂不会移动。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按当前真实姿态的指定逻辑角度修正一个或多个多圈关节标定")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置文件路径")
    parser.add_argument("--port", default=None, help="串口，例如 /dev/momo-servo")
    parser.add_argument("--baudrate", type=int, default=None, help="串口波特率，默认读真实配置")
    parser.add_argument("--joint", default=None, help="单关节兼容参数，例如 j12；未传 --joint-angle 时默认 j12")
    parser.add_argument("--angle", type=float, default=None, help="单关节兼容参数：当前真实姿态应对应的逻辑角度")
    parser.add_argument(
        "--joint-angle",
        action="append",
        default=[],
        metavar="JOINT=DEG",
        help="批量标定参数，可重复，例如 --joint-angle j12=30 --joint-angle j13=-15",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计算结果，不写文件")
    parser.add_argument("--yes", action="store_true", help="不交互，直接写入")
    return parser.parse_args()


def parse_angle_assignments(args: argparse.Namespace) -> dict[str, float]:
    assignments: dict[str, float] = {}
    for raw_item in args.joint_angle:
        if "=" not in raw_item:
            raise SystemExit(f"--joint-angle 格式错误：{raw_item}，应为 j12=30")
        raw_joint, raw_angle = raw_item.split("=", 1)
        joint = normalize_joint(raw_joint)
        try:
            assignments[joint] = float(raw_angle)
        except ValueError as exc:
            raise SystemExit(f"--joint-angle 角度不是数字：{raw_item}") from exc

    if assignments:
        if args.angle is not None or args.joint is not None:
            raise SystemExit("请不要混用 --joint-angle 和 --joint/--angle。")
        return assignments

    if args.angle is None:
        raise SystemExit("请传入 --angle，或使用一个/多个 --joint-angle j12=30。")
    return {normalize_joint(args.joint or "j12"): float(args.angle)}


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


def read_present_raws(config: dict[str, Any], calibration: dict[str, Any], port: str, joints: list[str], baudrate: int) -> dict[str, int]:
    motor_ids = build_motor_ids(config, calibration, joints)
    bus = LightweightFeetechBus(port, motor_ids, baudrate=baudrate)
    try:
        found = bus.connect()
        found_ids = {int(item) for item in found}
        missing = [f"{joint_label(joint)} ID {motor_ids[joint]}" for joint in joints if int(motor_ids[joint]) not in found_ids]
        if missing:
            raise RuntimeError("以下舵机未响应：" + "；".join(missing))
        return {joint: int(value) for joint, value in bus.read_many("Present_Position", joints).items()}
    finally:
        bus.disconnect()


def build_updates(
    config: dict[str, Any],
    calibration: dict[str, Any],
    assignments: dict[str, float],
    present_raw_by_joint: dict[str, int],
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for joint, assigned_angle in assignments.items():
        entry = calibration.get(joint)
        if not isinstance(entry, dict):
            raise SystemExit(f"{joint_label(joint)} 缺少标定项。")
        joint_config = joint_config_for(config, joint)
        present_raw = int(present_raw_by_joint[joint])
        old_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, entry)
        relative_raw = joint_deg_to_relative_raw(
            joint,
            float(assigned_angle),
            获取关节比例(joint, joint_config),
            获取方向(entry),
        )
        new_home_raw = int(round(present_raw - int(relative_raw)))
        new_entry = dict(entry)
        new_entry["home_present_raw"] = new_home_raw
        new_entry["home_present_wrapped_raw"] = new_home_raw % RAW_COUNTS_PER_REV
        new_detail = present_raw_to_joint_detail(joint, present_raw, joint_config, new_entry)
        updates.append(
            {
                "joint": joint,
                "present_raw": present_raw,
                "assigned_angle_deg": float(assigned_angle),
                "old_detail": old_detail,
                "new_detail": new_detail,
                "old_home_present_raw": entry.get("home_present_raw"),
                "new_home_present_raw": new_home_raw,
                "new_entry": new_entry,
            }
        )
    return updates


if __name__ == "__main__":
    main()
