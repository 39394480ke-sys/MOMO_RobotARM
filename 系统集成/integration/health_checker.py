"""统一健康检查。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .calibration_checker import CalibrationChecker
from .config_loader import INTEGRATION_DIR
from .path_utils import ensure_project_root_on_path
from .process_manager import ProcessManager
from .runtime_state import RuntimeState
from .service_registry import ServiceRegistry

ensure_project_root_on_path()

from 通用_http import HTTPJsonError, request_json_object  # noqa: E402


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
            return True, request_json_object(url, timeout=timeout)
        except HTTPJsonError as exc:
            return False, exc.payload if exc.payload is not None else exc.text[:300]
        except Exception as exc:
            return False, str(exc)
