"""阶段四标定文件检查。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import read_json_object  # noqa: E402


REQUIRED_FIELDS = {
    "j10": ["home_present_raw", "phase"],
    "j11": ["home_present_raw", "phase"],
    "j12": ["home_present_raw", "phase"],
    "j13": ["home_present_raw", "phase"],
    "j14": ["zero_present_raw", "range_min", "range_max"],
    "j15": ["home_present_raw", "phase"],
    "gripper": ["range_min", "range_max"],
}


class CalibrationChecker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        path = config.get("hardware", {}).get("calibration_path", "../真实舵机控制/标定文件.json")
        self.path = resolve_path(path, self.base_dir)

    def check(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "path": str(self.path),
            "exists": self.path.exists(),
            "joints": {},
            "errors": [],
            "real_mode_allowed": False,
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
        result["ok"] = all_ok
        result["real_mode_allowed"] = all_ok
        return result

    def _required_fields_for(self, calibration: dict[str, Any]) -> dict[str, list[str]]:
        required = dict(REQUIRED_FIELDS)
        meta = calibration.get("_meta", {}) if isinstance(calibration.get("_meta"), dict) else {}
        if meta.get("gripper_available") is False and "gripper" not in calibration:
            required.pop("gripper", None)
        return required
