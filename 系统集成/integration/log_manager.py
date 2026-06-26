"""统一 JSONL 日志。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import log_json_line, tail_lines  # noqa: E402


class LogManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        self.system_log = resolve_path(config.get("logging", {}).get("system_log", "runtime/logs/system.log"), self.base_dir)
        self.system_log.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, event: str, message: str, **fields: Any) -> None:
        log_json_line(self.system_log, level, event, message, time_style="iso", include_ts=True, **fields)

    def log_info(self, event: str, message: str, **fields: Any) -> None:
        self._write("info", event, message, **fields)

    def log_warning(self, event: str, message: str, **fields: Any) -> None:
        self._write("warning", event, message, **fields)

    def log_error(self, event: str, message: str, **fields: Any) -> None:
        self._write("error", event, message, **fields)

    def tail_log(self, service: str = "system", lines: int = 100) -> list[str]:
        path = self.system_log
        if service != "system":
            service_cfg = self.config.get("services", {}).get(service, {})
            log_file = service_cfg.get("log_file")
            if log_file:
                path = resolve_path(log_file, self.base_dir)
        if not path.exists():
            return []
        return tail_lines(path, lines, errors="replace")
