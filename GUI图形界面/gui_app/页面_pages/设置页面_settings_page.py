"""设置页面。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QFormLayout, QGroupBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


class SettingsPage(QWidget):
    mode_change_requested = pyqtSignal(str)
    connect_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    dependency_check_requested = pyqtSignal()
    calibration_check_requested = pyqtSignal()

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        mode_box = QGroupBox("通信与模式配置")
        form = QFormLayout(mode_box)
        form.setContentsMargins(12, 18, 12, 12)
        form.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("仿真模式", "simulation")
        self.mode_combo.addItem("dry-run 模式", "dry_run")
        self.mode_combo.addItem("真实模式", "real")
        self.mode_combo.setCurrentIndex(1)
        self.port_input = QLineEdit("/dev/tty.usbmodem5B141127021")
        self.port_input.setPlaceholderText("串口设备路径")
        form.addRow("模式", self.mode_combo)
        form.addRow("串口", self.port_input)

        path_box = QGroupBox("文件存储与路径资源")
        path_layout = QGridLayout(path_box)
        path_layout.setContentsMargins(12, 18, 12, 12)
        path_layout.setSpacing(8)
        self.path_fields: dict[str, QLineEdit] = {}
        for row, label in enumerate(("仿真配置", "真实配置", "动作配置", "运动学配置", "URDF 路径")):
            title = QLabel(label)
            title.setObjectName("PathName")
            field = QLineEdit()
            field.setObjectName("PathField")
            field.setReadOnly(True)
            field.setCursorPosition(0)
            self.path_fields[label] = field
            path_layout.addWidget(title, row, 0)
            path_layout.addWidget(field, row, 1)
        path_layout.setColumnStretch(1, 1)

        tools_box = QGroupBox("系统工具链")
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(12, 18, 12, 12)
        tools_layout.setSpacing(8)
        button_row = QWidget()
        button_row.setObjectName("ButtonTray")
        buttons = QHBoxLayout(button_row)
        buttons.setContentsMargins(12, 8, 12, 8)
        buttons.setSpacing(8)
        self.connect_button = QPushButton("连接桥接层")
        self.connect_button.setObjectName("PrimaryButton")
        self.disconnect_button = QPushButton("断开桥接层")
        self.refresh_button = QPushButton("刷新状态")
        self.dependency_button = QPushButton("检查依赖环境")
        self.calibration_button = QPushButton("验证标定文件")
        for button in (self.dependency_button, self.calibration_button, self.connect_button, self.disconnect_button, self.refresh_button):
            buttons.addWidget(button)
        tools_layout.addWidget(button_row)

        self.result_label = QLabel("默认 dry-run，不自动连接真实硬件。")
        self.result_label.setObjectName("StatusPill")
        self.result_label.setWordWrap(True)
        layout.addWidget(mode_box)
        layout.addWidget(path_box)
        layout.addWidget(tools_box)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.connect_button.clicked.connect(self.connect_requested.emit)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.dependency_button.clicked.connect(self.dependency_check_requested.emit)
        self.calibration_button.clicked.connect(self.calibration_check_requested.emit)
        self.refresh_paths()

    def _mode_changed(self) -> None:
        self.mode_change_requested.emit(str(self.mode_combo.currentData()))

    def set_mode(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        if index >= 0:
            blocked = self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(index)
            self.mode_combo.blockSignals(blocked)

    def refresh_paths(self) -> None:
        cfg = self.bridge.config.get("controller", {})
        for label, key in (
            ("仿真配置", "sim_config_path"),
            ("真实配置", "real_config_path"),
            ("动作配置", "action_config_path"),
            ("运动学配置", "kinematics_config_path"),
        ):
            value = cfg.get(key, "")
            path = (self.bridge.base_dir / value).resolve() if value else Path("")
            if label in self.path_fields:
                self.path_fields[label].setText(str(path))
                self.path_fields[label].setCursorPosition(0)
        urdf_path = (self.bridge.project_root / "URDF运动学仿真" / "urdf" / "soarmoce_urdf.urdf").resolve()
        self.path_fields["URDF 路径"].setText(str(urdf_path))
        self.path_fields["URDF 路径"].setCursorPosition(0)

    def show_result(self, result: dict) -> None:
        self.result_label.setText(str(result.get("message", result)))
