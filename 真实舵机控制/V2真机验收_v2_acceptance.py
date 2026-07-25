"""V2 真机验收前的只读报告和逐轴小步计划。

本工具不连接总线、不使能力矩、不写 Goal_Position。真实动作仍需操作者
在确认现场安全后，通过现有控制器逐步执行。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from 真实路径工具_real_path_utils import real_config_path
from 真实配置加载_real_config_loader import DEFAULT_CALIBRATION_PATH, load_real_config
from 标定管理_calibration_manager import CalibrationManager
from 角度映射_angle_mapper import effective_joint_limits


ACCEPTANCE_ORDER = ("j15", "j14", "j13", "j12", "j11", "j10")


def build_acceptance_steps(baseline: Mapping[str, float]) -> list[dict[str, float | str]]:
    """Return +delta, baseline, -delta, baseline steps in distal-first order."""

    steps: list[dict[str, float | str]] = []
    for joint in ACCEPTANCE_ORDER:
        center = float(baseline.get(joint, 0.0))
        delta = 1.0 if joint == "j10" else 0.5
        unit = "mm" if joint == "j10" else "deg"
        for label, target in (
            ("positive", center + delta),
            ("return", center),
            ("negative", center - delta),
            ("return", center),
        ):
            steps.append({"joint": joint, "phase": label, "target": target, "unit": unit})
    return steps


def build_preflight_report(
    config: dict[str, Any],
    calibration_path: str | Path,
) -> dict[str, Any]:
    robot = config.get("robot", {})
    variant = str(robot.get("variant", ""))
    if variant != "V2":
        raise ValueError(f"V2 真机验收工具只支持 V2，当前 robot.variant={variant!r}。")
    manager = CalibrationManager(calibration_path, config)
    scales = dict(robot.get("joint_scales", {}))
    joints = {
        str(item["key"]): {**item, "joint_scale": float(scales[str(item["key"])])}
        for item in robot.get("joints", [])
        if isinstance(item, dict) and item.get("key") in scales
    }
    effective_limits: dict[str, dict[str, float]] = {}
    for joint in ACCEPTANCE_ORDER:
        if joint not in joints:
            continue
        calibration = manager.get(joint) if manager.has(joint) else None
        lower, upper = effective_joint_limits(joint, joints[joint], calibration)
        effective_limits[joint] = {"min": lower, "max": upper}

    baseline = {
        joint: float(joints.get(joint, {}).get("默认角度", 0.0))
        for joint in ACCEPTANCE_ORDER
    }
    calibration_report = manager.calibration_report()
    acceptance_steps = build_acceptance_steps(baseline)
    plan_errors = validate_acceptance_plan(acceptance_steps, effective_limits)
    calibration_ready = bool(calibration_report["允许真机移动"])
    plan_valid = not plan_errors
    return {
        "mode": "read_only_plan",
        "robot_variant": variant,
        "calibration_ready_for_real": calibration_ready,
        "calibration_variant": calibration_report["机械版本"],
        "joint_scales": scales,
        "effective_limits": effective_limits,
        "acceptance_steps": acceptance_steps,
        "plan_valid": plan_valid,
        "plan_errors": plan_errors,
        "staged_plan_ready": calibration_ready and plan_valid,
        "hardware_writes": False,
        "approved_for_hardware_execution": False,
        "requires_explicit_real_approval": True,
    }


def validate_acceptance_plan(
    steps: list[dict[str, float | str]],
    limits: Mapping[str, Mapping[str, float]],
) -> list[str]:
    """Validate every staged target without connecting to or writing the servo bus."""

    errors: list[str] = []
    for index, step in enumerate(steps, start=1):
        joint = str(step["joint"])
        bounds = limits.get(joint)
        if bounds is None:
            errors.append(f"步骤 {index} 的 {joint} 缺少有效限位。")
            continue
        target = float(step["target"])
        lower = float(bounds["min"])
        upper = float(bounds["max"])
        if target < lower or target > upper:
            errors.append(
                f"步骤 {index} 的 {joint} 目标 {target:g} 超出有效范围 [{lower:g}, {upper:g}]。"
            )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 V2 真机验收前只读报告，不移动机械臂")
    parser.add_argument("--config", default=str(real_config_path()), help="真实配置路径")
    parser.add_argument("--calibration", default=None, help="标定文件路径，默认读取配置 calibration.path")
    parser.add_argument("--require-ready", action="store_true", help="标定版本或字段不完整时返回非零")
    return parser.parse_args()


def resolve_calibration_path(
    config_path: str | Path,
    config: dict[str, Any],
    override: str | Path | None,
) -> Path:
    """Resolve relative calibration paths from the selected config's directory."""

    value = override if override is not None else config.get("calibration", {}).get("path", DEFAULT_CALIBRATION_PATH)
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path(config_path).expanduser().resolve().parent / path).resolve()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_real_config(config_path)
    calibration_path = resolve_calibration_path(config_path, config, args.calibration)
    report = build_preflight_report(config, calibration_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ready and not report["staged_plan_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
