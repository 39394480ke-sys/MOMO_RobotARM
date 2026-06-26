"""动作库页面。"""

from __future__ import annotations

import time

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTextEdit, QVBoxLayout, QWidget

from gui_app.动作摘要格式化_action_summary_format import format_action_summary_detail
from gui_app.组件_widgets.布局工具_layout_tools import make_vbox_layout
from gui_app.组件_widgets.命名列表工具_named_list_tools import confirm_delete_selected, current_text, emit_selected_text, set_named_payloads


class ActionPage(QWidget):
    refresh_requested = pyqtSignal()
    play_requested = pyqtSignal(str)
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)
    record_start_requested = pyqtSignal(str)
    teach_start_requested = pyqtSignal(str)
    capture_pose_requested = pyqtSignal()
    save_recording_requested = pyqtSignal()
    cancel_recording_requested = pyqtSignal()

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
        self.delete_button = QPushButton("删除动作")
        self.delete_button.setObjectName("WarningButton")

        record_box = QGroupBox("动作录制")
        record_layout = make_vbox_layout(record_box, margins=(10, 16, 10, 10))
        self.record_name_input = QLineEdit()
        self.record_name_input.setPlaceholderText("动作名称，例如：抓取演示")
        self.record_name_input.setText(f"GUI录制_{time.strftime('%H%M%S')}")
        self.record_status_label = QLabel("未开始录制")
        self.record_status_label.setObjectName("PathLabel")
        self.record_button = QPushButton("开始录制")
        self.record_button.setObjectName("PrimaryButton")
        self.teach_button = QPushButton("示教录制")
        self.teach_button.setObjectName("WarningButton")
        self.capture_button = QPushButton("采集当前帧")
        self.save_recording_button = QPushButton("保存录制")
        self.save_recording_button.setObjectName("PrimaryButton")
        self.cancel_recording_button = QPushButton("取消录制")
        record_layout.addWidget(QLabel("动作名称"))
        record_layout.addWidget(self.record_name_input)
        record_layout.addWidget(self.record_status_label)
        record_layout.addWidget(self.record_button)
        record_layout.addWidget(self.teach_button)
        record_layout.addWidget(self.capture_button)
        record_layout.addWidget(self.save_recording_button)
        record_layout.addWidget(self.cancel_recording_button)

        for button in (self.refresh_button, self.play_button, self.pause_button, self.resume_button, self.stop_button, self.delete_button):
            button_layout.addWidget(button)
        button_layout.addWidget(record_box)
        button_layout.addStretch(1)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.detail, 2)
        layout.addLayout(button_layout)
        self._actions = {}
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.play_button.clicked.connect(lambda: emit_selected_text(self.list_widget, self.play_requested))
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.delete_button.clicked.connect(lambda: confirm_delete_selected(self, self.list_widget, "动作", self.delete_requested))
        self.record_button.clicked.connect(lambda: self.record_start_requested.emit(self.record_name_input.text()))
        self.teach_button.clicked.connect(lambda: self.teach_start_requested.emit(self.record_name_input.text()))
        self.capture_button.clicked.connect(self.capture_pose_requested.emit)
        self.save_recording_button.clicked.connect(self.save_recording_requested.emit)
        self.cancel_recording_button.clicked.connect(self.cancel_recording_requested.emit)
        self.list_widget.currentTextChanged.connect(self._show_detail)
        self.set_recording_status({"active": False})

    def set_actions(self, actions: list[dict]) -> None:
        self._actions = set_named_payloads(self.list_widget, actions, lambda item: item.get("summary", {}))
        self._show_detail(current_text(self.list_widget))

    def _show_detail(self, name: str) -> None:
        summary = self._actions.get(name, {})
        if not name:
            self.detail.setPlainText("请选择左侧动作。")
            return
        if not summary:
            self.detail.setPlainText(f"动作：{name}\n\n暂无动作摘要。")
            return
        self.detail.setPlainText(format_action_summary_detail(name, summary))

    def set_recording_status(self, recording: dict) -> None:
        active = bool(recording.get("active"))
        count = int(recording.get("pose_count", 0) or 0)
        name = str(recording.get("name") or self.record_name_input.text() or "--")
        self.record_status_label.setText(f"录制中：{name} | 已采集 {count} 帧" if active else "未开始录制")
        self.record_button.setEnabled(not active)
        self.teach_button.setEnabled(not active)
        self.record_name_input.setEnabled(not active)
        self.capture_button.setEnabled(active)
        self.save_recording_button.setEnabled(active and count > 0)
        self.cancel_recording_button.setEnabled(active)
