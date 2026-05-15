"""姿态页面。"""

from __future__ import annotations

import json

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QPushButton, QTextEdit, QVBoxLayout, QWidget


class PosePage(QWidget):
    refresh_requested = pyqtSignal()
    save_requested = pyqtSignal(str)
    goto_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.list_widget = QListWidget()
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        buttons_layout = QVBoxLayout()
        self.refresh_button = QPushButton("刷新姿态列表")
        self.save_button = QPushButton("保存当前姿态")
        self.goto_button = QPushButton("前往选中姿态")
        self.delete_button = QPushButton("删除选中姿态")
        for button in (self.refresh_button, self.save_button, self.goto_button, self.delete_button):
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.detail, 2)
        layout.addLayout(buttons_layout)
        self._poses = {}
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.save_button.clicked.connect(self._ask_save)
        self.goto_button.clicked.connect(lambda: self._emit_selected(self.goto_requested))
        self.delete_button.clicked.connect(lambda: self._emit_selected(self.delete_requested))
        self.list_widget.currentTextChanged.connect(self._show_detail)

    def set_poses(self, poses: list[dict]) -> None:
        self._poses = {item["name"]: item.get("pose", {}) for item in poses}
        self.list_widget.clear()
        self.list_widget.addItems(sorted(self._poses.keys()))
        self._show_detail(self.list_widget.currentItem().text() if self.list_widget.currentItem() else "")

    def _show_detail(self, name: str) -> None:
        self.detail.setPlainText(json.dumps(self._poses.get(name, {}), ensure_ascii=False, indent=2))

    def _ask_save(self) -> None:
        name, accepted = QInputDialog.getText(self, "保存当前姿态", "姿态名称")
        if accepted and name.strip():
            self.save_requested.emit(name.strip())

    def _emit_selected(self, signal) -> None:
        item = self.list_widget.currentItem()
        if item:
            signal.emit(item.text())

