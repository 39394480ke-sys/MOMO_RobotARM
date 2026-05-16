"""动作库页面。"""

from __future__ import annotations

import json
from collections.abc import Mapping

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QListWidget, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget


class ActionPage(QWidget):
    refresh_requested = pyqtSignal()
    play_requested = pyqtSignal(str)
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.list_widget = QListWidget()
        self.detail = QTextEdit()
        self.detail.setObjectName("DetailText")
        self.detail.setReadOnly(True)
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        self.refresh_button = QPushButton("刷新动作库")
        self.play_button = QPushButton("▶ 播放")
        self.play_button.setObjectName("PrimaryButton")
        self.pause_button = QPushButton("⏸ 暂停")
        self.resume_button = QPushButton("▶_ 继续")
        self.stop_button = QPushButton("⏹ 停止")
        self.stop_button.setObjectName("WarningButton")
        self.record_button = QPushButton("录制动作")
        self.record_button.setEnabled(False)
        self.record_button.setToolTip("请使用阶段六动作录制器完成录制。")
        self.teach_button = QPushButton("示教录制")
        self.teach_button.setEnabled(False)
        self.teach_button.setToolTip("示教录制暂未集成到 GUI。")
        self.delete_button = QPushButton("删除动作")
        self.delete_button.setObjectName("WarningButton")
        for button in (self.refresh_button, self.play_button, self.pause_button, self.resume_button, self.stop_button, self.record_button, self.teach_button, self.delete_button):
            button_layout.addWidget(button)
        button_layout.addStretch(1)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.detail, 2)
        layout.addLayout(button_layout)
        self._actions = {}
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.play_button.clicked.connect(lambda: self._emit_selected(self.play_requested))
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.delete_button.clicked.connect(self._confirm_delete)
        self.list_widget.currentTextChanged.connect(self._show_detail)

    def set_actions(self, actions: list[dict]) -> None:
        self._actions = {item["name"]: item.get("summary", {}) for item in actions}
        self.list_widget.clear()
        self.list_widget.addItems(sorted(self._actions.keys()))
        self._show_detail(self.list_widget.currentItem().text() if self.list_widget.currentItem() else "")

    def _show_detail(self, name: str) -> None:
        summary = self._actions.get(name, {})
        if not name:
            self.detail.setPlainText("请选择左侧动作。")
            return
        if not summary:
            self.detail.setPlainText(f"动作：{name}\n\n暂无动作摘要。")
            return
        self.detail.setPlainText(self._format_action_detail(name, summary))

    def _format_action_detail(self, name: str, summary: object) -> str:
        lines = [f"动作：{name}", ""]
        if isinstance(summary, Mapping):
            for label, key in (("帧数", "frame_count"), ("时长", "duration_sec"), ("来源", "source"), ("更新时间", "updated_at")):
                if key in summary:
                    lines.append(f"{label}: {summary.get(key)}")
            joints = summary.get("joints") or summary.get("joint_names")
            if isinstance(joints, (list, tuple)):
                lines.append(f"关节: {', '.join(str(item) for item in joints)}")
        if len(lines) <= 2:
            lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
        return "\n".join(lines)

    def _emit_selected(self, signal) -> None:
        item = self.list_widget.currentItem()
        if item:
            signal.emit(item.text())

    def _confirm_delete(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        reply = QMessageBox.question(self, "确认删除动作", f"确定删除动作“{item.text()}”？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(item.text())
