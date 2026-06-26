"""Web API 日志。

后端日志写入 runtime/logs/web_api.log，使用 JSON 行，方便之后 Agent 读取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import log_json_line  # noqa: E402


class JsonLineLogger:
    """很薄的一层 JSONL 日志封装。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, event: str, message: str, **extra: Any) -> None:
        log_json_line(self.log_path, level, event, message, time_style="local_string", **extra)
