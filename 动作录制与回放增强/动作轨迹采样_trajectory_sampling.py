"""动作轨迹的纯计算工具。

预览器和真实回放共用这里的时长与时间参数化插值逻辑，
避免同一条动作在两端呈现不同的轨迹。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from 动作路径工具_motion_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 动作工具_common import DEFAULT_JOINT_SPEED_LIMITS, motor_raw_speed_required_duration  # noqa: E402


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
        required = max(required, motor_raw_speed_required_duration(current, targets, playback_config))
        duration = max(duration, required)

    duration /= normalized_speed
    if enforce_real_minimum:
        duration = max(duration, float(playback_config.get("real_mode_min_duration_sec", 0.0) or 0.0))
    return max(0.0, duration)


def sample_bounded_cinematic(
    targets_by_waypoint: Sequence[Mapping[str, float]],
    segment_index: int,
    ratio: float,
    segment_durations: Sequence[float] | None = None,
) -> dict[str, float]:
    """在相邻关键帧间采样按实际时间保持速度连续的单调三次曲线。"""

    if len(targets_by_waypoint) < 2:
        return dict(targets_by_waypoint[0]) if targets_by_waypoint else {}
    index = max(0, min(int(segment_index), len(targets_by_waypoint) - 2))
    t = max(0.0, min(1.0, float(ratio)))
    p1 = targets_by_waypoint[index]
    p2 = targets_by_waypoint[index + 1]
    durations = _normalized_segment_durations(targets_by_waypoint, segment_durations)
    duration = durations[index]
    return {
        joint: _sample_monotone_hermite(
            targets_by_waypoint,
            durations,
            index,
            joint,
            t,
            duration,
        )
        for joint in p2
    }


def _normalized_segment_durations(
    targets_by_waypoint: Sequence[Mapping[str, float]],
    segment_durations: Sequence[float] | None,
) -> list[float]:
    count = max(0, len(targets_by_waypoint) - 1)
    supplied = list(segment_durations or ())
    return [max(1e-6, float(supplied[index])) if index < len(supplied) else 1.0 for index in range(count)]


def _sample_monotone_hermite(
    targets: Sequence[Mapping[str, float]],
    durations: Sequence[float],
    segment_index: int,
    joint: str,
    ratio: float,
    duration: float,
) -> float:
    start = float(targets[segment_index][joint])
    end = float(targets[segment_index + 1][joint])
    start_velocity = _waypoint_velocity(targets, durations, segment_index, joint)
    end_velocity = _waypoint_velocity(targets, durations, segment_index + 1, joint)
    t2 = ratio * ratio
    t3 = t2 * ratio
    value = (
        (2.0 * t3 - 3.0 * t2 + 1.0) * start
        + (t3 - 2.0 * t2 + ratio) * duration * start_velocity
        + (-2.0 * t3 + 3.0 * t2) * end
        + (t3 - t2) * duration * end_velocity
    )
    return max(min(start, end), min(max(start, end), value))


def _waypoint_velocity(
    targets: Sequence[Mapping[str, float]],
    durations: Sequence[float],
    waypoint_index: int,
    joint: str,
) -> float:
    """Return a shape-preserving velocity shared by both adjacent segments."""

    if waypoint_index <= 0 or waypoint_index >= len(targets) - 1:
        return 0.0
    previous_duration = durations[waypoint_index - 1]
    next_duration = durations[waypoint_index]
    previous_slope = (
        float(targets[waypoint_index][joint]) - float(targets[waypoint_index - 1][joint])
    ) / previous_duration
    next_slope = (
        float(targets[waypoint_index + 1][joint]) - float(targets[waypoint_index][joint])
    ) / next_duration
    if previous_slope == 0.0 or next_slope == 0.0 or previous_slope * next_slope <= 0.0:
        return 0.0
    previous_weight = 2.0 * next_duration + previous_duration
    next_weight = next_duration + 2.0 * previous_duration
    return (previous_weight + next_weight) / (
        previous_weight / previous_slope + next_weight / next_slope
    )
