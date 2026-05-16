"""关节增量控制行。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class JointControlRow(QWidget):
    delta_requested = pyqtSignal(str, float)
    continuous_pressed = pyqtSignal(str, int)
    continuous_released = pyqtSignal()

    def __init__(self, joint_key: str, title: str, parent=None):
        super().__init__(parent)
        self.joint_key = joint_key
        self.angle = 0.0
        self.step_deg = 1.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        self.setMinimumWidth(470)
        self.name_label = QLabel(f"{joint_key.upper()} / {title}")
        self.name_label.setMinimumWidth(210)
        self.name_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.minus_button = QPushButton("-")
        self.minus_button.setObjectName("JointStepButton")
        self.minus_button.setMinimumWidth(42)
        self.minus_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.angle_label = QLabel("0.00 deg")
        self.angle_label.setObjectName("AngleReadout")
        self.angle_label.setMinimumWidth(118)
        self.angle_label.setMaximumWidth(150)
        self.angle_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.angle_label.setAlignment(Qt.AlignCenter)
        self.plus_button = QPushButton("+")
        self.plus_button.setObjectName("JointStepButton")
        self.plus_button.setMinimumWidth(42)
        self.plus_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        layout.addWidget(self.name_label)
        layout.addWidget(self.minus_button)
        layout.addWidget(self.angle_label)
        layout.addWidget(self.plus_button)
        layout.addStretch(1)

        self.minus_button.clicked.connect(lambda: self.delta_requested.emit(self.joint_key, -self.step_deg))
        self.plus_button.clicked.connect(lambda: self.delta_requested.emit(self.joint_key, self.step_deg))
        self.minus_button.pressed.connect(lambda: self.continuous_pressed.emit(self.joint_key, -1))
        self.plus_button.pressed.connect(lambda: self.continuous_pressed.emit(self.joint_key, 1))
        self.minus_button.released.connect(self.continuous_released.emit)
        self.plus_button.released.connect(self.continuous_released.emit)

    def set_step(self, step_deg: float) -> None:
        self.step_deg = float(step_deg)

    def set_angle(self, angle: float) -> None:
        self.angle = float(angle)
        self.angle_label.setText(f"{self.angle:.2f} deg")
