"""依赖检查。"""

from __future__ import annotations

import importlib
from typing import Any

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import check_python_packages  # noqa: E402


class DependencyChecker:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def check_required(self) -> dict[str, bool]:
        return self._check_many(self.config.get("dependencies", {}).get("required", []))

    def check_optional(self) -> dict[str, bool]:
        return self._check_many(self.config.get("dependencies", {}).get("optional", []))

    def check_real_hardware_dependencies(self) -> dict[str, bool]:
        backend = str(self.config.get("transport", {}).get("driver_backend", "sdk")).strip().lower()
        names = ["feetech-servo-sdk", "pyserial"]
        if backend in {"lerobot", "legacy"}:
            names.insert(0, "lerobot")
        result = self._check_many(names)
        if backend in {"lerobot", "legacy"}:
            result["lerobot.motors.feetech"] = self._can_import_lerobot_feetech()
        else:
            result["scservo_sdk"] = self._can_import("scservo_sdk")
        return result

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
        return check_python_packages(names)

    @staticmethod
    def _can_import_lerobot_feetech() -> bool:
        return DependencyChecker._can_import("lerobot.motors.feetech")

    @staticmethod
    def _can_import(module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
        except Exception:
            return False
        return True
