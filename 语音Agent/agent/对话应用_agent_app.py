"""语音 Agent 应用层。"""

from __future__ import annotations

import json
import time
from typing import Any

from .Agent客户端_agent_client import AgentReply, create_agent_client
from .会话管理_session_manager import SessionManager
from .工具定义_robot_tools import tool_names
from .工具桥接_tool_bridge import RobotToolBridge
from .日志_logger import get_logger
from .语音输入_audio_input import record_until_enter
from .语音播报_tts import speak_text
from .语音转文字_stt import transcribe_audio


STOP_WORDS = {"停", "停止", "别动", "急停", "马上停", "不要动"}
STATUS_HINTS = {"状态", "连接", "模式", "当前位置", "当前角度", "关节角度", "在干嘛", "咋样"}


class AgentApp:
    def __init__(self, config: dict[str, Any], force_new_session: bool = False, tool_bridge: Any | None = None):
        self.config = config
        self.logger = get_logger(config)
        self.tool_bridge = tool_bridge or RobotToolBridge(config)
        self.client = create_agent_client(config, force_new_session=force_new_session, tool_bridge=self.tool_bridge)
        self.session_manager = SessionManager(config)

    def ask_text(self, text: str, speak: bool = True) -> AgentReply:
        content = str(text or "").strip()
        if not content:
            reply = AgentReply(text="请输入要询问的内容。", session_id="", raw_payload={})
        elif content in STOP_WORDS:
            result = self.tool_bridge.execute("stop_robot", {})
            message = "已发送停止命令。" if result.get("ok") else str(result.get("error", "停止命令失败。"))
            reply = AgentReply(text=message, session_id="", raw_payload={"tool_result": result})
        elif any(hint in content for hint in STATUS_HINTS):
            result = self.tool_bridge.execute("get_robot_state", {})
            reply = AgentReply(text=_format_robot_state(result), session_id="", raw_payload={"tool_result": result})
        else:
            self.logger.log("info", "ask", content)
            reply = self.client.ask(content)
        print(reply.text)
        if speak:
            self.say(reply.text)
        return reply

    def run_voice_turn(self, speak: bool = True) -> AgentReply:
        try:
            wav_bytes = record_until_enter(self.config)
            text = transcribe_audio(wav_bytes, self.config)
        except Exception as exc:
            message = str(exc)
            print(message)
            return AgentReply(text=message, session_id="", raw_payload={"error": message})
        print(f"识别结果：{text}")
        return self.ask_text(text, speak=speak)

    def say(self, text: str) -> None:
        speak_text(str(text), self.config)

    def warmup(self) -> AgentReply:
        prompt = str(self.config.get("agent", {}).get("warmup_prompt", "请只回复“就绪”。"))
        return self.ask_text(prompt, speak=False)

    def reset_session(self) -> None:
        self.client.reset_session()
        print("会话已重置。")

    def run_shell(self) -> None:
        print("机械臂语音助手 shell。输入 /quit 退出，/tools 查看工具。")
        while True:
            try:
                text = input("arm> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text.startswith("/"):
                if not self._handle_shell_command(text):
                    break
                continue
            self.ask_text(text, speak=bool(self.config.get("tts", {}).get("enabled", True)))
        self.client.close()

    def run_listen_loop(self, warmup: bool = False, speak: bool = True) -> None:
        if warmup:
            self.warmup()
        print("listen 模式已启动。每轮按 Enter 开始录音，再按 Enter 停止。Ctrl+C 退出。")
        try:
            while True:
                self.run_voice_turn(speak=speak)
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nlisten 模式已退出。")
        finally:
            self.client.close()

    def _handle_shell_command(self, text: str) -> bool:
        if text in {"/quit", "/exit"}:
            return False
        if text == "/voice":
            self.run_voice_turn(speak=bool(self.config.get("tts", {}).get("enabled", True)))
            return True
        if text.startswith("/say "):
            self.say(text.removeprefix("/say ").strip())
            return True
        if text == "/session":
            session = self.session_manager.load_session()
            print(json.dumps(session, ensure_ascii=False, indent=2))
            return True
        if text == "/warmup":
            self.warmup()
            return True
        if text == "/reset":
            self.reset_session()
            return True
        if text == "/tools":
            print("可用工具：" + "、".join(tool_names()))
            return True
        print("未知命令。可用命令：/voice /say 文本 /session /warmup /reset /tools /quit")
        return True


def _format_robot_state(tool_result: dict[str, Any]) -> str:
    if not tool_result.get("ok"):
        return str(tool_result.get("error") or "查询机械臂状态失败。")
    data = tool_result.get("result", {})
    if isinstance(data, dict) and data.get("data") and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        return "查询成功，但状态格式无法识别。"
    mode = str(data.get("mode") or data.get("模式") or "未知")
    connected = bool(data.get("connected", data.get("已连接", False)))
    joints = data.get("joints_deg") or data.get("关节角度") or {}
    action = data.get("action") or {}
    action_state = action.get("state", "未知") if isinstance(action, dict) else "未知"
    tcp = data.get("tcp_pose") or {}
    parts = [f"当前模式：{mode}。", f"连接状态：{'已连接' if connected else '未连接'}。"]
    if isinstance(joints, dict) and joints:
        joint_text = "，".join(f"{key}={float(value):.2f}" for key, value in joints.items() if isinstance(value, (int, float)))
        if joint_text:
            parts.append(f"关节：{joint_text}。")
    if isinstance(tcp, dict) and tcp.get("xyz"):
        xyz = tcp.get("xyz")
        if isinstance(xyz, list) and len(xyz) >= 3:
            parts.append(f"TCP xyz：{float(xyz[0]):.3f}, {float(xyz[1]):.3f}, {float(xyz[2]):.3f}。")
    if action_state != "未知":
        parts.append(f"动作状态：{action_state}。")
    return " ".join(parts)
