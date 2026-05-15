"""运动学页面。"""

from __future__ import annotations

import json

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget


class KinematicsPage(QWidget):
    fk_requested = pyqtSignal(list)
    ik_requested = pyqtSignal(list, object)
    execute_ik_requested = pyqtSignal(dict)
    delta_requested = pyqtSignal(float, float, float, str)
    refresh_tcp_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_ik_targets: dict | None = None
        layout = QHBoxLayout(self)
        controls = QVBoxLayout()

        fk_box = QGroupBox("FK 正运动学测试")
        fk_form = QFormLayout(fk_box)
        self.fk_inputs = []
        for idx in range(5):
            spin = self._spin(-360, 360, 0, 1)
            self.fk_inputs.append(spin)
            fk_form.addRow(f"J{idx + 1}", spin)
        self.fk_button = QPushButton("计算 FK")
        fk_form.addRow("", self.fk_button)

        ik_box = QGroupBox("IK 逆运动学测试")
        ik_form = QFormLayout(ik_box)
        self.x_input = self._spin(-1, 1, 0.2, 0.01, 4)
        self.y_input = self._spin(-1, 1, 0.0, 0.01, 4)
        self.z_input = self._spin(-1, 1, 0.2, 0.01, 4)
        self.roll_input = self._spin(-180, 180, 0, 1)
        self.pitch_input = self._spin(-180, 180, 0, 1)
        self.yaw_input = self._spin(-180, 180, 0, 1)
        for label, widget in (("X m", self.x_input), ("Y m", self.y_input), ("Z m", self.z_input), ("Roll deg", self.roll_input), ("Pitch deg", self.pitch_input), ("Yaw deg", self.yaw_input)):
            ik_form.addRow(label, widget)
        self.ik_button = QPushButton("计算 IK")
        self.execute_ik_button = QPushButton("执行 IK 结果")
        ik_form.addRow("", self.ik_button)
        ik_form.addRow("", self.execute_ik_button)

        delta_box = QGroupBox("末端增量移动")
        delta_form = QFormLayout(delta_box)
        self.dx_input = self._spin(-0.1, 0.1, 0.01, 0.005, 4)
        self.dy_input = self._spin(-0.1, 0.1, 0.0, 0.005, 4)
        self.dz_input = self._spin(-0.1, 0.1, 0.0, 0.005, 4)
        delta_form.addRow("dx m", self.dx_input)
        delta_form.addRow("dy m", self.dy_input)
        delta_form.addRow("dz m", self.dz_input)
        self.base_delta_button = QPushButton("base 增量移动")
        self.tool_delta_button = QPushButton("tool 增量移动")
        delta_form.addRow("", self.base_delta_button)
        delta_form.addRow("", self.tool_delta_button)

        self.refresh_tcp_button = QPushButton("刷新当前 TCP")
        controls.addWidget(fk_box)
        controls.addWidget(ik_box)
        controls.addWidget(delta_box)
        controls.addWidget(self.refresh_tcp_button)
        controls.addStretch(1)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addLayout(controls, 1)
        layout.addWidget(self.output, 2)

        self.fk_button.clicked.connect(lambda: self.fk_requested.emit([spin.value() for spin in self.fk_inputs]))
        self.ik_button.clicked.connect(self._request_ik)
        self.execute_ik_button.clicked.connect(self._execute_ik)
        self.base_delta_button.clicked.connect(lambda: self.delta_requested.emit(self.dx_input.value(), self.dy_input.value(), self.dz_input.value(), "base"))
        self.tool_delta_button.clicked.connect(lambda: self.delta_requested.emit(self.dx_input.value(), self.dy_input.value(), self.dz_input.value(), "tool"))
        self.refresh_tcp_button.clicked.connect(self.refresh_tcp_requested.emit)

    def _spin(self, minimum: float, maximum: float, value: float, step: float, decimals: int = 2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        return spin

    def _request_ik(self) -> None:
        xyz = [self.x_input.value(), self.y_input.value(), self.z_input.value()]
        rpy = [self.roll_input.value(), self.pitch_input.value(), self.yaw_input.value()]
        rpy_rad = [value * 3.141592653589793 / 180.0 for value in rpy]
        self.ik_requested.emit(xyz, rpy_rad)

    def _execute_ik(self) -> None:
        if self.last_ik_targets:
            self.execute_ik_requested.emit(self.last_ik_targets)

    def show_result(self, result: dict) -> None:
        data = result.get("data", {})
        if result.get("ok") and "target_joints_deg" in data:
            self.last_ik_targets = data["target_joints_deg"]
        self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))

