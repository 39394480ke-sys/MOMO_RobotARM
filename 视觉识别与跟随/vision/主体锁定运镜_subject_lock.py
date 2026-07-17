"""静止主体的 J10/J11 标定曲线、播放计划与绝对时钟调度。"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .路径工具_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

def calibration_positions(start_mm: float, end_mm: float, count: int = 11) -> list[float]:
    count = max(2, int(count))
    start = float(start_mm)
    span = float(end_mm) - start
    return [round(start + span * index / (count - 1), 6) for index in range(count)]


@dataclass(frozen=True)
class ShapePreservingHermiteCurve:
    x: tuple[float, ...]
    y: tuple[float, ...]
    slopes: tuple[float, ...]

    @classmethod
    def from_points(cls, points: Iterable[Mapping[str, Any]]) -> "ShapePreservingHermiteCurve":
        pairs = sorted((float(point["j10_mm"]), float(point["j11_deg"])) for point in points)
        unique: list[tuple[float, float]] = []
        for x_value, y_value in pairs:
            if unique and abs(x_value - unique[-1][0]) <= 1e-9:
                raise ValueError("标定点包含重复的 J10 位置。")
            unique.append((x_value, y_value))
        if len(unique) < 2:
            raise ValueError("至少需要两个不同的标定点。")
        x_values = tuple(item[0] for item in unique)
        y_values = tuple(item[1] for item in unique)
        return cls(x_values, y_values, tuple(_pchip_slopes(x_values, y_values)))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShapePreservingHermiteCurve":
        return cls(
            tuple(float(value) for value in payload.get("x", [])),
            tuple(float(value) for value in payload.get("y", [])),
            tuple(float(value) for value in payload.get("slopes", [])),
        )._validated()

    def _validated(self) -> "ShapePreservingHermiteCurve":
        if len(self.x) < 2 or len(self.x) != len(self.y) or len(self.x) != len(self.slopes):
            raise ValueError("主体锁定曲线数据不完整。")
        if any(self.x[index + 1] <= self.x[index] for index in range(len(self.x) - 1)):
            raise ValueError("主体锁定曲线的 J10 位置必须严格递增。")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"type": "pchip", "x": list(self.x), "y": list(self.y), "slopes": list(self.slopes)}

    def evaluate(self, x_value: float) -> float:
        self._validated()
        x = min(self.x[-1], max(self.x[0], float(x_value)))
        if x >= self.x[-1]:
            return self.y[-1]
        index = 0
        while index + 1 < len(self.x) and x > self.x[index + 1]:
            index += 1
        left = self.x[index]
        right = self.x[index + 1]
        width = right - left
        u = (x - left) / width
        h00 = 2.0 * u**3 - 3.0 * u**2 + 1.0
        h10 = u**3 - 2.0 * u**2 + u
        h01 = -2.0 * u**3 + 3.0 * u**2
        h11 = u**3 - u**2
        value = h00 * self.y[index] + h10 * width * self.slopes[index] + h01 * self.y[index + 1] + h11 * width * self.slopes[index + 1]
        lower = min(self.y[index], self.y[index + 1])
        upper = max(self.y[index], self.y[index + 1])
        return min(upper, max(lower, value))


def _pchip_slopes(x_values: tuple[float, ...], y_values: tuple[float, ...]) -> list[float]:
    count = len(x_values)
    widths = [x_values[index + 1] - x_values[index] for index in range(count - 1)]
    deltas = [(y_values[index + 1] - y_values[index]) / widths[index] for index in range(count - 1)]
    if count == 2:
        return [deltas[0], deltas[0]]
    slopes = [0.0] * count
    for index in range(1, count - 1):
        before = deltas[index - 1]
        after = deltas[index]
        if before == 0.0 or after == 0.0 or before * after < 0.0:
            slopes[index] = 0.0
            continue
        weight_before = 2.0 * widths[index] + widths[index - 1]
        weight_after = widths[index] + 2.0 * widths[index - 1]
        slopes[index] = (weight_before + weight_after) / (weight_before / before + weight_after / after)
    slopes[0] = _endpoint_slope(widths[0], widths[1], deltas[0], deltas[1])
    slopes[-1] = _endpoint_slope(widths[-1], widths[-2], deltas[-1], deltas[-2])
    return slopes


def _endpoint_slope(width: float, neighbor_width: float, delta: float, neighbor_delta: float) -> float:
    slope = ((2.0 * width + neighbor_width) * delta - width * neighbor_delta) / (width + neighbor_width)
    if slope * delta <= 0.0:
        return 0.0
    if delta * neighbor_delta < 0.0 and abs(slope) > abs(3.0 * delta):
        return 3.0 * delta
    return slope


def validate_calibration_samples(points: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """拒绝单点跳变，避免跟踪瞬时漂移被写进正式轨迹。"""
    samples = [dict(point) for point in points]
    ordered = sorted(samples, key=lambda point: float(point["j10_mm"]))
    if len(ordered) < 3:
        return samples
    deviations: list[tuple[int, float]] = []
    for index in range(1, len(ordered) - 1):
        before = ordered[index - 1]
        current = ordered[index]
        after = ordered[index + 1]
        width = float(after["j10_mm"]) - float(before["j10_mm"])
        if width <= 1e-9:
            raise ValueError("标定点的 J10 位置必须严格递增。")
        ratio = (float(current["j10_mm"]) - float(before["j10_mm"])) / width
        expected = float(before["j11_deg"]) + (float(after["j11_deg"]) - float(before["j11_deg"])) * ratio
        deviations.append((index, abs(float(current["j11_deg"]) - expected)))
    baseline = sorted(value for _, value in deviations)[len(deviations) // 2]
    threshold = max(2.0, baseline * 6.0)
    for index, deviation in deviations:
        before_y = float(ordered[index - 1]["j11_deg"])
        current_y = float(ordered[index]["j11_deg"])
        after_y = float(ordered[index + 1]["j11_deg"])
        isolated_turn = (current_y - before_y) * (after_y - current_y) < 0.0
        if isolated_turn and deviation > threshold:
            raise ValueError(f"检测到异常标定点 {index + 1}，请重新标定。")
    return samples


def build_playback_plan(
    curve: ShapePreservingHermiteCurve,
    *,
    start_mm: float,
    end_mm: float,
    speed_mm_s: float,
    update_hz: float = 40.0,
    ease_sec: float = 0.8,
) -> list[dict[str, Any]]:
    speed = max(0.05, abs(float(speed_mm_s)))
    hz = max(2.0, float(update_hz))
    start = float(start_mm)
    end = float(end_mm)
    distance = abs(end - start)
    if distance <= 1e-9:
        raise ValueError("J10 起点和终点不能相同。")
    easing = min(max(0.0, float(ease_sec)), distance / speed * 0.45)
    duration = distance / speed + easing
    steps = max(2, int(math.ceil(duration * hz)) + 1)
    interval = duration / (steps - 1)
    result: list[dict[str, Any]] = []
    for index in range(steps):
        elapsed = index * interval
        progress = _cosine_ramp_progress(elapsed, distance=distance, speed=speed, ease_sec=easing)
        j10 = start + (end - start) * progress
        if index == 0:
            j10 = start
        elif index == steps - 1:
            j10 = end
        result.append(
            {
                "index": index,
                "time_sec": round(index * interval, 9),
                "targets_deg": {"j10": round(j10, 6), "j11": round(curve.evaluate(j10), 6)},
            }
        )
    return result


def _cosine_ramp_progress(elapsed_sec: float, *, distance: float, speed: float, ease_sec: float) -> float:
    """半余弦速度坡道：加速段和匀速段的速度连续，不会在交界处跳变。"""
    total_distance = max(1e-9, float(distance))
    cruise_speed = max(1e-9, float(speed))
    ease = max(0.0, float(ease_sec))
    elapsed = max(0.0, float(elapsed_sec))
    if ease <= 1e-9:
        return min(1.0, elapsed * cruise_speed / total_distance)
    duration = total_distance / cruise_speed + ease
    elapsed = min(duration, elapsed)
    ramp_distance = 0.5 * cruise_speed * ease
    if elapsed < ease:
        covered = 0.5 * cruise_speed * (elapsed - ease / math.pi * math.sin(math.pi * elapsed / ease))
    elif elapsed <= duration - ease:
        covered = ramp_distance + cruise_speed * (elapsed - ease)
    else:
        remaining = duration - elapsed
        tail = 0.5 * cruise_speed * (remaining - ease / math.pi * math.sin(math.pi * remaining / ease))
        covered = total_distance - tail
    return min(1.0, max(0.0, covered / total_distance))


def plan_metrics(plan: list[Mapping[str, Any]]) -> dict[str, float]:
    max_speed = {"j10": 0.0, "j11": 0.0}
    max_accel = {"j10": 0.0, "j11": 0.0}
    previous_velocity = {"j10": 0.0, "j11": 0.0}
    for index in range(1, len(plan)):
        dt = float(plan[index]["time_sec"]) - float(plan[index - 1]["time_sec"])
        if dt <= 0.0:
            continue
        current = plan[index]["targets_deg"]
        previous = plan[index - 1]["targets_deg"]
        for joint in ("j10", "j11"):
            velocity = (float(current[joint]) - float(previous[joint])) / dt
            max_speed[joint] = max(max_speed[joint], abs(velocity))
            if index > 1:
                max_accel[joint] = max(max_accel[joint], abs(velocity - previous_velocity[joint]) / dt)
            previous_velocity[joint] = velocity
    return {
        "duration_sec": float(plan[-1]["time_sec"]) if plan else 0.0,
        "max_j10_speed_mm_s": max_speed["j10"],
        "max_j10_accel_mm_s2": max_accel["j10"],
        "max_j11_speed_deg_s": max_speed["j11"],
        "max_j11_accel_deg_s2": max_accel["j11"],
    }


def validate_playback_speed(
    curve: ShapePreservingHermiteCurve,
    *,
    start_mm: float,
    end_mm: float,
    speed_mm_s: float,
    max_j11_speed_deg_s: float = 12.0,
    max_j11_accel_deg_s2: float = 30.0,
    update_hz: float = 40.0,
    j10_limits: tuple[float, float] | None = None,
    j11_limits: tuple[float, float] | None = None,
) -> dict[str, Any]:
    requested = max(0.05, abs(float(speed_mm_s)))

    def evaluate(speed: float) -> tuple[bool, bool, dict[str, float]]:
        plan = build_playback_plan(curve, start_mm=start_mm, end_mm=end_mm, speed_mm_s=speed, update_hz=update_hz)
        metrics = plan_metrics(plan)
        within_limits = all(
            (j10_limits is None or j10_limits[0] <= float(frame["targets_deg"]["j10"]) <= j10_limits[1])
            and (j11_limits is None or j11_limits[0] <= float(frame["targets_deg"]["j11"]) <= j11_limits[1])
            for frame in plan
        )
        dynamic_ok = metrics["max_j11_speed_deg_s"] <= float(max_j11_speed_deg_s) + 1e-6 and metrics["max_j11_accel_deg_s2"] <= float(max_j11_accel_deg_s2) + 1e-6
        return within_limits and dynamic_ok, within_limits, metrics

    valid, within_limits, metrics = evaluate(requested)
    speed_exceeded = metrics["max_j11_speed_deg_s"] > float(max_j11_speed_deg_s) + 1e-6
    accel_exceeded = metrics["max_j11_accel_deg_s2"] > float(max_j11_accel_deg_s2) + 1e-6
    safe = requested
    if not within_limits:
        safe = 0.0
    elif not valid:
        low = 0.05
        high = requested
        low_valid, _, _ = evaluate(low)
        if not low_valid:
            safe = 0.0
        else:
            for _ in range(24):
                middle = (low + high) * 0.5
                middle_valid, _, _ = evaluate(middle)
                if middle_valid:
                    low = middle
                else:
                    high = middle
            safe = low
    return {
        "valid": valid,
        "requested_speed_mm_s": requested,
        "safe_max_speed_mm_s": round(safe, 3),
        "metrics": {key: round(value, 6) for key, value in metrics.items()},
        "message": _validation_message(valid, within_limits, speed_exceeded, accel_exceeded, safe),
    }


def _validation_message(valid: bool, within_limits: bool, speed_bad: bool, accel_bad: bool, safe_speed: float) -> str:
    if valid:
        return "轨迹速度检查通过。"
    if not within_limits:
        return "轨迹目标超出 J10/J11 关节限位，已禁止播放。"
    if accel_bad and not speed_bad:
        reason = "J11 加速度不平滑"
    elif speed_bad and not accel_bad:
        reason = "J11 速度超限"
    else:
        reason = "J11 速度和加速度超限"
    return f"{reason}；导轨最高安全速度约 {safe_speed:.3f} mm/s。"


def run_target_plan(
    plan: list[Mapping[str, Any]],
    *,
    stop_event: threading.Event,
    write_target: Callable[[dict[str, float]], Mapping[str, Any]],
    monotonic: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool] | None = None,
) -> dict[str, Any]:
    wait_fn = wait or stop_event.wait
    started = monotonic()
    index = 0
    writes = 0
    skipped = 0
    intervals: deque[float] = deque(maxlen=512)
    previous_write: float | None = None
    positive_intervals = [
        float(plan[position + 1].get("time_sec", 0.0)) - float(plan[position].get("time_sec", 0.0))
        for position in range(len(plan) - 1)
        if float(plan[position + 1].get("time_sec", 0.0)) > float(plan[position].get("time_sec", 0.0))
    ]
    nominal_interval = min(positive_intervals) if positive_intervals else 0.0
    late_tolerance = nominal_interval * 0.25
    min_write_spacing = nominal_interval * 0.5
    while index < len(plan) and not stop_event.is_set():
        deadline = started + float(plan[index].get("time_sec", 0.0))
        now = monotonic()
        if index + 1 < len(plan) and (
            deadline < now - late_tolerance
            or (previous_write is not None and deadline < previous_write + min_write_spacing)
        ):
            index += 1
            skipped += 1
            continue
        if wait_fn(max(0.0, deadline - monotonic())) or stop_event.is_set():
            break
        now = monotonic()
        if index + 1 < len(plan) and deadline < now - late_tolerance:
            index += 1
            skipped += 1
            continue
        if stop_event.is_set():
            break
        targets = {str(joint): float(value) for joint, value in dict(plan[index].get("targets_deg", {})).items()}
        response = write_target(targets)
        if not bool(response.get("ok", False)):
            raise RuntimeError(str(response.get("message") or response.get("error") or "主体锁定位置流写入失败。"))
        started += max(0.0, float(response.get("pause_sec", 0.0)))
        write_at = monotonic()
        if previous_write is not None:
            intervals.append(write_at - previous_write)
        previous_write = write_at
        writes += 1
        index += 1
    ordered = sorted(intervals)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
    mean = sum(intervals) / len(intervals) if intervals else 0.0
    return {
        "write_count": writes,
        "skipped_tick_count": skipped,
        "stopped": stop_event.is_set(),
        "actual_update_hz": round(1.0 / mean, 3) if mean > 0 else 0.0,
        "mean_interval_ms": round(mean * 1000.0, 3),
        "p95_interval_ms": round(p95 * 1000.0, 3),
        "max_interval_ms": round(max(intervals) * 1000.0, 3) if intervals else 0.0,
    }
