"""GUI 运动/位姿文本格式化工具。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def format_joint_value(value: Any, unit: str = "deg") -> str:
    try:
        return f"{float(value):.2f} {unit}".rstrip()
    except Exception:
        suffix = f" {unit}" if unit else ""
        return f"{value}{suffix}"


def format_motion_value(value: Any, unit: str, *, decimals: int = 3, signed: bool = False, prefix: str = "") -> str:
    try:
        sign = "+" if signed else ""
        return f"{prefix}{float(value):{sign}.{int(decimals)}f}{unit}"
    except Exception:
        return f"{prefix}{value}{unit}"


def append_joint_lines(lines: list[str], title: str, joints: object, unit: str = "deg") -> bool:
    if not isinstance(joints, Mapping):
        return False
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(title)
    for key, value in joints.items():
        lines.append(f"  {key}: {format_joint_value(value, unit)}")
    return True


def append_tcp_lines(lines: list[str], title: str, pose: object) -> bool:
    if not isinstance(pose, Mapping):
        return False
    xyz = pose.get("xyz")
    rpy = pose.get("rpy")
    added = False
    appended_blank = bool(lines and lines[-1] != "")
    if appended_blank:
        lines.append("")
    lines.append(title)
    if isinstance(xyz, (list, tuple)) and len(xyz) >= 3:
        lines.append(f"  XYZ: {float(xyz[0]):.4f}, {float(xyz[1]):.4f}, {float(xyz[2]):.4f} m")
        added = True
    if isinstance(rpy, (list, tuple)) and len(rpy) >= 3:
        lines.append(f"  RPY: {float(rpy[0]) * 57.2958:.2f}, {float(rpy[1]) * 57.2958:.2f}, {float(rpy[2]) * 57.2958:.2f} deg")
        added = True
    if not added:
        lines.pop()
        if appended_blank and lines and lines[-1] == "":
            lines.pop()
    return added


def format_pose_detail(name: str, pose: object) -> str:
    lines = [f"姿态：{name}", ""]
    if isinstance(pose, Mapping):
        append_joint_lines(lines, "关节角度", pose.get("joints_deg") or pose.get("joints") or pose.get("targets_deg"))
        append_tcp_lines(lines, "TCP", pose.get("tcp_pose") or pose.get("tcp"))
    if len(lines) <= 2:
        lines.append(json.dumps(pose, ensure_ascii=False, indent=2))
    return "\n".join(lines)
