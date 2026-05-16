"""阶段四标定文件检查。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path


REQUIRED_FIELDS = {
    "shoulder_pan": ["zero_present_raw", "range_min", "range_max"],
    "shoulder_lift": ["home_present_raw", "phase"],
    "elbow_flex": ["home_present_raw", "phase"],
    "wrist_flex": ["zero_present_raw", "range_min", "range_max"],
    "wrist_roll": ["home_present_raw", "phase"],
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
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            result["errors"].append(f"标定文件无法解析：{exc}")
            return result
        all_ok = True
        for joint, fields in REQUIRED_FIELDS.items():
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

