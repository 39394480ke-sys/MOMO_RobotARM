"""日志页面。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


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
        self.path_label = QLabel(f"日志文件：{self.log_path}")
        self.path_label.setWordWrap(True)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.refresh_button = QPushButton("刷新")
        self.clear_button = QPushButton("清空")
        self.open_button = QPushButton("路径")
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
        self.open_button.clicked.connect(lambda: self.text.append(f"\n日志文件路径：{self.log_path}"))
        self.refresh()

    def refresh(self) -> None:
        if not self.log_path.exists():
            self.text.setPlainText("暂无日志。")
            self._scroll_to_bottom()
            return
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.text.setPlainText("\n".join(lines[-300:]))
        self._scroll_to_bottom()

    def append_result(self, result: dict) -> None:
        self.text.append(str(result))
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self._set_scrollbar_to_bottom)

    def _set_scrollbar_to_bottom(self) -> None:
        scrollbar = self.text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
