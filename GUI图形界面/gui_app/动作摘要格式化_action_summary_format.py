"""动作摘要展示格式化。"""

from __future__ import annotations

import json
from collections.abc import Mapping


SUMMARY_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("帧数", "pose_count"),
    ("时长", "总时长"),
    ("末端轨迹点", "末端轨迹点数"),
    ("包含 raw", "是否包含 raw"),
    ("包含 TCP", "是否包含 tcp_pose"),
    ("包含夹爪", "是否包含 gripper"),
    ("包含多圈", "是否包含 multi_turn_state"),
    ("来源", "source"),
    ("更新时间", "updated_at"),
)


def format_action_summary_lines(name: str, summary: object) -> list[str]:
    lines = [f"动作：{name}", ""]
    if isinstance(summary, Mapping):
        for label, key in SUMMARY_FIELD_ORDER:
            if key in summary:
                lines.append(f"{label}: {summary.get(key)}")
        if "pose_count" not in summary and "frame_count" in summary:
            lines.append(f"帧数: {summary.get('frame_count')}")
        if "总时长" not in summary and "duration_sec" in summary:
            lines.append(f"时长: {summary.get('duration_sec')}")
        joints = summary.get("joints") or summary.get("joint_names")
        if isinstance(joints, (list, tuple)):
            lines.append(f"关节: {', '.join(str(item) for item in joints)}")
    if len(lines) <= 2:
        lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
    return lines


def format_action_summary_detail(name: str, summary: object) -> str:
    return "\n".join(format_action_summary_lines(name, summary))
