"""姿态页面。"""

from __future__ import annotations

import json
from collections.abc import Mapping

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget


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
        self.goto_button.clicked.connect(lambda: self._emit_selected(self.goto_requested))
        self.delete_button.clicked.connect(self._confirm_delete)
        self.list_widget.currentTextChanged.connect(self._show_detail)

    def set_poses(self, poses: list[dict]) -> None:
        self._poses = {item["name"]: item.get("pose", {}) for item in poses}
        self.list_widget.clear()
        self.list_widget.addItems(sorted(self._poses.keys()))
        self._show_detail(self.list_widget.currentItem().text() if self.list_widget.currentItem() else "")

    def _show_detail(self, name: str) -> None:
        pose = self._poses.get(name, {})
        if not name:
            self.detail.setPlainText("请选择左侧姿态。")
            return
        if not pose:
            self.detail.setPlainText(f"姿态：{name}\n\n暂无姿态数据。")
            return
        self.detail.setPlainText(self._format_pose_detail(name, pose))

    def _format_pose_detail(self, name: str, pose: object) -> str:
        lines = [f"姿态：{name}", ""]
        if isinstance(pose, Mapping):
            joints = pose.get("joints_deg") or pose.get("joints") or pose.get("targets_deg")
            tcp = pose.get("tcp_pose") or pose.get("tcp")
            if isinstance(joints, Mapping):
                lines.append("关节角度")
                for key, value in joints.items():
                    lines.append(f"  {key}: {float(value):.2f} deg")
            if isinstance(tcp, Mapping):
                xyz = tcp.get("xyz")
                rpy = tcp.get("rpy")
                lines.append("")
                lines.append("TCP")
                if isinstance(xyz, (list, tuple)) and len(xyz) >= 3:
                    lines.append(f"  XYZ: {float(xyz[0]):.4f}, {float(xyz[1]):.4f}, {float(xyz[2]):.4f} m")
                if isinstance(rpy, (list, tuple)) and len(rpy) >= 3:
                    lines.append(f"  RPY: {float(rpy[0]) * 57.2958:.2f}, {float(rpy[1]) * 57.2958:.2f}, {float(rpy[2]) * 57.2958:.2f} deg")
        if len(lines) <= 2:
            lines.append(json.dumps(pose, ensure_ascii=False, indent=2))
        return "\n".join(lines)

    def _ask_save(self) -> None:
        name, accepted = QInputDialog.getText(self, "保存当前姿态", "姿态名称")
        if accepted and name.strip():
            self.save_requested.emit(name.strip())

    def _emit_selected(self, signal) -> None:
        item = self.list_widget.currentItem()
        if item:
            signal.emit(item.text())

    def _confirm_delete(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        reply = QMessageBox.question(self, "确认删除姿态", f"确定删除姿态“{item.text()}”？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(item.text())
