"""Quick Move 快速控制页面。"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from gui_app.控制器桥接_controller_bridge import JOINT_LABELS, JOINT_ORDER
from gui_app.组件_widgets.TCP显示_tcp_display import TCPDisplay
from gui_app.组件_widgets.仿真视图_sim_view import SimView
from gui_app.组件_widgets.关节控制条_joint_control import JointControlRow
from gui_app.组件_widgets.夹爪控制器_gripper_control import GripperControl


class QuickControlPage(QWidget):
    joint_delta_requested = pyqtSignal(str, float)
    gripper_requested = pyqtSignal(float)
    home_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, JointControlRow] = {}
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        joint_box = QGroupBox("关节控制")
        joint_layout = QVBoxLayout(joint_box)
        for joint in JOINT_ORDER:
            row = JointControlRow(joint, JOINT_LABELS[joint])
            row.delta_requested.connect(self.joint_delta_requested.emit)
            self.rows[joint] = row
            joint_layout.addWidget(row)

        step_row = QHBoxLayout()
        self.step_combo = QComboBox()
        for value in (0.5, 1, 2, 5):
            self.step_combo.addItem(f"{value:g} 度", float(value))
        self.step_combo.setCurrentIndex(1)
        step_row.addWidget(self.step_combo)
        step_row.addStretch(1)
        joint_layout.addLayout(step_row)

        self.gripper = GripperControl()
        self.gripper.value_requested.connect(self.gripper_requested.emit)

        button_row = QHBoxLayout()
        self.home_button = QPushButton("Home")
        self.refresh_button = QPushButton("刷新状态")
        self.stop_button = QPushButton("急停")
        self.stop_button.setObjectName("DangerButton")
        button_row.addWidget(self.home_button)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.stop_button)

        tcp_box = QGroupBox("TCP 末端位姿")
        tcp_layout = QVBoxLayout(tcp_box)
        self.tcp_display = TCPDisplay()
        tcp_layout.addWidget(self.tcp_display)

        left.addWidget(joint_box)
        left.addWidget(QGroupBox("夹爪控制"))
        left.itemAt(1).widget().setLayout(QVBoxLayout())
        left.itemAt(1).widget().layout().addWidget(self.gripper)
        left.addLayout(button_row)
        left.addWidget(tcp_box)
        left.addStretch(1)

        self.sim_view = SimView()
        layout.addLayout(left, 2)
        layout.addWidget(self.sim_view, 3)

        self.step_combo.currentIndexChanged.connect(self._step_changed)
        self.home_button.clicked.connect(self.home_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self._step_changed()

    def _step_changed(self) -> None:
        step = float(self.step_combo.currentData())
        for row in self.rows.values():
            row.set_step(step)

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
        grip = state.get("gripper", {}).get("open_percent")
        if grip is not None:
            self.gripper.set_value(float(grip))
        self.tcp_display.update_pose(state.get("tcp_pose"))
        self.sim_view.update_state(joints)

