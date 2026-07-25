"""标定文件读取、校验和报告。"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from 真实路径工具_real_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 角度映射_angle_mapper import JOINT_ORDER, MULTI_TURN_JOINTS, SINGLE_TURN_JOINTS, joint_label
from 通用_io import atomic_write_json, read_json_object
from 机器人配置_profile_loader import SUPPORTED_VARIANTS, validate_robot_variant


CALIBRATION_FORMAT_VERSION = "momo-calibration-v1"

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

    def __init__(
        self,
        calibration_path: str | Path,
        config: dict[str, Any] | None = None,
        *,
        require_real_variant: bool | None = None,
    ):
        self.path = Path(calibration_path)
        self.config = config or {}
        self.require_real_variant = require_real_variant
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        """加载标定文件。"""

        if not self.path.exists():
            self.data = {}
            if self.require_real_variant is True:
                self.require_exact_variant()
            return self.data

        try:
            data = read_json_object(self.path)
        except JSONDecodeError as 错误:
            raise ValueError(f"标定文件 JSON 格式错误：{错误}") from 错误
        except ValueError as 错误:
            raise ValueError("标定文件最外层必须是 JSON 对象。") from 错误

        self.data = data
        self._validate_loaded_variant_for_runtime()
        return self.data

    def reload(self) -> dict[str, Any]:
        """重新加载标定文件。"""

        return self.load()

    def save(self) -> None:
        """保存标定文件。"""

        report = self.variant_report()
        if not report["允许保存"]:
            raise ValueError(report["问题"])
        meta = self.data["_meta"]
        format_version = meta.get("format_version")
        if format_version not in (None, CALIBRATION_FORMAT_VERSION):
            raise ValueError(
                f"标定 format_version={format_version!r} 不受支持，"
                f"当前只支持 {CALIBRATION_FORMAT_VERSION}。"
            )
        meta["format_version"] = CALIBRATION_FORMAT_VERSION
        if not isinstance(meta.get("generated_at_unix_s"), (int, float)):
            meta["generated_at_unix_s"] = time.time()
        if not isinstance(meta.get("generated_at_utc"), str) or not meta["generated_at_utc"]:
            meta["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        atomic_write_json(self.path, self.data)

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

        integer_fields = {
            "id",
            "zero_present_raw",
            "home_present_raw",
            "range_min",
            "range_max",
        }
        for field in required:
            if field not in entry or field not in integer_fields:
                continue
            try:
                int(entry[field])
            except (TypeError, ValueError):
                issues.append(f"{field} 必须是整数，当前是 {entry[field]!r}")

        if "direction" in entry:
            try:
                direction = int(entry["direction"])
            except (TypeError, ValueError):
                issues.append(f"direction 必须是 -1 或 1，当前是 {entry['direction']!r}")
            else:
                if direction not in (-1, 1):
                    issues.append(f"direction 必须是 -1 或 1，当前是 {entry['direction']!r}")

        if joint_key in MULTI_TURN_JOINTS:
            try:
                phase = int(entry.get("phase"))
            except (TypeError, ValueError):
                issues.append(f"phase 必须是整数 28，当前是 {entry.get('phase')!r}")
            else:
                if phase != 28:
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
        variant = self.variant_report()
        meta = self.data.get("_meta", {})
        meta_gripper_disabled = isinstance(meta, dict) and meta.get("gripper_available") is False
        gripper_available = bool(self.config.get("transport", {}).get("gripper_available", True)) and not meta_gripper_disabled
        check_keys = list(joint_keys)
        if gripper_available:
            check_keys.append("gripper")

        项目 = {joint_key: self.joint_report(joint_key) for joint_key in check_keys}
        允许真机移动 = bool(variant["允许真机"]) and all(report["完整"] for report in 项目.values())
        if not self.path.exists():
            允许真机移动 = False
        return {
            "标定文件": str(self.path),
            "是否存在": self.path.exists(),
            "标定说明": self.data.get("说明", self.data.get("_meta", {}).get("notes", {})),
            "_meta": self.data.get("_meta", {}),
            "机械版本": variant,
            "允许真机移动": 允许真机移动,
            "项目": 项目,
        }

    def variant_report(self) -> dict[str, Any]:
        """报告配置与标定的机械版本关系，不把预览伪装成可用真机标定。"""

        expected_value = self.config.get("robot", {}).get("variant")
        expected = expected_value if isinstance(expected_value, str) else ""
        meta = self.data.get("_meta", {})
        actual_value = meta.get("robot_variant") if isinstance(meta, dict) else None
        actual = actual_value if isinstance(actual_value, str) else ""
        template = bool(meta.get("template", False)) if isinstance(meta, dict) else False
        expected_known = expected in SUPPORTED_VARIANTS
        actual_known = actual in SUPPORTED_VARIANTS
        exact_variant = expected_known and actual_known and actual == expected
        matches = exact_variant and not template

        if not expected_known:
            problem = f"robot.variant 必须精确为 V1 或 V2，当前值：{expected_value!r}，禁止真实移动或保存标定。"
            status = "unknown_active_variant"
        elif template:
            problem = f"标定文件是 {actual or '未知版本'} 模板，模板永远不能用于真实移动或覆盖真实标定。"
            status = "template"
        elif not actual:
            problem = f"标定文件缺少 robot_variant，真实配置要求 {expected}，禁止真实移动。"
            status = "missing"
        elif not actual_known:
            problem = f"标定文件包含未知 robot_variant={actual!r}，仅支持 V1/V2，禁止真实移动。"
            status = "unknown_calibration_variant"
        elif actual != expected:
            problem = f"标定机械版本不匹配：当前标定为 {actual}，真实配置要求 {expected}，禁止真实移动。"
            status = "mismatch"
        else:
            problem = ""
            status = "exact"
        dry_run = bool(self.config.get("transport", {}).get("dry_run", True))
        return {
            "配置版本": expected,
            "标定版本": actual,
            "匹配": matches,
            "问题": problem,
            "状态": status,
            "模板": template,
            "允许预览": dry_run,
            "允许真机": matches,
            "当前模式允许真实执行": matches and not dry_run,
            "允许保存": matches,
        }

    def _validate_loaded_variant_for_runtime(self) -> None:
        """真实模式加载即拒绝错误版本；dry-run 只保留为明确的预览数据。"""

        require_real = self.require_real_variant
        if require_real is False:
            return
        if require_real is None and bool(self.config.get("transport", {}).get("dry_run", True)):
            return
        self.require_exact_variant()

    def require_exact_variant(self) -> dict[str, Any]:
        """强制要求已加载标定与 active profile 精确匹配且不是模板。"""

        validate_robot_variant(self.config.get("robot", {}).get("variant"))
        report = self.variant_report()
        if not report["允许真机"]:
            raise ValueError(report["问题"])
        return report

    def require_complete_for_hardware(self, joint_keys: list[str] | None = None) -> None:
        """在任何硬件 I/O 前要求版本精确且目标标定字段有效。"""

        self.require_exact_variant()
        keys = joint_keys if joint_keys is not None else self.get_joint_order()
        if joint_keys is None:
            meta = self.data.get("_meta", {})
            meta_disables_gripper = isinstance(meta, dict) and meta.get("gripper_available") is False
            if bool(self.config.get("transport", {}).get("gripper_available", True)) and not meta_disables_gripper:
                keys = [*keys, "gripper"]
        invalid = []
        for joint_key in keys:
            report = self.joint_report(joint_key)
            if not report["完整"]:
                details = report["问题"] or report["缺失字段"]
                invalid.append(f"{report['show_name']} ({joint_key})：{'; '.join(details)}")
        if invalid:
            raise ValueError("标定字段不完整或无效，禁止硬件 I/O。" + "；".join(invalid))

    def is_complete_for_real_move(self) -> bool:
        """真机移动所需标定是否完整。"""

        return bool(self.calibration_report()["允许真机移动"])

    def get_joint_order(self) -> list[str]:
        """读取固定关节顺序。"""

        return list(self.config.get("robot", {}).get("joint_order", JOINT_ORDER))


标定管理器 = CalibrationManager
