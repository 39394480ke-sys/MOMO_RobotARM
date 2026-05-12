"""真实舵机控制安全检查。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from 角度映射_angle_mapper import (
    MULTI_TURN_ABSOLUTE_RAW_LIMIT,
    MULTI_TURN_JOINTS,
    SINGLE_TURN_JOINTS,
    joint_label,
    wrap_single_turn_raw,
)
from 标定管理_calibration_manager import CalibrationManager


@dataclass(frozen=True)
class SafetyResult:
    成功: bool
    消息: str


class SafetyChecker:
    """集中处理角度、raw、标定和 dry-run 安全逻辑。"""

    def __init__(self, config: dict[str, Any], calibration_manager: CalibrationManager):
        self.config = config
        self.calibration_manager = calibration_manager

    def is_dry_run(self) -> bool:
        """当前是否 dry-run。"""

        return bool(self.config.get("transport", {}).get("dry_run", True))

    def startup_warning(self) -> str:
        """真实模式启动安全提示。"""

        if self.is_dry_run():
            return "当前为 dry-run：不会真实写入舵机。"
        return (
            "警告：当前为真实模式，会控制真实机械臂。请确认机械臂周围安全、"
            "电源稳定、串口和标定正确，并随时准备断电。"
        )

    def check_calibration_for_move(self) -> SafetyResult:
        """检查真机移动是否具备完整标定。"""

        if self.is_dry_run():
            return SafetyResult(True, "dry-run 模式允许映射检查，不会真实移动。")

        report = self.calibration_manager.calibration_report()
        if report["允许真机移动"]:
            return SafetyResult(True, "标定完整，允许真实移动。")

        bad = [
            f"{item['show_name']}：{'; '.join(item['问题'] or item['缺失字段'])}"
            for item in report["项目"].values()
            if not item["完整"]
        ]
        return SafetyResult(False, "标定不完整，禁止真实移动。" + (" " + "；".join(bad) if bad else ""))

    def check_joint_angle(self, joint_key: str, target_deg: float, joint_config: dict[str, Any]) -> SafetyResult:
        """检查逻辑关节角度是否在配置范围内。"""

        min_deg = float(joint_config.get("最小角度", -180))
        max_deg = float(joint_config.get("最大角度", 180))
        if target_deg < min_deg or target_deg > max_deg:
            return SafetyResult(
                False,
                f"{joint_label(joint_key)} 目标角度 {target_deg:.2f} 超出范围 [{min_deg:.2f}, {max_deg:.2f}]。",
            )
        return SafetyResult(True, f"{joint_label(joint_key)} 角度合法。")

    def check_all_joint_angles(
        self,
        target_deg_by_joint: dict[str, float],
        joint_config_by_key: dict[str, dict[str, Any]],
    ) -> SafetyResult:
        """检查一组逻辑角度。"""

        for joint_key, target_deg in target_deg_by_joint.items():
            if joint_key not in joint_config_by_key:
                return SafetyResult(False, f"未知关节 key：{joint_key}")
            result = self.check_joint_angle(joint_key, float(target_deg), joint_config_by_key[joint_key])
            if not result.成功:
                return result
        return SafetyResult(True, "所有逻辑角度合法。")

    def check_goal_raw(self, joint_key: str, goal_raw: int, calibration_entry: dict[str, Any]) -> SafetyResult:
        """检查目标 raw 是否安全。"""

        if joint_key in MULTI_TURN_JOINTS:
            if abs(int(goal_raw)) > MULTI_TURN_ABSOLUTE_RAW_LIMIT:
                return SafetyResult(
                    False,
                    f"{joint_label(joint_key)} 多圈目标 raw={goal_raw} 超出 "
                    f"[-{MULTI_TURN_ABSOLUTE_RAW_LIMIT}, {MULTI_TURN_ABSOLUTE_RAW_LIMIT}]。",
                )

            range_min = int(calibration_entry.get("range_min", 0))
            range_max = int(calibration_entry.get("range_max", 0))
            if not (range_min == 0 and range_max == 0):
                if not _raw_in_range(goal_raw, range_min, range_max):
                    return SafetyResult(
                        False,
                        f"{joint_label(joint_key)} 多圈目标 raw={goal_raw} 超出标定范围 [{range_min}, {range_max}]。",
                    )
            return SafetyResult(True, f"{joint_label(joint_key)} 多圈 raw 合法。")

        if joint_key in SINGLE_TURN_JOINTS or joint_key == "gripper":
            wrapped_raw = wrap_single_turn_raw(goal_raw)
            range_min = int(calibration_entry["range_min"])
            range_max = int(calibration_entry["range_max"])
            if not _raw_in_range(wrapped_raw, range_min, range_max):
                return SafetyResult(
                    False,
                    f"{joint_label(joint_key)} 单圈目标 raw={wrapped_raw} 超出标定范围 [{range_min}, {range_max}]。",
                )
            return SafetyResult(True, f"{joint_label(joint_key)} 单圈 raw 合法。")

        return SafetyResult(False, f"未知关节 key：{joint_key}")

    def check_goal_raws(
        self,
        goal_raw_by_joint: dict[str, int],
        calibration_by_joint: dict[str, dict[str, Any]],
    ) -> SafetyResult:
        """检查一组目标 raw。"""

        for joint_key, goal_raw in goal_raw_by_joint.items():
            if joint_key not in calibration_by_joint:
                return SafetyResult(False, f"{joint_label(joint_key)} 缺少标定，禁止移动。")
            result = self.check_goal_raw(joint_key, int(goal_raw), calibration_by_joint[joint_key])
            if not result.成功:
                return result
        return SafetyResult(True, "所有目标 raw 合法。")


def _raw_in_range(raw: int, range_min: int, range_max: int) -> bool:
    """支持普通范围，也支持跨 0 的单圈范围。"""

    if range_min <= range_max:
        return range_min <= raw <= range_max
    return raw >= range_min or raw <= range_max


安全检查器 = SafetyChecker
