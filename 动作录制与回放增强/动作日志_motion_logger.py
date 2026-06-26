"""阶段六动作执行日志。

日志采用 JSONL，每行一个事件，便于后续 GUI / Web / Agent 直接读取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from 动作路径工具_motion_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import log_event_json_line  # noqa: E402


class MotionLogger:
    """写入动作录制与回放运行日志。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **payload: Any) -> None:
        log_event_json_line(self.log_path, event, time_style="local_string", **payload)


动作日志 = MotionLogger
