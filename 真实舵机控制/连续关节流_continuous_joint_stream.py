"""共享的连续关节位置流调度器。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ContinuousJogStats:
    configured_update_hz: float
    tick_count: int
    write_count: int
    skipped_tick_count: int
    actual_update_hz: float
    mean_interval_ms: float
    p95_interval_ms: float
    max_interval_ms: float
    duration_s: float
    last_target_deg: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_continuous_joint_stream(
    *,
    start_deg: float,
    direction: int,
    speed_units_s: float,
    update_hz: float,
    max_step: float,
    stop_event: Any,
    write_target: Callable[[float], bool],
    on_progress: Callable[[ContinuousJogStats], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ContinuousJogStats:
    """按绝对时间点发送固定增量目标，超时帧直接跳过。"""

    hz = float(update_hz)
    speed = abs(float(speed_units_s))
    step_limit = abs(float(max_step))
    if hz <= 0:
        raise ValueError("update_hz 必须大于 0。")
    if speed <= 0:
        raise ValueError("speed_units_s 必须大于 0。")
    if step_limit <= 0:
        raise ValueError("max_step 必须大于 0。")

    signed_direction = 1 if int(direction) > 0 else -1
    period_s = 1.0 / hz
    delta_per_tick = signed_direction * min(step_limit, speed / hz)
    started_at = monotonic()
    next_deadline = started_at + period_s
    target_deg = float(start_deg)
    completed_times: list[float] = []
    tick_count = 0
    write_count = 0
    skipped_tick_count = 0

    while not stop_event.is_set():
        now = monotonic()
        while next_deadline < now:
            skipped_tick_count += 1
            next_deadline += period_s
        wait_s = next_deadline - now
        if wait_s > 0 and stop_event.wait(wait_s):
            break

        target_deg += delta_per_tick
        wrote = bool(write_target(target_deg))
        completed_times.append(monotonic())
        tick_count += 1
        if wrote:
            write_count += 1

        next_deadline += period_s
        if on_progress is not None:
            on_progress(
                _build_stats(
                    configured_update_hz=hz,
                    tick_count=tick_count,
                    write_count=write_count,
                    skipped_tick_count=skipped_tick_count,
                    started_at=started_at,
                    completed_times=completed_times,
                    last_target_deg=target_deg,
                )
            )

    return _build_stats(
        configured_update_hz=hz,
        tick_count=tick_count,
        write_count=write_count,
        skipped_tick_count=skipped_tick_count,
        started_at=started_at,
        completed_times=completed_times,
        last_target_deg=target_deg,
        ended_at=monotonic(),
    )


def _build_stats(
    *,
    configured_update_hz: float,
    tick_count: int,
    write_count: int,
    skipped_tick_count: int,
    started_at: float,
    completed_times: list[float],
    last_target_deg: float,
    ended_at: float | None = None,
) -> ContinuousJogStats:
    intervals = [later - earlier for earlier, later in zip(completed_times, completed_times[1:])]
    mean_interval_s = sum(intervals) / len(intervals) if intervals else 0.0
    sorted_intervals = sorted(intervals)
    p95_index = max(0, int(len(sorted_intervals) * 0.95 + 0.999999) - 1)
    p95_interval_s = sorted_intervals[p95_index] if sorted_intervals else 0.0
    actual_update_hz = 1.0 / mean_interval_s if mean_interval_s > 0 else 0.0
    end = float(ended_at if ended_at is not None else (completed_times[-1] if completed_times else started_at))
    return ContinuousJogStats(
        configured_update_hz=float(configured_update_hz),
        tick_count=int(tick_count),
        write_count=int(write_count),
        skipped_tick_count=int(skipped_tick_count),
        actual_update_hz=float(actual_update_hz),
        mean_interval_ms=float(mean_interval_s * 1000.0),
        p95_interval_ms=float(p95_interval_s * 1000.0),
        max_interval_ms=float(max(intervals, default=0.0) * 1000.0),
        duration_s=max(0.0, end - float(started_at)),
        last_target_deg=float(last_target_deg),
    )
