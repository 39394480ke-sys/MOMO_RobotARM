"""OpenClaw backend 预留客户端。"""

from __future__ import annotations

from typing import Any

from .Agent客户端_agent_client import AgentReply
from .会话管理_session_manager import SessionManager


class OpenClawAgentClient:
    def __init__(self, config: dict[str, Any], force_new_session: bool = False):
        self.config = config
        self.session_manager = SessionManager(config)
        self.session = self.session_manager.load_session(force_new=force_new_session)

    def ask(self, message: str) -> AgentReply:
        return AgentReply(
            text="OpenClaw backend 预留接口尚未启用。当前版本请使用 openai_compatible；OpenClaw 接入时仍只能通过工具桥接调用阶段八 API。",
            session_id=self.session["session_id"],
            raw_payload={"backend": "openclaw", "enabled": self.config.get("openclaw", {}).get("enabled", False)},
        )

    def close(self) -> None:
        self.session_manager.save_session(self.session)

    def reset_session(self) -> None:
        self.session = self.session_manager.reset_session()

