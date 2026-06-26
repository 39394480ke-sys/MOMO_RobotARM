"""姿态页面。"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QPushButton, QTextEdit, QVBoxLayout, QWidget

from gui_app.运动文本格式化_motion_text_format import format_pose_detail
from gui_app.组件_widgets.命名列表工具_named_list_tools import confirm_delete_selected, current_text, emit_selected_text, set_named_payloads


class PosePage(QWidget):
    refresh_requested = pyqtSignal()
    save_requested = pyqtSignal(str)
    goto_requested = pyqtSignal(str)
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
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(10)
        self.refresh_button = QPushButton("刷新姿态列表")
        self.save_button = QPushButton("保存当前姿态")
        self.goto_button = QPushButton("前往选中姿态")
        self.goto_button.setObjectName("PrimaryButton")
        self.delete_button = QPushButton("删除选中姿态")
        self.delete_button.setObjectName("WarningButton")
        for button in (self.refresh_button, self.save_button, self.goto_button, self.delete_button):
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.detail, 2)
        layout.addLayout(buttons_layout)
        self._poses = {}
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.save_button.clicked.connect(self._ask_save)
        self.goto_button.clicked.connect(lambda: emit_selected_text(self.list_widget, self.goto_requested))
        self.delete_button.clicked.connect(lambda: confirm_delete_selected(self, self.list_widget, "姿态", self.delete_requested))
        self.list_widget.currentTextChanged.connect(self._show_detail)

    def set_poses(self, poses: list[dict]) -> None:
        self._poses = set_named_payloads(self.list_widget, poses, lambda item: item.get("pose", {}))
        self._show_detail(current_text(self.list_widget))

    def _show_detail(self, name: str) -> None:
        pose = self._poses.get(name, {})
        if not name:
            self.detail.setPlainText("请选择左侧姿态。")
            return
        if not pose:
            self.detail.setPlainText(f"姿态：{name}\n\n暂无姿态数据。")
            return
        self.detail.setPlainText(format_pose_detail(name, pose))

    def _ask_save(self) -> None:
        name, accepted = QInputDialog.getText(self, "保存当前姿态", "姿态名称")
        if accepted and name.strip():
            self.save_requested.emit(name.strip())
