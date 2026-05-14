"""阶段六动作插值器。

真实机械臂不能从一个姿态瞬间跳到另一个姿态。本模块提供独立分段能力，
即使底层控制器自己也有插值，阶段六仍可在大角度动作前先拆小步。
"""

from __future__ import annotations

import math
from typing import Mapping


class MotionInterpolator:
    """关节和夹爪插值工具。"""

    def interpolate_joints(
        self,
        start_targets: Mapping[str, float],
        end_targets: Mapping[str, float],
        duration_sec: float,
        update_hz: float,
    ) -> list[dict[str, float]]:
        steps = max(1, int(math.ceil(float(duration_sec) * float(update_hz))))
        start = {key: float(value) for key, value in start_targets.items()}
        end = {key: float(value) for key, value in end_targets.items()}
        keys = list(end.keys())
        frames: list[dict[str, float]] = []
        for step in range(1, steps + 1):
            ratio = step / steps
            frames.append({
                key: start.get(key, end[key]) + (end[key] - start.get(key, end[key])) * ratio
                for key in keys
            })
        return frames

    def split_large_step(
        self,
        start_targets: Mapping[str, float],
        end_targets: Mapping[str, float],
        max_step_deg: float,
    ) -> list[dict[str, float]]:
        start = {key: float(value) for key, value in start_targets.items()}
        end = {key: float(value) for key, value in end_targets.items()}
        max_delta = 0.0
        for key, end_value in end.items():
            max_delta = max(max_delta, abs(end_value - start.get(key, end_value)))
        steps = max(1, int(math.ceil(max_delta / max(0.001, float(max_step_deg)))))
        frames: list[dict[str, float]] = []
        for step in range(1, steps + 1):
            ratio = step / steps
            frames.append({
                key: start.get(key, end[key]) + (end[key] - start.get(key, end[key])) * ratio
                for key in end
            })
        return frames

    def interpolate_gripper(self, start_value: float | None, end_value: float | None, steps: int) -> list[float | None]:
        if end_value is None:
            return [None for _ in range(max(1, int(steps)))]
        if start_value is None:
            start_value = end_value
        count = max(1, int(steps))
        return [
            float(start_value) + (float(end_value) - float(start_value)) * (index / count)
            for index in range(1, count + 1)
        ]


动作插值器 = MotionInterpolator
