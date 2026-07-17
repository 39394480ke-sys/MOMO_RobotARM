"""OpenAI-compatible Agent backend。"""

from __future__ import annotations

import json
import re
from typing import Any

from .path_utils import PROJECT_ROOT, ensure_project_root_on_path

ensure_project_root_on_path()

from .Agent客户端_agent_client import AgentReply
from .会话管理_session_manager import SessionManager
from .工具定义_robot_tools import robot_tool_specs
from .工具桥接_tool_bridge import RobotToolBridge
from .配置_config import config_base_dir, resolve_path
from 通用_http import HTTPJsonError, request_json_object
from 通用_io import read_text, resolve_secret_value


class OpenAICompatibleAgentClient:
    def __init__(self, config: dict[str, Any], force_new_session: bool = False, tool_bridge: Any | None = None):
        self.config = config
        self.agent_cfg = config.get("agent", {})
        self.backend_cfg = config.get("openai_compatible", {})
        self.session_manager = SessionManager(config)
        self.session = self.session_manager.load_session(force_new=force_new_session)
        self.tool_bridge = tool_bridge or RobotToolBridge(config)
        self.system_prompt = self._load_system_prompt()

    def ask(self, message: str) -> AgentReply:
        user_text = str(message).strip()
        if not user_text:
            return AgentReply(text="请输入要询问的内容。", session_id=self.session["session_id"], raw_payload={})
        self.session["messages"].append({"role": "user", "content": user_text})
        self.session["messages"] = self.session_manager.trim_history(self.session["messages"])

        try:
            reply = self._run_chat_with_tools()
        except HTTPJsonError as exc:
            text = f"Agent backend 不可用，请检查 OpenAI-compatible 服务是否启动：{exc}"
            reply = AgentReply(text=text, session_id=self.session["session_id"], raw_payload={"error": str(exc)})
        except Exception as exc:
            text = f"Agent 处理失败：{exc}"
            reply = AgentReply(text=text, session_id=self.session["session_id"], raw_payload={"error": str(exc)})

        self.session["messages"].append({"role": "assistant", "content": reply.text})
        self.session["messages"] = self.session_manager.trim_history(self.session["messages"])
        self.session_manager.save_session(self.session)
        return reply

    def interpret_robot_intent(self, message: str) -> dict[str, Any]:
        """Use the model as a semantic parser; this method never executes tools."""

        user_text = str(message or "").strip()
        if not user_text:
            return {"kind": "clarify", "tool_name": "", "arguments": {}, "missing": ["request"], "reply": "请说明想让机械臂做什么。", "confidence": 1.0}
        prompt = """你是机械臂的语义指令解析器。只判断用户想让系统做什么，不要回答“我能不能控制硬件”，不要执行工具。
只输出一个 JSON 对象，字段如下：
kind: command | clarify | conversation
tool_name: get_robot_state | stop_robot | stop_face_follow | set_gripper | move_joint | run_robot_behavior | play_action | start_face_follow | ""
arguments: object
missing: array of missing or ambiguous field names
reply: kind=clarify 时用中文简短说明缺少什么，其他情况为空字符串
confidence: 0 到 1

领域映射：J10=底盘导轨（毫米），J11=底座旋转，J12=肩部抬升，J13=肘部弯曲，J14=腕部俯仰，J15=腕部旋转。J11-J15 的单位是度。

规则：
- 理解语义而不是匹配固定文字。礼貌问句“能否……”“可以……吗”只要包含明确的操作对象和具体数值，就是 command，不是能力咨询。
- move_joint 必须有 joint_name（j10..j15）、mode（relative|absolute）和数字 value。正转/正向/顺时针是正的相对值，反转/反向/逆时针是负的相对值。
- 绝不得猜测数值、关节、方向、单位、动作名或绝对/相对模式。缺少或有歧义时必须 clarify，missing 列出所有缺少字段。
- J12-J15 不接受绝对目标，必须追问相对方向和变化量。
- 打开夹爪是 set_gripper {"open_ratio":1.0}，闭合夹爪是 {"open_ratio":0.0}。
- 回 Home 是 run_robot_behavior {"name":"home"}。播放动作必须有确切动作库名称。
- 启动视觉跟随是 start_face_follow；停止机械臂或停止跟随是立即降低风险的指令。
- 只询问原理、能力、状态解释或普通聊天，且没有要求执行具体动作时，才是 conversation。
- 模糊指令绝不得变成 command。
"""
        payload = {
            "model": self.backend_cfg.get("model"),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "能否控制 j10 运动到 50mm 的位置"},
                {"role": "assistant", "content": '{"kind":"command","tool_name":"move_joint","arguments":{"joint_name":"j10","mode":"absolute","value":50},"missing":[],"reply":"","confidence":1.0}'},
                {"role": "user", "content": "j12 正转度"},
                {"role": "assistant", "content": '{"kind":"clarify","tool_name":"move_joint","arguments":{"joint_name":"j12","mode":"relative"},"missing":["value"],"reply":"请说明 J12 要正转多少度。","confidence":1.0}'},
                {"role": "user", "content": "J12 是做什么的？"},
                {"role": "assistant", "content": '{"kind":"conversation","tool_name":"","arguments":{},"missing":[],"reply":"","confidence":1.0}'},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        try:
            data = self._post_chat(payload)
        except HTTPJsonError:
            payload.pop("response_format", None)
            data = self._post_chat(payload)
        content = str(_choice_message(data).get("content") or "")
        return _normalize_robot_intent(_parse_json_object(content))

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
                pending = result.get("result", {}).get("pending_action") if isinstance(result.get("result"), dict) else None
                if isinstance(pending, dict):
                    summary = pending.get("summary", {}) if isinstance(pending.get("summary"), dict) else {}
                    return AgentReply(
                        text=str(summary.get("confirmation_text") or "动作已生成，请查看具体内容并确认执行。"),
                        session_id=self.session["session_id"],
                        raw_payload={"pending_action": pending, "tool_result": result},
                    )
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
        api_key = resolve_secret_value(
            self.backend_cfg.get("api_key", ""),
            default_env_names=("OPENAI_COMPATIBLE_API_KEY", "SILICONFLOW_API_KEY"),
            env_paths=(PROJECT_ROOT / "系统集成" / "环境变量.env", PROJECT_ROOT / ".env"),
        )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return request_json_object(
            f"{api_base}/chat/completions",
            method="POST",
            headers=headers,
            payload=payload,
            timeout=float(self.agent_cfg.get("timeout_sec", 60)),
        )

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
        return read_text(path)


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
        return _extract_loose_tool_calls(content)
    calls = data.get("tool_calls")
    if not isinstance(calls, list):
        loose_calls, loose_reply = _extract_loose_tool_calls(content)
        return loose_calls, str(data.get("reply") or loose_reply or "")
    parsed: list[dict[str, Any]] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        if name:
            parsed.append({"name": name, "arguments": arguments})
    return parsed, str(data.get("reply") or "")


def _extract_loose_tool_calls(content: str) -> tuple[list[dict[str, Any]], str]:
    """Best-effort parser for small/free models that emit malformed JSON."""
    reply_match = re.search(r'"reply"\s*:\s*"([^"]*)"', content)
    reply = reply_match.group(1).strip() if reply_match else ""
    parsed: list[dict[str, Any]] = []
    name_matches = list(re.finditer(r'"name"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"', content))
    for index, match in enumerate(name_matches):
        name = match.group(1).strip()
        tail = content[match.end() :]
        args = {}
        args_match = re.search(r'"arguments"\s*:\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', tail, flags=re.S)
        if args_match:
            args = _parse_arguments(args_match.group(1))
        parsed.append({"id": f"loose-tool-{index}", "name": name, "arguments": args})
    return parsed, reply


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


def _normalize_robot_intent(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "kind": "clarify",
            "tool_name": "",
            "arguments": {},
            "missing": ["clear_request"],
            "reply": "我没有准确理解这条指令。请说明要操作的关节或功能，以及具体方向和数值。",
            "confidence": 0.0,
        }
    kind = str(value.get("kind") or "conversation").strip().lower()
    if kind not in {"command", "clarify", "conversation"}:
        kind = "clarify"
    arguments = value.get("arguments") if isinstance(value.get("arguments"), dict) else {}
    missing = value.get("missing") if isinstance(value.get("missing"), list) else []
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "kind": kind,
        "tool_name": str(value.get("tool_name") or "").strip(),
        "arguments": dict(arguments),
        "missing": [str(item) for item in missing if str(item).strip()],
        "reply": str(value.get("reply") or "").strip(),
        "confidence": confidence,
    }
