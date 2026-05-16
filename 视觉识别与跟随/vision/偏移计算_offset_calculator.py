"""计算目标中心相对期望中心的像素偏移和归一化偏移。"""

from __future__ import annotations

from typing import Any


class OffsetCalculator:
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config or {})
        self.center_x_norm = float(self.config.get("center_x_norm", 0.5))
        self.center_y_norm = float(self.config.get("center_y_norm", 0.42))
        self.dead_zone_x = float(self.config.get("dead_zone_x", 0.02))
        self.dead_zone_y = float(self.config.get("dead_zone_y", 0.025))

    def calculate(self, frame_width: int, frame_height: int, target_center: list[float] | tuple[float, float] | None) -> dict[str, Any]:
        if not target_center:
            return self.empty(frame_width, frame_height)

        width = max(1.0, float(frame_width))
        height = max(1.0, float(frame_height))
        target_cx = float(target_center[0])
        target_cy = float(target_center[1])
        desired_cx = width * self.center_x_norm
        desired_cy = height * self.center_y_norm

        dx = target_cx - desired_cx
        dy = target_cy - desired_cy
        ndx = dx / (width / 2.0)
        ndy = dy / (height / 2.0)
        direction = self._direction(ndx, ndy)

        return {
            "valid": True,
            "dx": round(dx, 3),
            "dy": round(dy, 3),
            "ndx": round(ndx, 6),
            "ndy": round(ndy, 6),
            "desired_center": [round(desired_cx, 3), round(desired_cy, 3)],
            "target_center": [round(target_cx, 3), round(target_cy, 3)],
            "horizontal": direction["horizontal"],
            "vertical": direction["vertical"],
            "combined": direction["combined"],
            "in_dead_zone": direction["in_dead_zone"],
        }

    def empty(self, frame_width: int = 0, frame_height: int = 0) -> dict[str, Any]:
        desired_cx = float(frame_width) * self.center_x_norm if frame_width else 0.0
        desired_cy = float(frame_height) * self.center_y_norm if frame_height else 0.0
        return {
            "valid": False,
            "dx": 0.0,
            "dy": 0.0,
            "ndx": 0.0,
            "ndy": 0.0,
            "desired_center": [round(desired_cx, 3), round(desired_cy, 3)],
            "target_center": None,
            "horizontal": "center",
            "vertical": "center",
            "combined": "center",
            "in_dead_zone": True,
        }

    def _direction(self, ndx: float, ndy: float) -> dict[str, Any]:
        horizontal = "center"
        vertical = "center"
        if ndx > self.dead_zone_x:
            horizontal = "right"
        elif ndx < -self.dead_zone_x:
            horizontal = "left"
        if ndy > self.dead_zone_y:
            vertical = "down"
        elif ndy < -self.dead_zone_y:
            vertical = "up"

        if horizontal == "center" and vertical == "center":
            combined = "center"
        elif horizontal == "center":
            combined = vertical
        elif vertical == "center":
            combined = horizontal
        else:
            combined = f"{horizontal}_{vertical}"

        return {
            "horizontal": horizontal,
            "vertical": vertical,
            "combined": combined,
            "in_dead_zone": horizontal == "center" and vertical == "center",
        }
