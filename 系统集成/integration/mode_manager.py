"""统一运行模式管理。"""

from __future__ import annotations

from typing import Any

from .runtime_state import RuntimeState
from .safety_guard import SafetyGuard


VALID_MODES = {"sim", "dry_run", "real"}


class ModeManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.runtime_state = RuntimeState(config)

    def get_mode(self) -> str:
        state = self.runtime_state.load()
        mode = str(state.get("mode") or self.config.get("project", {}).get("default_mode", "dry_run"))
        return mode if mode in VALID_MODES else "dry_run"

    def set_mode(self, mode: str, confirm_text: str = "", require_web_api_for_real: bool = True) -> dict[str, Any]:
        normalized = self._normalize_mode(mode)
        if normalized == "real":
            allowed = SafetyGuard(self.config).check_real_mode_allowed(confirm_text, require_web_api=require_web_api_for_real)
            if not allowed.get("ok"):
                self.runtime_state.set_error("; ".join(allowed.get("errors", [])))
                return {"ok": False, "mode": self.get_mode(), "errors": allowed.get("errors", []), "safety": allowed}
        self.runtime_state.set_mode(normalized)
        return {"ok": True, "mode": normalized, "errors": []}

    def is_real_mode_allowed(self) -> dict[str, Any]:
        return SafetyGuard(self.config).check_real_mode_allowed(confirm_text="", require_web_api=True)

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = str(mode or "dry_run").strip()
        if normalized not in VALID_MODES:
            raise ValueError(f"模式只能是 sim / dry_run / real，当前：{mode}")
        return normalized

