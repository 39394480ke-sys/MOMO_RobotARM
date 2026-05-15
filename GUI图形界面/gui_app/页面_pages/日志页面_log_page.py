"""日志页面。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogPage(QWidget):
    refresh_requested = pyqtSignal()

    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self.log_path = Path(log_path)
        layout = QVBoxLayout(self)
        self.path_label = QLabel(f"日志文件：{self.log_path}")
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.refresh_button = QPushButton("刷新日志")
        self.clear_button = QPushButton("清空日志视图")
        self.open_button = QPushButton("显示日志文件路径")
        layout.addWidget(self.path_label)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.clear_button)
        layout.addWidget(self.open_button)
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(self.text.clear)
        self.open_button.clicked.connect(lambda: self.text.append(f"\n日志文件路径：{self.log_path}"))
        self.refresh()

    def refresh(self) -> None:
        if not self.log_path.exists():
            self.text.setPlainText("暂无日志。")
            return
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.text.setPlainText("\n".join(lines[-300:]))

    def append_result(self, result: dict) -> None:
        self.text.append(str(result))

