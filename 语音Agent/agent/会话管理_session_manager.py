"""Agent 会话缓存。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .path_utils import ensure_project_root_on_path
from .配置_config import config_base_dir, resolve_path

ensure_project_root_on_path()

from 通用_io import atomic_write_json, read_json_object_or_default  # noqa: E402


class SessionManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = config_base_dir(config)
        self.path = resolve_path("runtime/sessions/agent_session_state.json", self.base_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_session(self, force_new: bool = False) -> dict[str, Any]:
        if force_new:
            return self.reset_session()
        if self.path.exists():
            data = read_json_object_or_default(self.path)
            if isinstance(data.get("messages"), list):
                if not data.get("session_id"):
                    data["session_id"] = self._new_session_id()
                if not data.get("backend"):
                    data["backend"] = self.config.get("agent", {}).get("backend", "openai_compatible")
                return data
        data = self._empty_session()
        self.save_session(data)
        return data

    def save_session(self, session: dict[str, Any]) -> None:
        session["updated_at"] = time.time()
        atomic_write_json(self.path, session)

    def reset_session(self) -> dict[str, Any]:
        session = self._empty_session()
        self.save_session(session)
        return session

    def trim_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        max_turns = int(self.config.get("agent", {}).get("max_turns", 20))
        limit = max(2, max_turns * 2)
        if len(messages) <= limit:
            return messages
        return messages[-limit:]

    def _empty_session(self) -> dict[str, Any]:
        return {
            "backend": self.config.get("agent", {}).get("backend", "openai_compatible"),
            "session_id": self._new_session_id(),
            "messages": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    @staticmethod
    def _new_session_id() -> str:
        return f"agent-{uuid.uuid4().hex[:12]}"


def load_session(config: dict[str, Any], force_new: bool = False) -> dict[str, Any]:
    return SessionManager(config).load_session(force_new=force_new)


def save_session(config: dict[str, Any], session: dict[str, Any]) -> None:
    SessionManager(config).save_session(session)


def reset_session(config: dict[str, Any]) -> dict[str, Any]:
    return SessionManager(config).reset_session()


def trim_history(config: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return SessionManager(config).trim_history(messages)
