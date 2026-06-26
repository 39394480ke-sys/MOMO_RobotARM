"""Web 会话状态持久化。

这里保存的是 Web API 的 session 状态，不是舵机 raw 状态。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import atomic_write_json, read_json_object_or_default  # noqa: E402


class SessionStateManager:
    """读写 runtime/state/session_state.json。"""

    def __init__(self, path: str | Path, default_mode: str = "dry_run"):
        self.path = Path(path)
        self.default_mode = default_mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_or_default()
        self.save()

    def get(self) -> dict[str, Any]:
        return dict(self.state)

    def update(self, **changes: Any) -> dict[str, Any]:
        self.state.update(changes)
        self.state["updated_at"] = time.time()
        self.save()
        return self.get()

    def mark_connected(self, mode: str) -> dict[str, Any]:
        return self.update(
            session_id=self.state.get("session_id") or str(uuid.uuid4()),
            mode=mode,
            connected=True,
            connected_at=time.time(),
            disconnected_at=None,
        )

    def mark_disconnected(self) -> dict[str, Any]:
        return self.update(connected=False, disconnected_at=time.time())

    def save(self) -> None:
        atomic_write_json(self.path, self.state)

    def _load_or_default(self) -> dict[str, Any]:
        if self.path.exists():
            data = read_json_object_or_default(self.path)
            if data:
                if not data.get("session_id"):
                    data["session_id"] = str(uuid.uuid4())
                data.setdefault("mode", self.default_mode)
                data.setdefault("connected", False)
                if not data.get("created_at"):
                    data["created_at"] = time.time()
                if not data.get("updated_at"):
                    data["updated_at"] = time.time()
                # 服务重启后不自动认为真实硬件仍连接。
                data["connected"] = False
                return data
        now = time.time()
        return {
            "session_id": str(uuid.uuid4()),
            "mode": self.default_mode,
            "connected": False,
            "created_at": now,
            "updated_at": now,
            "connected_at": None,
            "disconnected_at": None,
        }
