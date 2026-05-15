"""真实模式安全确认对话框。"""

from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


class SafetyConfirmDialog(QDialog):
    def __init__(self, confirm_text: str, title: str = "真实模式安全确认", parent=None):
        super().__init__(parent)
        self.confirm_text = confirm_text
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("真实硬件操作可能导致机械臂运动。请确认机械臂周围无人、无障碍物。"))
        layout.addWidget(QLabel(f"请输入：{confirm_text}"))
        self.input = QLineEdit()
        self.input.setPlaceholderText(confirm_text)
        layout.addWidget(self.input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _try_accept(self) -> None:
        if self.input.text().strip() == self.confirm_text:
            self.accept()
            return
        self.input.setStyleSheet("border: 1px solid #c62828;")


def ask_safety_confirm(parent, confirm_text: str, title: str = "真实模式安全确认") -> bool:
    dialog = SafetyConfirmDialog(confirm_text, title=title, parent=parent)
    return dialog.exec_() == QDialog.Accepted

