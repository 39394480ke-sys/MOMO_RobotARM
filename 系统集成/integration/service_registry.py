"""服务注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path


@dataclass(slots=True)
class ServiceDefinition:
    name: str
    enabled: bool
    command: str
    cwd: Path
    pid_file: Path
    log_file: Path
    health_url: str


class ServiceRegistry:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        self._services = self._load_services()

    def _load_services(self) -> dict[str, ServiceDefinition]:
        services: dict[str, ServiceDefinition] = {}
        for key, item in self.config.get("services", {}).items():
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or key)
            services[name] = ServiceDefinition(
                name=name,
                enabled=bool(item.get("enabled", False)),
                command=str(item.get("command", "")),
                cwd=resolve_path(item.get("cwd", "."), self.base_dir),
                pid_file=self.base_dir / "runtime" / "pids" / f"{name}.pid",
                log_file=resolve_path(item.get("log_file", f"runtime/logs/{name}.log"), self.base_dir),
                health_url=str(item.get("health_url", "")),
            )
        return services

    def get(self, service_name: str) -> ServiceDefinition:
        try:
            return self._services[service_name]
        except KeyError as exc:
            raise KeyError(f"未知服务：{service_name}") from exc

    def all(self, only_enabled: bool = False) -> list[ServiceDefinition]:
        values = list(self._services.values())
        if only_enabled:
            values = [service for service in values if service.enabled]
        return values

    def names(self, only_enabled: bool = False) -> list[str]:
        return [service.name for service in self.all(only_enabled=only_enabled)]

