"""Web API 日志。

后端日志写入 runtime/logs/web_api.log，使用 JSON 行，方便之后 Agent 读取。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any


class JsonLineLogger:
    """很薄的一层 JSONL 日志封装。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"web_api.{self.log_path}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = logging.FileHandler(self.log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def log(self, level: str, event: str, message: str, **extra: Any) -> None:
        payload = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": str(level),
            "event": str(event),
            "message": str(message),
        }
        payload.update(extra)
        line = json.dumps(payload, ensure_ascii=False)
        if str(level).lower() in {"error", "exception"}:
            self._logger.error(line)
        elif str(level).lower() in {"warning", "warn"}:
            self._logger.warning(line)
        else:
            self._logger.info(line)
