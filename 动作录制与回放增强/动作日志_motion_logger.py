"""阶段六动作执行日志。

日志采用 JSONL，每行一个事件，便于后续 GUI / Web / Agent 直接读取。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class MotionLogger:
    """写入动作录制与回放运行日志。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **payload: Any) -> None:
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False)
            file.write("\n")


动作日志 = MotionLogger
