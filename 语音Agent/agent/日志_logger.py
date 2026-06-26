"""阶段十运行日志。"""

from __future__ import annotations

from typing import Any

from .path_utils import ensure_project_root_on_path
from .配置_config import config_base_dir, resolve_path

ensure_project_root_on_path()

from 通用_io import log_json_line  # noqa: E402


class AgentLogger:
    def __init__(self, config: dict[str, Any]):
        base_dir = config_base_dir(config)
        self.path = resolve_path("runtime/logs/agent_runtime.log", base_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, event: str, message: str, **extra: Any) -> None:
        log_json_line(self.path, level, event, message, time_style="epoch", **extra)


def get_logger(config: dict[str, Any]) -> AgentLogger:
    return AgentLogger(config)
