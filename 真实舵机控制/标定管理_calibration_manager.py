"""标定文件读取、校验和报告。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from 角度映射_angle_mapper import JOINT_ORDER, MULTI_TURN_JOINTS, SINGLE_TURN_JOINTS, joint_label


SINGLE_TURN_REQUIRED_FIELDS = [
    "id",
    "模式",
    "zero_present_raw",
    "range_min",
    "range_max",
    "direction",
]

MULTI_TURN_REQUIRED_FIELDS = [
    "id",
    "模式",
    "home_present_raw",
    "phase",
    "direction",
]

GRIPPER_REQUIRED_FIELDS = [
    "id",
    "range_min",
    "range_max",
]


class CalibrationManager:
    """管理标定 JSON 文件。"""

    def __init__(self, calibration_path: str | Path, config: dict[str, Any] | None = None):
        self.path = Path(calibration_path)
        self.config = config or {}
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        """加载标定文件。"""

        if not self.path.exists():
            raise FileNotFoundError(f"没有找到标定文件：{self.path}")

        try:
            with self.path.open("r", encoding="utf-8") as 文件:
                data = json.load(文件)
        except json.JSONDecodeError as 错误:
            raise ValueError(f"标定文件 JSON 格式错误：{错误}") from 错误

        if not isinstance(data, dict):
            raise ValueError("标定文件最外层必须是 JSON 对象。")

        self.data = data
        return self.data

    def save(self) -> None:
        """保存标定文件。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as 文件:
            json.dump(self.data, 文件, ensure_ascii=False, indent=2)
            文件.write("\n")

    def get(self, joint_key: str) -> dict[str, Any]:
        """获取单个关节标定项。"""

        entry = self.data.get(joint_key)
        if not isinstance(entry, dict):
            raise KeyError(f"标定文件缺少 {joint_label(joint_key)}。")
        return entry

    def has(self, joint_key: str) -> bool:
        """判断是否存在某个标定项。"""

        return isinstance(self.data.get(joint_key), dict)

    def joint_report(self, joint_key: str) -> dict[str, Any]:
        """生成单个关节标定报告。"""

        entry = self.data.get(joint_key)
        if not isinstance(entry, dict):
            return {
                "show_name": joint_label(joint_key),
                "完整": False,
                "缺失字段": ["整个标定项"],
                "问题": [f"缺少 {joint_label(joint_key)} 标定项"],
            }

        if joint_key in MULTI_TURN_JOINTS:
            required = MULTI_TURN_REQUIRED_FIELDS
            expected_mode = "多圈"
        elif joint_key in SINGLE_TURN_JOINTS:
            required = SINGLE_TURN_REQUIRED_FIELDS
            expected_mode = "单圈"
        elif joint_key == "gripper":
            required = GRIPPER_REQUIRED_FIELDS
            expected_mode = None
        else:
            required = ["id"]
            expected_mode = None

        missing = [field for field in required if field not in entry]
        issues = []
        if missing:
            issues.append(f"缺少字段：{', '.join(missing)}")

        if expected_mode is not None and entry.get("模式") != expected_mode:
            issues.append(f"模式应为 {expected_mode}，当前是 {entry.get('模式')}")

        if joint_key in MULTI_TURN_JOINTS and int(entry.get("phase", -1)) != 28:
            issues.append(f"多圈 phase 应为 28，当前是 {entry.get('phase')}")

        if "range_min" in entry and "range_max" in entry:
            try:
                range_min = int(entry["range_min"])
                range_max = int(entry["range_max"])
                if joint_key in SINGLE_TURN_JOINTS and range_min == range_max:
                    issues.append("单圈关节 range_min/range_max 不能相等")
            except (TypeError, ValueError):
                issues.append("range_min/range_max 必须是整数")

        return {
            "show_name": entry.get("show_name", joint_label(joint_key)),
            "完整": not missing and not issues,
            "缺失字段": missing,
            "问题": issues,
        }

    def calibration_report(self) -> dict[str, Any]:
        """生成标定状态报告。"""

        joint_keys = self.get_joint_order()
        gripper_available = bool(self.config.get("transport", {}).get("gripper_available", True))
        check_keys = list(joint_keys)
        if gripper_available:
            check_keys.append("gripper")

        项目 = {joint_key: self.joint_report(joint_key) for joint_key in check_keys}
        允许真机移动 = all(report["完整"] for report in 项目.values())
        return {
            "标定文件": str(self.path),
            "允许真机移动": 允许真机移动,
            "项目": 项目,
        }

    def is_complete_for_real_move(self) -> bool:
        """真机移动所需标定是否完整。"""

        return bool(self.calibration_report()["允许真机移动"])

    def get_joint_order(self) -> list[str]:
        """读取固定关节顺序。"""

        return list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))


标定管理器 = CalibrationManager
