"""视觉偏差到连续关节位置目标的纯控制逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from 控制桥接_common import FOLLOW_JOINT_AXES, normalize_joint_key


@dataclass(frozen=True)
class FollowControlFrame:
    targets_deg: dict[str, float]
    velocities_deg_s: dict[str, float]
    hold_reason: str


class ContinuousFollowPlanner:
    def __init__(self, config: Mapping[str, Any], initial_targets: Mapping[str, float]):
        self.config = dict(config)
        raw_joints = self.config.get("enabled_follow_joints") or ["j11", "j13"]
        self.joints = [normalize_joint_key(str(joint)) for joint in raw_joints]
        self.joints = [joint for joint in self.joints if joint in FOLLOW_JOINT_AXES]
        self.targets = {joint: float(initial_targets.get(joint, 0.0)) for joint in self.joints}
        self.velocities = {joint: 0.0 for joint in self.joints}
        self.active = {joint: False for joint in self.joints}

    def step(
        self,
        ndx: float,
        ndy: float,
        *,
        dt: float,
        hold_reason: str = "",
        manual_tracker: bool = False,
    ) -> FollowControlFrame:
        dt = max(0.0, min(0.1, float(dt)))
        if hold_reason:
            for joint in self.joints:
                self.velocities[joint] = 0.0
            return self._frame(hold_reason)

        for joint in self.joints:
            axis = FOLLOW_JOINT_AXES[joint]
            value = float(ndx if axis == "pan" else ndy)
            desired = self._desired_velocity(joint, axis, value, manual_tracker)
            accel = self._axis_value(axis, "accel_deg_s2", 30.0 if axis == "pan" else 25.0)
            max_change = accel * dt
            current = self.velocities[joint]
            change = max(-max_change, min(max_change, desired - current))
            velocity = current + change
            self.velocities[joint] = velocity
            self.targets[joint] += velocity * dt
        return self._frame("")

    def _desired_velocity(self, joint: str, axis: str, value: float, manual_tracker: bool) -> float:
        dead = self._axis_value(axis, "dead_zone_norm", 0.03 if axis == "pan" else 0.035)
        resume = self._axis_value(axis, "resume_zone_norm", 0.05 if axis == "pan" else 0.055)
        if manual_tracker:
            profile = self.config.get("manual_tracker_profile", {})
            if not isinstance(profile, Mapping):
                profile = {}
            dead = float(profile.get("dead_zone_norm", 0.06))
            resume = float(profile.get("resume_zone_norm", 0.10))
        magnitude = abs(value)
        if self.active[joint]:
            if magnitude <= dead:
                self.active[joint] = False
        elif magnitude >= resume:
            self.active[joint] = True
        if not self.active[joint]:
            return 0.0
        max_speed = max(
            0.0,
            float(self.config.get(f"max_{axis}_speed_deg_s", 12.0 if axis == "pan" else 10.0)),
        )
        gain = self._axis_value(axis, "velocity_gain_deg_s_per_norm", max_speed * 2.0)
        sign = float(self.config.get(f"{axis}_sign", 1.0))
        desired = value * gain * sign
        return max(-max_speed, min(max_speed, desired))

    def _axis_value(self, axis: str, suffix: str, default: float) -> float:
        return max(0.0, float(self.config.get(f"{axis}_{suffix}", default)))

    def _frame(self, hold_reason: str) -> FollowControlFrame:
        return FollowControlFrame(dict(self.targets), dict(self.velocities), hold_reason)
