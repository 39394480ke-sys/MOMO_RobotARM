"""日志页面。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogPage(QWidget):
    refresh_requested = pyqtSignal()

    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self.log_path = Path(log_path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.title_label = QLabel("实时日志")
        self.title_label.setObjectName("PanelTitle")
        self.path_label = QLineEdit(str(self.log_path))
        self.path_label.setObjectName("PathLabel")
        self.path_label.setReadOnly(True)
        self.text = QTextEdit()
        self.text.setObjectName("LogText")
        self.text.setReadOnly(True)
        self.refresh_button = QPushButton("手动刷新")
        self.clear_button = QPushButton("清空视窗")
        self.open_button = QPushButton("追加路径")
        for button in (self.refresh_button, self.clear_button, self.open_button):
            button.setObjectName("TinyButton")
        button_row = QHBoxLayout()
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.open_button)
        layout.addWidget(self.title_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.text, 1)
        layout.addLayout(button_row)
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(self.text.clear)
        self.open_button.clicked.connect(lambda: self._append_html_line("PATH", f"日志文件路径：{self.log_path}"))
        self.refresh()

    def refresh(self) -> None:
        if not self.log_path.exists():
            self.text.setHtml("<span style='color:#94a3b8;'>暂无日志。</span>")
            self._scroll_to_bottom()
            return
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.text.setHtml("<br>".join(self._format_log_line(line) for line in lines[-300:]))
        self._scroll_to_bottom()

    def append_result(self, result: dict) -> None:
        message = str(result.get("message", result))
        level = "INFO" if result.get("ok", True) else "ERROR"
        self._append_html_line(level, message)
        self._scroll_to_bottom()

    def _append_html_line(self, level: str, message: str, time_text: str = "") -> None:
        self.text.append(self._format_parts(time_text, level, message))

    def _format_log_line(self, line: str) -> str:
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                time_text = self._short_time(str(payload.get("time", "")))
                level = str(payload.get("level", "info")).upper()
                message = str(payload.get("message", payload.get("event", line)))
                return self._format_parts(time_text, level, message)
        except Exception:
            pass
        return self._format_parts("", "INFO", line)

    def _format_parts(self, time_text: str, level: str, message: str) -> str:
        level = level.upper()
        color = {"INFO": "#50fa7b", "WARN": "#fbbf24", "WARNING": "#fbbf24", "ERROR": "#f87171"}.get(level, "#93c5fd")
        time_html = f"<span style='color:#94a3b8;'>[{html.escape(time_text)}]</span> " if time_text else ""
        return (
            f"{time_html}<span style='color:{color}; font-weight:700;'>[{html.escape(level)}]</span> "
            f"<span style='color:#e5e7eb;'>{html.escape(message)}</span>"
        )

    def _short_time(self, text: str) -> str:
        if " " in text:
            text = text.split(" ", 1)[1]
        if "T" in text:
            text = text.split("T", 1)[1]
        return text[:8] if text else "--:--:--"

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self._set_scrollbar_to_bottom)

    def _set_scrollbar_to_bottom(self) -> None:
        scrollbar = self.text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
