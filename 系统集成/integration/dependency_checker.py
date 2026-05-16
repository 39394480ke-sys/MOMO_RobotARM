"""依赖检查。"""

from __future__ import annotations

import importlib.util
from typing import Any


IMPORT_NAMES = {
    "pyyaml": ["yaml"],
    "opencv-contrib-python": ["cv2"],
    "feetech-servo-sdk": ["feetech_servo_sdk", "feetech", "scservo_sdk"],
    "pyserial": ["serial"],
}


class DependencyChecker:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def check_required(self) -> dict[str, bool]:
        return self._check_many(self.config.get("dependencies", {}).get("required", []))

    def check_optional(self) -> dict[str, bool]:
        return self._check_many(self.config.get("dependencies", {}).get("optional", []))

    def check_real_hardware_dependencies(self) -> dict[str, bool]:
        names = ["lerobot", "feetech-servo-sdk", "pyserial"]
        return self._check_many(names)

    def check_all(self) -> dict[str, Any]:
        required = self.check_required()
        optional = self.check_optional()
        real_deps = self.check_real_hardware_dependencies()
        return {
            "required": required,
            "optional": optional,
            "real_hardware": real_deps,
            "required_ok": all(required.values()),
            "real_mode_ready": all(real_deps.values()),
        }

    def _check_many(self, names: list[str]) -> dict[str, bool]:
        return {name: self._available(name) for name in names}

    @staticmethod
    def _available(package_name: str) -> bool:
        import_names = IMPORT_NAMES.get(package_name, [package_name])
        return any(importlib.util.find_spec(name) is not None for name in import_names)

