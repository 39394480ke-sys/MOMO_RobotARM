"""关节增量控制行。"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class JointControlRow(QWidget):
    delta_requested = pyqtSignal(str, float)

    def __init__(self, joint_key: str, title: str, parent=None):
        super().__init__(parent)
        self.joint_key = joint_key
        self.angle = 0.0
        self.step_deg = 1.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        self.name_label = QLabel(title)
        self.name_label.setMinimumWidth(110)
        self.minus_button = QPushButton("-")
        self.minus_button.setFixedWidth(42)
        self.angle_label = QLabel("0.00 deg")
        self.angle_label.setMinimumWidth(90)
        self.plus_button = QPushButton("+")
        self.plus_button.setFixedWidth(42)

        layout.addWidget(self.name_label)
        layout.addWidget(self.minus_button)
        layout.addWidget(self.angle_label)
        layout.addWidget(self.plus_button)
        layout.addStretch(1)

        self.minus_button.clicked.connect(lambda: self.delta_requested.emit(self.joint_key, -self.step_deg))
        self.plus_button.clicked.connect(lambda: self.delta_requested.emit(self.joint_key, self.step_deg))

    def set_step(self, step_deg: float) -> None:
        self.step_deg = float(step_deg)

    def set_angle(self, angle: float) -> None:
        self.angle = float(angle)
        self.angle_label.setText(f"{self.angle:.2f} deg")

