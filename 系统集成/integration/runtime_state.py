"""系统运行状态持久化。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import atomic_write_json, read_json_object_or_default  # noqa: E402


class RuntimeState:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        state_path = config.get("logging", {}).get("state_file", "runtime/state/system_state.json")
        self.path = resolve_path(state_path, self.base_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def default_state(self) -> dict[str, Any]:
        mode = self.config.get("project", {}).get("default_mode", "dry_run")
        return {
            "mode": mode,
            "started_at": "",
            "services": {},
            "last_health": {},
            "last_error": "",
            "updated_at": time.time(),
        }

    def load(self) -> dict[str, Any]:
        merged = self.default_state()
        data = read_json_object_or_default(self.path)
        merged.update(data)
        return merged

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = time.time()
        atomic_write_json(self.path, state)
        return state

    def update(self, **kwargs: Any) -> dict[str, Any]:
        state = self.load()
        state.update(kwargs)
        return self.save(state)

    def set_mode(self, mode: str) -> dict[str, Any]:
        return self.update(mode=mode)

    def update_service(self, service_name: str, **kwargs: Any) -> dict[str, Any]:
        state = self.load()
        services = state.setdefault("services", {})
        current = services.setdefault(service_name, {})
        current.update(kwargs)
        return self.save(state)

    def set_last_health(self, health: dict[str, Any]) -> dict[str, Any]:
        return self.update(last_health=health, last_error="; ".join(health.get("errors", [])))

    def set_error(self, message: str) -> dict[str, Any]:
        return self.update(last_error=message)
