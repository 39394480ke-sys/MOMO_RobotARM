"""设置页面。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget


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

        mode_box = QGroupBox("连接配置")
        form = QFormLayout(mode_box)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("仿真模式", "simulation")
        self.mode_combo.addItem("dry-run 模式", "dry_run")
        self.mode_combo.addItem("真实模式", "real")
        self.mode_combo.setCurrentIndex(1)
        self.port_input = QLineEdit("/dev/tty.usbmodem5B141127021")
        form.addRow("模式", self.mode_combo)
        form.addRow("串口", self.port_input)

        self.path_text = QTextEdit()
        self.path_text.setReadOnly(True)
        self.path_text.setMinimumHeight(150)
        form.addRow("配置路径", self.path_text)

        button_row = QWidget()
        from PyQt5.QtWidgets import QHBoxLayout

        buttons = QHBoxLayout(button_row)
        self.connect_button = QPushButton("连接")
        self.connect_button.setObjectName("PrimaryButton")
        self.disconnect_button = QPushButton("断开")
        self.refresh_button = QPushButton("刷新状态")
        self.dependency_button = QPushButton("检查依赖")
        self.calibration_button = QPushButton("检查标定")
        for button in (self.connect_button, self.disconnect_button, self.refresh_button, self.dependency_button, self.calibration_button):
            buttons.addWidget(button)
        form.addRow("", button_row)

        self.result_label = QLabel("默认 dry-run，不自动连接真实硬件。")
        self.result_label.setWordWrap(True)
        layout.addWidget(mode_box)
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
        lines = []
        for label, key in (
            ("仿真配置", "sim_config_path"),
            ("真实配置", "real_config_path"),
            ("动作配置", "action_config_path"),
            ("运动学配置", "kinematics_config_path"),
        ):
            value = cfg.get(key, "")
            path = (self.bridge.base_dir / value).resolve() if value else Path("")
            lines.append(f"{label}: {path}")
        lines.append(f"URDF 路径: {(self.bridge.project_root / 'URDF运动学仿真' / 'urdf' / 'soarmoce_urdf.urdf').resolve()}")
        self.path_text.setPlainText("\n".join(lines))

    def show_result(self, result: dict) -> None:
        self.result_label.setText(str(result.get("message", result)))

