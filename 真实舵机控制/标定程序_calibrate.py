"""真实舵机标定程序。

用途：
- 连接真实 Feetech / LeRobot 舵机总线。
- 读取当前硬件状态。
- 生成新的 标定文件.json。
- 可选把标定寄存器写入舵机。

默认不属于 dry-run 主程序。运行前请确认机械臂处于安全位置。
"""

from __future__ import annotations

import argparse
import select
import sys
import time
from pathlib import Path
from typing import Any

from 标定工具_calibration_utils import (
    ARM_MOTOR_IDS,
    GRIPPER_MIDPOINT_HOMING_OFFSET,
    JOINTS,
    MULTI_TURN_DISABLED_LIMIT_RAW,
    MULTI_TURN_JOINTS,
    MULTI_TURN_PHASE_VALUE,
    POSITION_MODE_VALUE,
    RAW_COUNTS_PER_REV,
    SINGLE_TURN_CALIBRATION_JOINTS,
    bus_read,
    bus_sync_read_positions,
    bus_write,
    confirm_or_abort,
    create_feetech_bus,
    has_complete_single_turn_calibration,
    joint_label,
    load_config,
    load_json,
    save_json,
)


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    port = args.port or config.get("transport", {}).get("port")
    if not port:
        raise SystemExit("没有串口。请在真实配置.yaml 中设置 transport.port，或传入 --port。")

    output_name = args.output
    if output_name is None:
        output_name = "标定文件_dry_run预览.json" if args.dry_run else "标定文件.json"

    output_path = Path(output_name)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    old_calibration = load_json(output_path, default={}) or {}

    print("真实舵机标定程序")
    print(f"串口：{port}")
    print(f"输出文件：{output_path}")
    print("注意：dry-run 主程序不需要依赖；本标定程序需要真实硬件和 momo_rebot 环境。")

    if args.dry_run:
        print("当前为 --dry-run：不会连接舵机，也不会写寄存器，只生成基于旧标定的预览。")
        payload = build_dry_run_preview(old_calibration)
        save_json(output_path, payload)
        print(f"已写入 dry-run 预览标定文件：{output_path}")
        return

    if not args.yes:
        confirm_or_abort(
            "该程序会连接真实舵机并读取当前位置。若使用 --apply-registers，还会写入标定寄存器。",
            "我确认开始标定",
        )

    bus = create_feetech_bus(port, include_gripper=True)
    try:
        bus.connect()
        print("已连接 Feetech 舵机总线。")
        print_hardware_status(bus)

        if args.apply_registers:
            apply_multi_turn_registers(bus)
        else:
            print("未传入 --apply-registers：不会写入多圈标定寄存器，只读取当前位置生成标定文件。")

        payload: dict[str, Any] = {"_meta": build_meta()}
        payload.update(build_multi_turn_entries(bus))
        payload.update(build_single_turn_entries(bus, old_calibration, force_recalibrate=args.recalibrate_single))

        if args.apply_registers:
            apply_single_turn_registers(bus, payload)

        save_json(output_path, payload)
        print(f"标定文件已保存：{output_path}")
        print("提示：真实控制器 connect() 会读取这个文件，不会重新标定。")
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
    parser = argparse.ArgumentParser(description="MomoAgent / SOARM MOCE 真实舵机标定程序")
    parser.add_argument("--config", default=str(BASE_DIR / "真实配置.yaml"), help="真实配置文件路径")
    parser.add_argument("--port", default=None, help="串口，例如 /dev/tty.usbmodemXXXX")
    parser.add_argument("--output", default=None, help="输出标定文件。dry-run 默认写 标定文件_dry_run预览.json")
    parser.add_argument("--dry-run", action="store_true", help="不连接硬件，只生成预览")
    parser.add_argument("--apply-registers", action="store_true", help="把多圈/单圈标定寄存器写入舵机")
    parser.add_argument("--recalibrate-single", action="store_true", help="强制重新标定 J1/J4/夹爪")
    parser.add_argument("--yes", action="store_true", help="跳过启动固定文本确认，适合自动化但不推荐真机首次使用")
    return parser.parse_args()


def print_hardware_status(bus: Any) -> None:
    """读取当前硬件状态。"""

    print("\n当前硬件状态：")
    joint_names = JOINTS + ["gripper"]
    positions = bus_sync_read_positions(bus, joint_names)
    for joint_name in joint_names:
        status = [f"Present_Position={positions.get(joint_name)}"]
        for register_name in ["Present_Velocity", "Present_Current", "Moving"]:
            try:
                status.append(f"{register_name}={bus_read(bus, register_name, joint_name)}")
            except Exception:
                status.append(f"{register_name}=未读取")
        print(f"  {joint_label(joint_name)} ({joint_name})：" + " ".join(status))

    if hasattr(bus, "read_calibration"):
        try:
            hardware_calibration = bus.read_calibration()
            print("\n硬件已有 calibration 读取成功。")
            print(hardware_calibration)
        except Exception as error:
            print(f"\n读取硬件已有 calibration 失败：{error}")


def apply_multi_turn_registers(bus: Any) -> None:
    """写入 J2/J3/J5 多圈寄存器配置。"""

    print("\n写入多圈关节寄存器配置：Operating_Mode=0, Homing_Offset=0, Phase=28, Limit=0/0")
    for joint_name in MULTI_TURN_JOINTS:
        bus_write(bus, "Operating_Mode", joint_name, POSITION_MODE_VALUE)
        bus_write(bus, "Homing_Offset", joint_name, 0)
        bus_write(bus, "Phase", joint_name, MULTI_TURN_PHASE_VALUE)
        bus_write(bus, "Min_Position_Limit", joint_name, MULTI_TURN_DISABLED_LIMIT_RAW)
        bus_write(bus, "Max_Position_Limit", joint_name, MULTI_TURN_DISABLED_LIMIT_RAW)
        print(f"  已写入 {joint_label(joint_name)} ({joint_name})")


def build_multi_turn_entries(bus: Any) -> dict[str, dict[str, Any]]:
    """读取 J2/J3/J5 当前 raw，生成多圈标定项。"""

    positions = bus_sync_read_positions(bus, MULTI_TURN_JOINTS)
    entries = {}
    for joint_name in MULTI_TURN_JOINTS:
        present_raw = int(positions[joint_name])
        entries[joint_name] = {
            "show_name": joint_label(joint_name),
            "模式": "多圈",
            "direction": 1,
            "id": ARM_MOTOR_IDS[joint_name],
            "drive_mode": 0,
            "homing_offset": 0,
            "phase": MULTI_TURN_PHASE_VALUE,
            "range_min": 0,
            "range_max": 0,
            "operating_mode": POSITION_MODE_VALUE,
            "home_present_raw": present_raw,
            "home_present_wrapped_raw": present_raw % RAW_COUNTS_PER_REV,
        }
        print(
            f"{joint_label(joint_name)} 多圈 home_present_raw={present_raw}, "
            f"wrapped={present_raw % RAW_COUNTS_PER_REV}"
        )
    return entries


def build_single_turn_entries(
    bus: Any,
    old_calibration: dict[str, Any],
    force_recalibrate: bool = False,
) -> dict[str, dict[str, Any]]:
    """生成 J1/J4/夹爪单圈标定项。"""

    if has_complete_single_turn_calibration(old_calibration) and not force_recalibrate:
        answer = input(
            "\n检测到已有 J1/J4/夹爪标定。\n"
            "按 ENTER 复用已有单圈标定。\n"
            "输入 c 并回车，重新标定 J1/J4/夹爪："
        ).strip().lower()
        if answer != "c":
            print("复用已有 J1/J4/夹爪单圈标定。")
            return {joint_name: dict(old_calibration[joint_name]) for joint_name in SINGLE_TURN_CALIBRATION_JOINTS}

    print("\n开始重新标定 J1/J4/夹爪。")
    bus.disable_torque()
    input(
        "请手动把 J1 底座旋转放到安全中间位置。\n"
        "请手动把 J4 腕部俯仰放到你希望的 0 度位置。\n"
        "请把夹爪放到安全位置。\n"
        "完成后按 ENTER。"
    )

    homing_offsets = get_half_turn_homing_offsets(bus)
    positions = bus_sync_read_positions(bus, SINGLE_TURN_CALIBRATION_JOINTS)
    ranges = record_single_turn_ranges(bus)

    entries: dict[str, dict[str, Any]] = {}
    for joint_name in ["shoulder_pan", "wrist_flex"]:
        old_entry = old_calibration.get(joint_name, {}) if isinstance(old_calibration.get(joint_name), dict) else {}
        homing_offset = homing_offsets.get(joint_name, old_entry.get("homing_offset", 0))
        range_min, range_max = ranges[joint_name]
        entries[joint_name] = {
            "show_name": joint_label(joint_name),
            "模式": "单圈",
            "direction": int(old_entry.get("direction", 1)),
            "id": ARM_MOTOR_IDS[joint_name],
            "drive_mode": 0,
            "homing_offset": int(homing_offset),
            "range_min": int(range_min),
            "range_max": int(range_max),
            "operating_mode": POSITION_MODE_VALUE,
            "zero_present_raw": int(positions[joint_name]),
        }

    gripper_range_min, gripper_range_max = ranges["gripper"]
    entries["gripper"] = {
        "show_name": joint_label("gripper"),
        "模式": "单圈",
        "direction": 1,
        "id": ARM_MOTOR_IDS["gripper"],
        "drive_mode": 0,
        "homing_offset": GRIPPER_MIDPOINT_HOMING_OFFSET,
        "range_min": int(gripper_range_min),
        "range_max": int(gripper_range_max),
        "operating_mode": POSITION_MODE_VALUE,
        "zero_present_raw": int(gripper_range_min),
    }
    return entries


def apply_single_turn_registers(bus: Any, calibration: dict[str, Any]) -> None:
    """把 J1/J4/夹爪单圈寄存器写入舵机。"""

    print("\n写入 J1/J4/夹爪单圈寄存器配置。")
    for joint_name in SINGLE_TURN_CALIBRATION_JOINTS:
        entry = calibration[joint_name]
        bus_write(bus, "Operating_Mode", joint_name, int(entry.get("operating_mode", POSITION_MODE_VALUE)))
        bus_write(bus, "Homing_Offset", joint_name, int(entry.get("homing_offset", 0)))
        bus_write(bus, "Min_Position_Limit", joint_name, int(entry["range_min"]))
        bus_write(bus, "Max_Position_Limit", joint_name, int(entry["range_max"]))
        print(f"  已写入 {joint_label(joint_name)} ({joint_name})")


def get_half_turn_homing_offsets(bus: Any) -> dict[str, int]:
    """尽量调用 set_half_turn_homings 标定 J1。"""

    if not hasattr(bus, "set_half_turn_homings"):
        print("当前 Feetech bus 不支持 set_half_turn_homings，J1 homing_offset 使用 0。")
        return {}

    try:
        result = bus.set_half_turn_homings(["shoulder_pan"])
        if isinstance(result, dict):
            print(f"set_half_turn_homings 返回：{result}")
            return {key: int(value) for key, value in result.items()}
        print(f"set_half_turn_homings 返回非字典：{result}")
    except Exception as error:
        print(f"set_half_turn_homings 调用失败，J1 homing_offset 使用旧值或 0：{error}")
    return {}


def record_single_turn_ranges(bus: Any) -> dict[str, tuple[int, int]]:
    """记录 J1/J4/夹爪安全运动范围。"""

    print("\n请手动让 J1/J4/夹爪在安全范围内完整移动一遍。")
    input("准备开始记录范围时按 ENTER。")

    print("开始采样，按 ENTER 结束。采样期间请缓慢移动 J1/J4/夹爪。")
    ranges = {joint_name: [10**9, -10**9] for joint_name in SINGLE_TURN_CALIBRATION_JOINTS}
    latest = {joint_name: None for joint_name in SINGLE_TURN_CALIBRATION_JOINTS}
    print("\033[2J\033[H", end="")
    while True:
        for joint_name in SINGLE_TURN_CALIBRATION_JOINTS:
            raw = read_present_position_with_retry(bus, joint_name)
            if raw is None:
                continue
            latest[joint_name] = raw
            ranges[joint_name][0] = min(ranges[joint_name][0], raw)
            ranges[joint_name][1] = max(ranges[joint_name][1], raw)
        render_single_table(ranges, latest)
        if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
            sys.stdin.readline()
            break
    print()
    result: dict[str, tuple[int, int]] = {}
    for joint_name, values in ranges.items():
        if values[0] == 10**9 or values[1] == -10**9:
            raise RuntimeError(f"{joint_label(joint_name)} 没有采集到有效 Present_Position。")
        result[joint_name] = (values[0], values[1])
    return result


def read_present_position_with_retry(bus: Any, joint_name: str, retries: int = 3) -> int | None:
    """逐个读取 Present_Position，失败时重试，避免批量 sync_read 不稳定。"""

    for _ in range(retries):
        try:
            return bus_read(bus, "Present_Position", joint_name)
        except Exception:
            time.sleep(0.03)
    return None


def render_single_table(ranges: dict[str, list[int]], latest: dict[str, int | None]) -> None:
    """在终端原地刷新单个范围表。"""

    print("\033[H", end="")
    print("-------------------------------------------")
    print(f"{'NAME':<15} | {'MIN':>6} | {'POS':>6} | {'MAX':>6}")
    for joint_name in SINGLE_TURN_CALIBRATION_JOINTS:
        min_raw = ranges[joint_name][0]
        max_raw = ranges[joint_name][1]
        pos_raw = latest[joint_name]
        min_text = "----" if min_raw == 10**9 else str(min_raw)
        max_text = "----" if max_raw == -10**9 else str(max_raw)
        pos_text = "----" if pos_raw is None else str(pos_raw)
        print(f"{joint_name:<15} | {min_text:>6} | {pos_text:>6} | {max_text:>6}")
    print("\n按 ENTER 结束采样。", end="", flush=True)


def normalize_recorded_ranges(result: Any) -> dict[str, tuple[int, int]]:
    """把 LeRobot range 结果整理为 joint -> (min, max)。"""

    if isinstance(result, tuple) and len(result) >= 2 and all(isinstance(item, dict) for item in result[:2]):
        min_values, max_values = result[0], result[1]
        return {
            joint_name: (int(min_values[joint_name]), int(max_values[joint_name]))
            for joint_name in SINGLE_TURN_CALIBRATION_JOINTS
            if joint_name in min_values and joint_name in max_values
        }
    if not isinstance(result, dict):
        return {}
    ranges: dict[str, tuple[int, int]] = {}
    for joint_name in SINGLE_TURN_CALIBRATION_JOINTS:
        item = result.get(joint_name)
        if isinstance(item, dict):
            range_min = item.get("range_min", item.get("min", item.get("Min_Position_Limit")))
            range_max = item.get("range_max", item.get("max", item.get("Max_Position_Limit")))
            if range_min is not None and range_max is not None:
                ranges[joint_name] = (int(range_min), int(range_max))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            ranges[joint_name] = (int(item[0]), int(item[1]))
    return ranges


def build_meta() -> dict[str, Any]:
    """生成标定文件 _meta。"""

    return {
        "generated_at_unix_s": time.time(),
        "script": "标定程序_calibrate.py",
        "bounded_single_turn_joints": list(SINGLE_TURN_CALIBRATION_JOINTS),
        "absolute_raw_joints": list(MULTI_TURN_JOINTS),
        "notes": {
            "bounded_single_turn": "J1/J4/夹爪使用有限位单圈标定。",
            "absolute_raw": "J2/J3/J5 使用 mode 0 + Phase 28 + 0/0 限位的多圈绝对 raw 模式。",
            "home": "home() 回到由 zero_present_raw / home_present_raw 定义的相对 0 度。",
        },
    }


def build_dry_run_preview(old_calibration: dict[str, Any]) -> dict[str, Any]:
    """生成 dry-run 预览文件。没有旧标定时使用安全模板值。"""

    payload: dict[str, Any] = {"_meta": build_meta()}
    for joint_name in JOINTS + ["gripper"]:
        entry = old_calibration.get(joint_name)
        if isinstance(entry, dict):
            payload[joint_name] = dict(entry)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"标定程序失败：{error}") from error
