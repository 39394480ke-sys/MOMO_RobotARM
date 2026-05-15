"""动作库页面。"""

from __future__ import annotations

import json

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QListWidget, QPushButton, QTextEdit, QVBoxLayout, QWidget


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
        self.list_widget = QListWidget()
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        button_layout = QVBoxLayout()
        self.refresh_button = QPushButton("刷新动作库")
        self.play_button = QPushButton("播放动作")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")
        self.record_button = QPushButton("录制动作")
        self.teach_button = QPushButton("示教录制")
        self.delete_button = QPushButton("删除动作")
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
        self.delete_button.clicked.connect(lambda: self._emit_selected(self.delete_requested))
        self.record_button.clicked.connect(lambda: self.detail.setPlainText("第一版 GUI 不直接录制，请使用阶段六动作录制器。"))
        self.teach_button.clicked.connect(lambda: self.detail.setPlainText("第一版 GUI 不直接进入示教，请使用阶段六示教模式。"))
        self.list_widget.currentTextChanged.connect(self._show_detail)

    def set_actions(self, actions: list[dict]) -> None:
        self._actions = {item["name"]: item.get("summary", {}) for item in actions}
        self.list_widget.clear()
        self.list_widget.addItems(sorted(self._actions.keys()))
        self._show_detail(self.list_widget.currentItem().text() if self.list_widget.currentItem() else "")

    def _show_detail(self, name: str) -> None:
        self.detail.setPlainText(json.dumps(self._actions.get(name, {}), ensure_ascii=False, indent=2))

    def _emit_selected(self, signal) -> None:
        item = self.list_widget.currentItem()
        if item:
            signal.emit(item.text())

