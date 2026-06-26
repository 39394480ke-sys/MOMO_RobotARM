"""AI 对话页面。"""

from __future__ import annotations

import html
from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget

from gui_app.结果格式化_result_format import result_data, result_message


class AIChatPage(QWidget):
    ask_requested = pyqtSignal(str)
    voice_turn_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, agent_config: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.agent_config = agent_config or {}
        self.busy = False
        self._build_ui()
        self._connect_signals()
        self.set_agent_config(agent_config)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        self.title_label = QLabel("AI 对话")
        self.title_label.setObjectName("PanelTitle")
        self.status_label = QLabel("Agent 配置加载中...")
        self.status_label.setObjectName("StatusPill")
        self.status_label.setWordWrap(True)
        header_row.addWidget(self.title_label)
        header_row.addStretch(1)
        header_row.addWidget(self.status_label, 2)

        self.chat_text = QTextEdit()
        self.chat_text.setObjectName("AIChatText")
        self.chat_text.setReadOnly(True)
        self.chat_text.setMinimumHeight(360)

        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setObjectName("AIChatInput")
        self.input_field.setPlaceholderText("输入要问机械臂助手的话")
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("PrimaryButton")
        self.voice_button = QPushButton("语音一轮")
        self.reset_button = QPushButton("重置会话")
        self.stop_button = QPushButton("停止机械臂")
        self.stop_button.setObjectName("DangerButton")
        input_row.addWidget(self.input_field, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.voice_button)
        input_row.addWidget(self.reset_button)
        input_row.addWidget(self.stop_button)

        self.result_label = QLabel("文本发送默认不播报；语音一轮按 Agent 配置执行 STT/TTS。")
        self.result_label.setObjectName("StatusPill")
        self.result_label.setWordWrap(True)

        layout.addLayout(header_row)
        layout.addWidget(self.chat_text, 1)
        layout.addLayout(input_row)
        layout.addWidget(self.result_label)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._send_clicked)
        self.input_field.returnPressed.connect(self._send_clicked)
        self.voice_button.clicked.connect(self.voice_turn_requested.emit)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)

    def set_agent_config(self, config: dict[str, Any] | None) -> None:
        self.agent_config = config or {}
        if not self.agent_config:
            self.status_label.setText("Agent 配置未加载。")
            self.append_system("Agent 配置未加载，请检查 语音Agent/Agent配置.yaml。")
            return
        agent = self.agent_config.get("agent", {})
        backend = str(agent.get("backend", "openai_compatible"))
        model = str(self.agent_config.get("openai_compatible", {}).get("model", "未配置模型"))
        api_base = str(self.agent_config.get("openai_compatible", {}).get("api_base", "未配置 API"))
        robot_api = str(self.agent_config.get("robot_api", {}).get("base_url", "未配置 Web API"))
        stt = str(self.agent_config.get("stt", {}).get("url", "未配置 STT"))
        tts_enabled = "开启" if bool(self.agent_config.get("tts", {}).get("enabled", True)) else "关闭"
        self.status_label.setText(f"Agent: {backend} | 模型: {model} | API: {api_base} | Web: {robot_api} | STT: {stt} | TTS: {tts_enabled}")

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.send_button.setEnabled(not busy)
        self.voice_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        self.input_field.setEnabled(not busy)
        if message:
            self.result_label.setText(message)

    def show_result(self, result: dict[str, Any]) -> None:
        data = result_data(result)
        message = result_message(result, "完成。")
        reply = str(data.get("reply") or message or "")
        if result.get("ok"):
            self.append_ai(reply or "已完成。")
        else:
            self.append_error(message)
        session_id = str(data.get("session_id") or "")
        suffix = f" 会话: {session_id}" if session_id else ""
        self.result_label.setText(message + suffix)

    def append_user(self, text: str) -> None:
        self._append_line("我", text, "#1769aa")

    def append_ai(self, text: str) -> None:
        self._append_line("AI", text, "#34d399")

    def append_system(self, text: str) -> None:
        self._append_line("SYSTEM", text, "#93c5fd")

    def append_error(self, text: str) -> None:
        self._append_line("ERROR", text, "#f87171")

    def _send_clicked(self) -> None:
        text = self.input_field.text().strip()
        if not text or self.busy:
            return
        self.input_field.clear()
        self.append_user(text)
        self.ask_requested.emit(text)

    def _append_line(self, role: str, text: str, color: str) -> None:
        escaped_role = html.escape(role)
        escaped_text = html.escape(text).replace("\n", "<br>")
        self.chat_text.append(
            f"<p style='margin:8px 0; line-height:1.55;'>"
            f"<span style='color:{color}; font-weight:800;'>[{escaped_role}]</span> "
            f"<span style='color:#e5e7eb;'>{escaped_text}</span></p>"
        )
        self.chat_text.moveCursor(QTextCursor.End)
        self.chat_text.ensureCursorVisible()
