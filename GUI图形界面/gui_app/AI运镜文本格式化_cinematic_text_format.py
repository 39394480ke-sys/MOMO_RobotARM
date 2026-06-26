"""AI 运镜项目展示文本格式化。"""

from __future__ import annotations

import json
from typing import Any


def format_cinematic_analysis(project: dict[str, Any]) -> str:
    analysis = project.get("motion_analysis", {})
    lines = ["视频运动质量分析", ""]
    lines.append(json.dumps(analysis.get("summary", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("抖动区间")
    for item in analysis.get("jitter_intervals", []):
        lines.append(
            f"- {item.get('start_time')}s -> {item.get('end_time')}s | "
            f"frame {item.get('start_frame')}..{item.get('end_frame')}"
        )
    lines.append("")
    lines.append("稳定区间")
    for item in analysis.get("stable_intervals", []):
        lines.append(
            f"- {item.get('start_time')}s -> {item.get('end_time')}s | "
            f"frame {item.get('start_frame')}..{item.get('end_frame')}"
        )
    lines.append("")
    lines.append("候选关键帧")
    for item in analysis.get("candidate_keyframes", []):
        lines.append(
            f"- frame {item.get('frame_index')} / {item.get('time')}s | "
            f"score {item.get('score')}: {item.get('reason')}"
        )
    return "\n".join(lines)


def format_cinematic_keyframes(keyframes: list[Any]) -> str:
    lines = ["Keyframe List", ""]
    for item in keyframes:
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"{item.get('id', 'K?')}:",
                f"- time: {item.get('time')}s / frame {item.get('frame_index')}",
                f"- pose: {json.dumps(item.get('pose', {}), ensure_ascii=False)}",
                f"- composition: {item.get('composition')}",
                f"- reason: {item.get('reason')}",
                f"- dwell_time: {item.get('dwell_time', 0.0)}",
                "",
            ]
        )
    return "\n".join(lines)


def format_cinematic_trajectory(project: dict[str, Any]) -> str:
    trajectory = project.get("trajectory_plan", {})
    generated = project.get("generated_action", {})
    lines = [
        "Trajectory",
        f"- type: {trajectory.get('type')}",
        f"- action: {generated.get('name')} ({generated.get('pose_count')} points)",
        f"- action_path: {generated.get('path')}",
        f"- blending strategy: {json.dumps(trajectory.get('blending_strategy', {}), ensure_ascii=False)}",
        f"- speed profile: {json.dumps(trajectory.get('speed_profile', {}), ensure_ascii=False)}",
        f"- recommended execution: {json.dumps(trajectory.get('recommended_execution', {}), ensure_ascii=False)}",
    ]
    return "\n".join(lines)
