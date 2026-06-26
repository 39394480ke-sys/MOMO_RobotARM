"""设置页面。"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from 控制桥接_common import DEFAULT_MOTION_TUNING
from gui_app.结果格式化_result_format import result_message
from gui_app.组件_widgets.布局工具_layout_tools import make_form_layout, make_grid_layout, make_vbox_layout
from gui_app.组件_widgets.数值输入工具_spinbox_tools import make_double_spin, make_int_spin


class SettingsPage(QWidget):
    mode_change_requested = pyqtSignal(str)
    connect_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    dependency_check_requested = pyqtSignal()
    calibration_check_requested = pyqtSignal()
    motion_tuning_changed = pyqtSignal(dict)
    motion_tuning_reset_requested = pyqtSignal()

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self._updating_motion_tuning = False
        self.motion_direction_overrides: dict[str, int] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        mode_box = QGroupBox("通信与模式配置")
        form = make_form_layout(mode_box)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("仿真模式", "simulation")
        self.mode_combo.addItem("dry-run 模式", "dry_run")
        self.mode_combo.addItem("真实模式", "real")
        self.mode_combo.setCurrentIndex(1)
        self.port_input = QLineEdit(os.environ.get("ARM_ROBOT_PORT", ""))
        self.port_input.setPlaceholderText("串口设备路径")
        form.addRow("模式", self.mode_combo)
        form.addRow("串口", self.port_input)

        path_box = QGroupBox("文件存储与路径资源")
        path_layout = make_grid_layout(path_box)
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
        tools_layout = make_vbox_layout(tools_box)
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

        motion_box = QGroupBox("运动调参 / 全局")
        motion_box.setCheckable(True)
        motion_box.setChecked(False)
        motion_layout = make_vbox_layout(motion_box)
        self.motion_body = QWidget()
        motion_form = make_form_layout(self.motion_body, margins=(0, 0, 0, 0))
        self.quick_step_duration_input = make_double_spin(0.05, 10.0, DEFAULT_MOTION_TUNING["quick_step_duration_s"], 0.05, 2, " s")
        self.quick_step_frames_input = make_int_spin(1, 240, DEFAULT_MOTION_TUNING["quick_step_frames"], 1)
        self.continuous_update_hz_input = make_double_spin(2.0, 60.0, DEFAULT_MOTION_TUNING["continuous_update_hz"], 1.0, 1, " Hz")
        self.continuous_target_horizon_input = make_double_spin(0.0, 2.0, DEFAULT_MOTION_TUNING["continuous_target_horizon_s"], 0.05, 2, " s")
        self.playback_update_hz_input = make_double_spin(2.0, 60.0, DEFAULT_MOTION_TUNING["playback_update_hz"], 1.0, 1, " Hz")
        motion_form.addRow("单击用时", self.quick_step_duration_input)
        motion_form.addRow("单击帧数", self.quick_step_frames_input)
        motion_form.addRow("长按刷新率", self.continuous_update_hz_input)
        motion_form.addRow("长按前瞻", self.continuous_target_horizon_input)
        motion_form.addRow("动作/AI运镜刷新率", self.playback_update_hz_input)
        self.reset_motion_button = QPushButton("恢复推荐值")
        self.reset_motion_button.setObjectName("GhostButton")
        motion_layout.addWidget(self.motion_body)
        motion_layout.addWidget(self.reset_motion_button)
        self.motion_body.setVisible(False)

        self.result_label = QLabel("默认 dry-run，不自动连接真实硬件。")
        self.result_label.setObjectName("StatusPill")
        self.result_label.setWordWrap(True)
        layout.addWidget(mode_box)
        layout.addWidget(path_box)
        layout.addWidget(motion_box)
        layout.addWidget(tools_box)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.connect_button.clicked.connect(self.connect_requested.emit)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.dependency_button.clicked.connect(self.dependency_check_requested.emit)
        self.calibration_button.clicked.connect(self.calibration_check_requested.emit)
        motion_box.toggled.connect(self.motion_body.setVisible)
        self.reset_motion_button.clicked.connect(self.motion_tuning_reset_requested.emit)
        for widget in (
            self.quick_step_duration_input,
            self.quick_step_frames_input,
            self.continuous_update_hz_input,
            self.continuous_target_horizon_input,
            self.playback_update_hz_input,
        ):
            widget.valueChanged.connect(self._emit_motion_tuning_changed)
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

    def set_motion_tuning(self, tuning: dict) -> None:
        self._updating_motion_tuning = True
        try:
            self.quick_step_duration_input.setValue(float(tuning.get("quick_step_duration_s", DEFAULT_MOTION_TUNING["quick_step_duration_s"])))
            self.quick_step_frames_input.setValue(int(tuning.get("quick_step_frames", DEFAULT_MOTION_TUNING["quick_step_frames"])))
            self.continuous_update_hz_input.setValue(float(tuning.get("continuous_update_hz", DEFAULT_MOTION_TUNING["continuous_update_hz"])))
            self.continuous_target_horizon_input.setValue(float(tuning.get("continuous_target_horizon_s", DEFAULT_MOTION_TUNING["continuous_target_horizon_s"])))
            self.playback_update_hz_input.setValue(float(tuning.get("playback_update_hz", DEFAULT_MOTION_TUNING["playback_update_hz"])))
            raw_overrides = tuning.get("jog_direction_overrides", {})
            self.motion_direction_overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}
        finally:
            self._updating_motion_tuning = False

    def _motion_tuning_payload(self) -> dict:
        return {
            "quick_step_duration_s": float(self.quick_step_duration_input.value()),
            "quick_step_frames": int(self.quick_step_frames_input.value()),
            "continuous_update_hz": float(self.continuous_update_hz_input.value()),
            "continuous_target_horizon_s": float(self.continuous_target_horizon_input.value()),
            "playback_update_hz": float(self.playback_update_hz_input.value()),
            "jog_direction_overrides": dict(self.motion_direction_overrides),
        }

    def _emit_motion_tuning_changed(self) -> None:
        if self._updating_motion_tuning:
            return
        self.motion_tuning_changed.emit(self._motion_tuning_payload())

    def show_result(self, result: dict) -> None:
        self.result_label.setText(result_message(result))
