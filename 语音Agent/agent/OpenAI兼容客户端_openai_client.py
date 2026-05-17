"""OpenAI-compatible Agent backend。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from .Agent客户端_agent_client import AgentReply
from .会话管理_session_manager import SessionManager
from .工具定义_robot_tools import robot_tool_specs
from .工具桥接_tool_bridge import RobotToolBridge
from .配置_config import config_base_dir, resolve_path


class OpenAICompatibleAgentClient:
    def __init__(self, config: dict[str, Any], force_new_session: bool = False):
        self.config = config
        self.agent_cfg = config.get("agent", {})
        self.backend_cfg = config.get("openai_compatible", {})
        self.session_manager = SessionManager(config)
        self.session = self.session_manager.load_session(force_new=force_new_session)
        self.tool_bridge = RobotToolBridge(config)
        self.system_prompt = self._load_system_prompt()

    def ask(self, message: str) -> AgentReply:
        user_text = str(message).strip()
        if not user_text:
            return AgentReply(text="请输入要询问的内容。", session_id=self.session["session_id"], raw_payload={})
        self.session["messages"].append({"role": "user", "content": user_text})
        self.session["messages"] = self.session_manager.trim_history(self.session["messages"])

        try:
            reply = self._run_chat_with_tools()
        except requests.RequestException as exc:
            text = f"Agent backend 不可用，请检查 OpenAI-compatible 服务是否启动：{exc}"
            reply = AgentReply(text=text, session_id=self.session["session_id"], raw_payload={"error": str(exc)})
        except Exception as exc:
            text = f"Agent 处理失败：{exc}"
            reply = AgentReply(text=text, session_id=self.session["session_id"], raw_payload={"error": str(exc)})

        self.session["messages"].append({"role": "assistant", "content": reply.text})
        self.session["messages"] = self.session_manager.trim_history(self.session["messages"])
        self.session_manager.save_session(self.session)
        return reply

    def close(self) -> None:
        self.session_manager.save_session(self.session)

    def reset_session(self) -> None:
        self.session = self.session_manager.reset_session()

    def _run_chat_with_tools(self) -> AgentReply:
        raw_messages = self._messages_for_request(self.session["messages"])
        tools = robot_tool_specs()
        max_iterations = int(self.config.get("nanobot", {}).get("max_tool_iterations", 12))
        last_payload: dict[str, Any] = {}

        for _ in range(max(1, max_iterations)):
            payload = self._chat_completion_payload(raw_messages, tools)
            data = self._post_chat(payload)
            last_payload = data
            message = _choice_message(data)
            content = str(message.get("content") or "")
            tool_calls = _extract_standard_tool_calls(message)
            json_calls, json_reply = _extract_json_tool_calls(content)
            if not tool_calls and json_calls:
                tool_calls = json_calls
                content = json_reply or content

            if not tool_calls:
                return AgentReply(text=content.strip() or "已完成。", session_id=self.session["session_id"], raw_payload=data)

            assistant_message = {"role": "assistant", "content": content or ""}
            if message.get("tool_calls"):
                assistant_message["tool_calls"] = message["tool_calls"]
            raw_messages.append(assistant_message)

            tool_summaries: list[str] = []
            for index, call in enumerate(tool_calls):
                name = str(call.get("name", "")).strip()
                arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                result = self.tool_bridge.execute(name, arguments)
                tool_summaries.append(f"{name}: {json.dumps(result, ensure_ascii=False)}")
                if not json_calls:
                    raw_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(call.get("id") or f"tool-{index}"),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            if json_calls:
                # JSON fallback 模式下，有些本地模型不接受 role=tool；追加普通文本观察更稳。
                raw_messages.append(
                    {
                        "role": "user",
                        "content": "工具结果：\n"
                        + "\n".join(tool_summaries)
                        + "\n请基于工具执行结果，用中文简短回复用户。必须说明工具是否成功，不能编造状态。",
                    }
                )
            else:
                raw_messages.append(
                    {
                        "role": "user",
                        "content": "请基于以上工具执行结果，用中文简短回复用户。必须说明工具是否成功，不能编造状态。",
                    }
                )

        return AgentReply(text="工具调用次数过多，已停止本轮对话。", session_id=self.session["session_id"], raw_payload=last_payload)

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_base = str(self.backend_cfg.get("api_base", "http://127.0.0.1:1234/v1")).rstrip("/")
        headers = {"Content-Type": "application/json"}
        api_key = str(self.backend_cfg.get("api_key", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.post(
            f"{api_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=float(self.agent_cfg.get("timeout_sec", 60)),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def _chat_completion_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.backend_cfg.get("model"),
            "messages": messages,
            "temperature": float(self.backend_cfg.get("temperature", 0.3)),
            "max_tokens": int(self.backend_cfg.get("max_tokens", 800)),
            "tools": tools,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _messages_for_request(self, session_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system = self.system_prompt + "\n\n如果需要调用工具，请优先使用 OpenAI tools；如果不支持，请输出 JSON：{\"reply\":\"...\",\"tool_calls\":[{\"name\":\"get_robot_state\",\"arguments\":{}}]}。"
        return [{"role": "system", "content": system}, *session_messages]

    def _load_system_prompt(self) -> str:
        path_value = str(self.agent_cfg.get("system_prompt_path", "prompts/system_prompt.md"))
        path = resolve_path(path_value, config_base_dir(self.config))
        if not path.exists():
            return "你是我的机械臂语音助手，只能通过安全工具控制机械臂。"
        return path.read_text(encoding="utf-8")


def _choice_message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                return message
            if isinstance(choice.get("text"), str):
                return {"content": choice["text"]}
    return {"content": ""}


def _extract_standard_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    parsed: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        arguments = _parse_arguments(function.get("arguments"))
        parsed.append({"id": call.get("id"), "name": name, "arguments": arguments})
    return parsed


def _extract_json_tool_calls(content: str) -> tuple[list[dict[str, Any]], str]:
    data = _parse_json_object(content)
    if not isinstance(data, dict):
        return [], ""
    calls = data.get("tool_calls")
    if not isinstance(calls, list):
        return [], str(data.get("reply") or "")
    parsed: list[dict[str, Any]] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        if name:
            parsed.append({"name": name, "arguments": arguments})
    return parsed, str(data.get("reply") or "")


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except Exception:
        pass
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None
