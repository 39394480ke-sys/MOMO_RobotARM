"""动作轨迹的纯计算工具。

预览器和真实回放共用这里的时长与 Catmull-Rom 采样逻辑，
避免同一条动作在两端呈现不同的轨迹。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from 动作路径工具_motion_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import bounded_catmull_rom  # noqa: E402
from 动作工具_common import DEFAULT_JOINT_SPEED_LIMITS  # noqa: E402


def effective_segment_duration(
    pose: Mapping[str, Any],
    playback_config: Mapping[str, Any],
    current: Mapping[str, float],
    targets: Mapping[str, float],
    *,
    speed: float = 1.0,
    enforce_real_minimum: bool = False,
) -> float:
    """返回一段轨迹在指定速度下的有效时长。"""

    normalized_speed = max(0.1, min(3.0, float(speed)))
    configured = float(pose.get("duration_sec", 0.0) or 0.0)
    duration = configured if configured > 0 else float(playback_config.get("default_duration_sec", 1.5))

    if bool(playback_config.get("auto_duration_from_distance", True)):
        limits = playback_config.get("joint_speed_limits", {})
        limits = limits if isinstance(limits, Mapping) else {}
        required = 0.0
        for joint, target in targets.items():
            limit = float(limits.get(joint, DEFAULT_JOINT_SPEED_LIMITS.get(joint, 45.0)))
            if limit <= 0:
                continue
            required = max(required, abs(float(target) - float(current.get(joint, target))) / limit)
        duration = max(duration, required)

    duration /= normalized_speed
    if enforce_real_minimum:
        duration = max(duration, float(playback_config.get("real_mode_min_duration_sec", 0.0) or 0.0))
    return max(0.0, duration)


def sample_bounded_cinematic(
    targets_by_waypoint: Sequence[Mapping[str, float]],
    segment_index: int,
    ratio: float,
) -> dict[str, float]:
    """在相邻关键帧间采样有界 Catmull-Rom 曲线。"""

    if len(targets_by_waypoint) < 2:
        return dict(targets_by_waypoint[0]) if targets_by_waypoint else {}
    index = max(0, min(int(segment_index), len(targets_by_waypoint) - 2))
    t = max(0.0, min(1.0, float(ratio)))
    p0 = targets_by_waypoint[max(0, index - 1)]
    p1 = targets_by_waypoint[index]
    p2 = targets_by_waypoint[index + 1]
    p3 = targets_by_waypoint[min(len(targets_by_waypoint) - 1, index + 2)]
    return {
        joint: bounded_catmull_rom(
            float(p0.get(joint, p1[joint])),
            float(p1[joint]),
            float(p2[joint]),
            float(p3.get(joint, p2[joint])),
            t,
        )
        for joint in p2
    }
