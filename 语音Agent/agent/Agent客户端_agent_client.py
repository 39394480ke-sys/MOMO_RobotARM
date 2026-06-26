"""Agent 客户端统一协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentReply:
    text: str
    session_id: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


class AgentClient(Protocol):
    def ask(self, message: str) -> AgentReply:
        ...

    def close(self) -> None:
        ...

    def reset_session(self) -> None:
        ...


def create_agent_client(config: dict[str, Any], force_new_session: bool = False, tool_bridge: Any | None = None) -> AgentClient:
    backend = str(config.get("agent", {}).get("backend", "openai_compatible")).lower()
    if backend == "openai_compatible":
        from .OpenAI兼容客户端_openai_client import OpenAICompatibleAgentClient

        return OpenAICompatibleAgentClient(config, force_new_session=force_new_session, tool_bridge=tool_bridge)
    if backend == "nanobot":
        from .Nanobot客户端_nanobot_client import NanobotAgentClient

        return NanobotAgentClient(config, force_new_session=force_new_session)
    if backend == "openclaw":
        from .OpenClaw客户端_openclaw_client import OpenClawAgentClient

        return OpenClawAgentClient(config, force_new_session=force_new_session)
    raise ValueError(f"未知 Agent backend：{backend}")
