"""统一健康检查。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .calibration_checker import CalibrationChecker
from .config_loader import INTEGRATION_DIR
from .process_manager import ProcessManager
from .runtime_state import RuntimeState
from .service_registry import ServiceRegistry


class HealthChecker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        self.registry = ServiceRegistry(config)
        self.process_manager = ProcessManager(config)
        self.runtime_state = RuntimeState(config)

    def check(self) -> dict[str, Any]:
        state = self.runtime_state.load()
        errors: list[str] = []
        services: dict[str, Any] = {}
        for service in self.registry.all():
            proc = self.process_manager.status_service(service.name)
            healthy = None
            health_data: Any = None
            if service.health_url and proc["running"]:
                ok, health_data = self._get_json(service.health_url)
                healthy = ok
                if not ok and service.enabled:
                    errors.append(f"{service.name} health 失败：{health_data}")
            elif service.enabled and service.health_url:
                healthy = False
                errors.append(f"{service.name} 未运行。")
            services[service.name] = {
                "enabled": service.enabled,
                "running": proc["running"],
                "healthy": healthy,
                "pid": proc["pid"],
                "health": health_data,
            }
        details = {
            "web_session": self._get_json("http://127.0.0.1:8010/api/v1/session/status")[1],
            "web_robot_state": self._get_json("http://127.0.0.1:8010/api/v1/robot/state")[1],
            "vision_latest": self._get_json("http://127.0.0.1:8000/latest")[1],
            "agent_config_exists": (self.base_dir / "../语音Agent/Agent配置.yaml").resolve().exists(),
            "gui_config_exists": (self.base_dir / "../GUI图形界面/GUI配置.yaml").resolve().exists(),
            "calibration": CalibrationChecker(self.config).check(),
        }
        ok = not errors
        result = {
            "ok": ok,
            "services": services,
            "mode": state.get("mode", self.config.get("project", {}).get("default_mode", "dry_run")),
            "errors": errors,
            "details": details,
        }
        self.runtime_state.set_last_health(result)
        return result

    @staticmethod
    def _get_json(url: str, timeout: float = 2.0) -> tuple[bool, Any]:
        try:
            import requests

            response = requests.get(url, timeout=timeout)
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()
            else:
                try:
                    data = response.json()
                except Exception:
                    data = response.text[:300]
            return 200 <= response.status_code < 300, data
        except Exception as exc:
            return False, str(exc)

