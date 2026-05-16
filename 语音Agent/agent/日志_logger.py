"""阶段十运行日志。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .配置_config import config_base_dir, resolve_path


class AgentLogger:
    def __init__(self, config: dict[str, Any]):
        base_dir = config_base_dir(config)
        self.path = resolve_path("runtime/logs/agent_runtime.log", base_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, event: str, message: str, **extra: Any) -> None:
        payload = {
            "time": time.time(),
            "level": str(level),
            "event": str(event),
            "message": str(message),
            **extra,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def get_logger(config: dict[str, Any]) -> AgentLogger:
    return AgentLogger(config)

