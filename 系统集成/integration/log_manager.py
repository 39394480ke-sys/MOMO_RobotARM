"""统一 JSONL 日志。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config_loader import INTEGRATION_DIR, resolve_path


class LogManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()
        self.system_log = resolve_path(config.get("logging", {}).get("system_log", "runtime/logs/system.log"), self.base_dir)
        self.system_log.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, event: str, message: str, **fields: Any) -> None:
        item = {
            "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "ts": time.time(),
            "level": level,
            "event": event,
            "message": message,
        }
        item.update(fields)
        with self.system_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

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
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            content = fh.readlines()
        return [line.rstrip("\n") for line in content[-lines:]]

