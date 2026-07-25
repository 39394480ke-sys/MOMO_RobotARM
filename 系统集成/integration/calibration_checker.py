"""阶段四标定文件检查。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import read_json_object  # noqa: E402
from 机器人配置_profile_loader import SUPPORTED_VARIANTS  # noqa: E402


REQUIRED_FIELDS = {
    "j10": ["home_present_raw", "phase"],
    "j11": ["home_present_raw", "phase"],
    "j12": ["home_present_raw", "phase"],
    "j13": ["home_present_raw", "phase"],
    "j14": ["home_present_raw", "phase"],
    "j15": ["home_present_raw", "phase"],
    "gripper": ["range_min", "range_max"],
}


class CalibrationChecker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        path = config.get("hardware", {}).get(
            "calibration_path",
            "../真实舵机控制/标定/current.local.json",
        )
        self.path = resolve_path(path, self.base_dir)

    def check(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "path": str(self.path),
            "exists": self.path.exists(),
            "joints": {},
            "errors": [],
            "real_mode_allowed": False,
            "robot_variant": self._active_variant(),
        }
        if not self.path.exists():
            result["errors"].append("标定文件不存在。")
            return result
        try:
            data = read_json_object(self.path)
        except Exception as exc:
            message = str(exc)
            if "不是 JSON 对象" in message:
                result["errors"].append("标定文件最外层必须是对象。")
            else:
                result["errors"].append(f"标定文件无法解析：{exc}")
            return result
        variant_ok = self._check_variant(data, result)
        required_fields = self._required_fields_for(data)
        all_ok = True
        for joint, fields in required_fields.items():
            item = data.get(joint)
            missing = []
            if not isinstance(item, dict):
                missing = fields[:]
            else:
                missing = [field for field in fields if field not in item]
            joint_ok = not missing
            if not joint_ok:
                all_ok = False
                result["errors"].append(f"{joint} 缺少字段：{', '.join(missing)}")
            result["joints"][joint] = {"ok": joint_ok, "missing": missing}
        result["ok"] = all_ok and variant_ok
        result["real_mode_allowed"] = all_ok and variant_ok
        return result

    def _active_variant(self) -> str:
        robot_variant = self.config.get("robot", {}).get("variant")
        hardware_variant = self.config.get("hardware", {}).get("robot_variant")
        return str(robot_variant or hardware_variant or "")

    def _check_variant(self, calibration: dict[str, Any], result: dict[str, Any]) -> bool:
        robot_variant = self.config.get("robot", {}).get("variant")
        hardware_variant = self.config.get("hardware", {}).get("robot_variant")
        expected = self._active_variant()
        if robot_variant and hardware_variant and robot_variant != hardware_variant:
            result["errors"].append(
                f"集成配置机械版本不一致：robot.variant={robot_variant}，"
                f"hardware.robot_variant={hardware_variant}。"
            )
            return False
        if expected not in SUPPORTED_VARIANTS:
            result["errors"].append(
                f"集成配置 robot_variant 必须精确为 V1 或 V2，当前值：{expected!r}。"
            )
            return False

        meta = calibration.get("_meta", {})
        if not isinstance(meta, dict):
            result["errors"].append("标定文件缺少 _meta 对象和 robot_variant。")
            return False
        actual = meta.get("robot_variant")
        if meta.get("template") is True:
            result["errors"].append("标定文件是示例模板，不能用于真实模式。")
            return False
        if not actual:
            result["errors"].append(f"标定文件缺少 robot_variant，真实配置要求 {expected}。")
            return False
        if actual not in SUPPORTED_VARIANTS:
            result["errors"].append(f"标定文件包含未知 robot_variant={actual!r}，仅支持 V1/V2。")
            return False
        if actual != expected:
            result["errors"].append(f"标定机械版本不匹配：当前标定为 {actual}，真实配置要求 {expected}。")
            return False
        return True

    def _required_fields_for(self, calibration: dict[str, Any]) -> dict[str, list[str]]:
        required = dict(REQUIRED_FIELDS)
        meta = calibration.get("_meta", {}) if isinstance(calibration.get("_meta"), dict) else {}
        if meta.get("gripper_available") is False and "gripper" not in calibration:
            required.pop("gripper", None)
        return required
