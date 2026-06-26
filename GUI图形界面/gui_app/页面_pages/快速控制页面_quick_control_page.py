"""Quick Move 快速控制页面。"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from 控制桥接_common import JOINT_LABELS, JOINT_ORDER
from gui_app.组件_widgets.TCP显示_tcp_display import TCPDisplay
from gui_app.组件_widgets.关节控制条_joint_control import JointControlRow
from gui_app.组件_widgets.夹爪控制器_gripper_control import GripperControl
from gui_app.组件_widgets.布局工具_layout_tools import make_hbox_layout, make_vbox_layout
from gui_app.组件_widgets.数值输入工具_spinbox_tools import make_double_spin


class QuickControlPage(QWidget):
    joint_delta_requested = pyqtSignal(str, float)
    continuous_jog_started = pyqtSignal(str, int, float)
    continuous_jog_stopped = pyqtSignal()
    gripper_requested = pyqtSignal(float)
    home_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, JointControlRow] = {}
        self.control_mode = "step"
        self.active_joint: str | None = None
        self.active_direction = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(10)
        joint_box = QGroupBox("关节控制阵列")
        joint_box.setMinimumHeight(292)
        joint_layout = make_vbox_layout(joint_box, spacing=6)
        for joint in JOINT_ORDER:
            row = JointControlRow(joint, JOINT_LABELS[joint])
            row.delta_requested.connect(self._step_delta_requested)
            row.continuous_pressed.connect(self._continuous_pressed)
            row.continuous_released.connect(self._continuous_released)
            self.rows[joint] = row
            joint_layout.addWidget(row)

        mode_widget = QWidget()
        mode_widget.setMinimumHeight(40)
        mode_row = make_hbox_layout(mode_widget, margins=(0, 10, 0, 2), spacing=14)
        self.step_mode_radio = QPushButton("步进模式 Step")
        self.step_mode_radio.setObjectName("SegmentButton")
        self.step_mode_radio.setCheckable(True)
        self.continuous_mode_radio = QPushButton("连续模式 Continuous")
        self.continuous_mode_radio.setObjectName("SegmentButton")
        self.continuous_mode_radio.setCheckable(True)
        self.step_mode_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.step_mode_radio)
        self.mode_group.addButton(self.continuous_mode_radio)
        mode_row.addWidget(self.step_mode_radio)
        mode_row.addWidget(self.continuous_mode_radio)
        mode_row.addStretch(1)
        joint_layout.addWidget(mode_widget)
        joint_layout.addSpacing(6)

        step_row = make_hbox_layout(margins=(0, 6, 0, 0), spacing=10)
        step_row.addWidget(QLabel("步进值"))
        self.step_combo = QComboBox()
        self.step_combo.setMinimumWidth(132)
        for value in (0.5, 1, 2, 3, 4, 5):
            self.step_combo.addItem(f"{value:g} deg/mm", float(value))
        self.step_combo.setCurrentIndex(1)
        step_row.addWidget(self.step_combo)
        step_row.addStretch(1)
        joint_layout.addLayout(step_row)

        speed_row = make_hbox_layout(margins=(0, 2, 0, 0), spacing=10)
        speed_row.addWidget(QLabel("连续速度"))
        self.speed_input = make_double_spin(0.2, 20.0, 6.0, 0.5, suffix=" deg/mm/s", minimum_width=144)
        self.speed_input.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        speed_row.addWidget(self.speed_input)
        speed_row.addStretch(1)
        joint_layout.addLayout(speed_row)

        self.gripper = GripperControl()
        self.gripper.value_requested.connect(self.gripper_requested.emit)

        button_row = make_hbox_layout()
        self.home_button = QPushButton("Home")
        self.home_button.setObjectName("PrimaryButton")
        self.home_button.setMinimumWidth(120)
        self.refresh_button = QPushButton("刷新状态")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumWidth(120)
        self.stop_button = QPushButton("急停")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setMinimumWidth(120)
        button_row.addWidget(self.home_button)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.stop_button)

        tcp_box = QGroupBox("TCP 末端位姿")
        tcp_layout = make_vbox_layout(tcp_box)
        self.tcp_display = TCPDisplay()
        tcp_layout.addWidget(self.tcp_display)

        left.addWidget(joint_box)
        gripper_box = QGroupBox("夹爪控制")
        gripper_layout = make_vbox_layout(gripper_box)
        gripper_layout.addWidget(self.gripper)
        left.addWidget(gripper_box)
        left.addLayout(button_row)
        left.addWidget(tcp_box)
        left.addStretch(1)

        layout.addLayout(left, 1)

        self.step_combo.currentIndexChanged.connect(self._step_changed)
        self.step_mode_radio.toggled.connect(self._mode_changed)
        self.home_button.clicked.connect(self.home_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self._step_changed()
        self._mode_changed()

    def _step_changed(self) -> None:
        step = float(self.step_combo.currentData())
        for row in self.rows.values():
            row.set_step(step)

    def _step_delta_requested(self, joint: str, delta: float) -> None:
        if self.control_mode != "step":
            return
        self.joint_delta_requested.emit(joint, delta)

    def _mode_changed(self) -> None:
        self.control_mode = "continuous" if self.continuous_mode_radio.isChecked() else "step"
        self.speed_input.setEnabled(self.control_mode == "continuous")
        self.step_combo.setEnabled(self.control_mode == "step")
        if self.control_mode == "step":
            self._continuous_released()

    def _continuous_pressed(self, joint: str, direction: int) -> None:
        if self.control_mode != "continuous":
            return
        self.active_joint = joint
        self.active_direction = int(direction)
        self.continuous_jog_started.emit(joint, int(direction), float(self.speed_input.value()))

    def _continuous_released(self) -> None:
        if self.active_joint is not None:
            self.continuous_jog_stopped.emit()
        self.active_joint = None
        self.active_direction = 0

    def set_real_mode(self, is_real: bool, max_real_step: float = 2.0) -> None:
        if is_real:
            for idx in range(self.step_combo.count()):
                if float(self.step_combo.itemData(idx)) > max_real_step:
                    self.step_combo.model().item(idx).setEnabled(False)
            if float(self.step_combo.currentData()) > max_real_step:
                index = self.step_combo.findData(float(max_real_step))
                self.step_combo.setCurrentIndex(index if index >= 0 else 2)
        else:
            for idx in range(self.step_combo.count()):
                self.step_combo.model().item(idx).setEnabled(True)

    def update_state(self, state: dict) -> None:
        joints = state.get("joints_deg", {})
        for joint, angle in joints.items():
            if joint in self.rows:
                self.rows[joint].set_angle(float(angle))
        gripper_state = state.get("gripper", {})
        gripper_available = gripper_state.get("available", True)
        self.gripper.set_available(bool(gripper_available))
        grip = gripper_state.get("open_percent")
        if grip is not None and gripper_available:
            self.gripper.set_value(float(grip))
        self.tcp_display.update_pose(state.get("tcp_pose"))
