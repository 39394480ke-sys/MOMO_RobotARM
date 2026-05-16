"""运动学页面。"""

from __future__ import annotations

import json

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget


class KinematicsPage(QWidget):
    fk_requested = pyqtSignal(list)
    ik_requested = pyqtSignal(list, object)
    delta_requested = pyqtSignal(float, float, float, str)
    refresh_tcp_requested = pyqtSignal()
    execute_result_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        right_column = QVBoxLayout()
        right_column.setSpacing(12)

        fk_box = QGroupBox("FK 正运动学测试")
        fk_form = self._form(fk_box)
        self.fk_inputs = []
        for idx in range(5):
            spin = self._spin(-360, 360, 0, 1)
            self.fk_inputs.append(spin)
            fk_form.addRow(f"J{idx + 1}", spin)
        self.fk_button = QPushButton("计算 FK")
        self.fk_button.setMinimumWidth(180)
        fk_form.addRow("", self.fk_button)

        ik_box = QGroupBox("IK 逆运动学测试")
        ik_form = self._form(ik_box)
        self.x_input = self._spin(-1, 1, 0.2, 0.01, 4)
        self.y_input = self._spin(-1, 1, 0.0, 0.01, 4)
        self.z_input = self._spin(-1, 1, 0.2, 0.01, 4)
        self.roll_input = self._spin(-180, 180, 0, 1)
        self.pitch_input = self._spin(-180, 180, 0, 1)
        self.yaw_input = self._spin(-180, 180, 0, 1)
        for label, widget in (("X m", self.x_input), ("Y m", self.y_input), ("Z m", self.z_input), ("Roll deg", self.roll_input), ("Pitch deg", self.pitch_input), ("Yaw deg", self.yaw_input)):
            ik_form.addRow(label, widget)
        self.ik_button = QPushButton("计算 IK")
        self.ik_button.setMinimumWidth(180)
        ik_form.addRow("", self.ik_button)

        delta_box = QGroupBox("末端增量移动")
        delta_form = self._form(delta_box)
        self.dx_input = self._spin(-0.1, 0.1, 0.01, 0.005, 4)
        self.dy_input = self._spin(-0.1, 0.1, 0.0, 0.005, 4)
        self.dz_input = self._spin(-0.1, 0.1, 0.0, 0.005, 4)
        delta_form.addRow("dx m", self.dx_input)
        delta_form.addRow("dy m", self.dy_input)
        delta_form.addRow("dz m", self.dz_input)
        self.base_delta_button = QPushButton("计算 base 增量")
        self.tool_delta_button = QPushButton("计算 tool 增量")
        self.base_delta_button.setMinimumWidth(180)
        self.tool_delta_button.setMinimumWidth(180)
        delta_form.addRow("", self.base_delta_button)
        delta_form.addRow("", self.tool_delta_button)

        self.refresh_tcp_button = QPushButton("刷新当前 TCP")
        self.refresh_tcp_button.setToolTip("读取当前关节状态并计算当前末端 TCP 位姿；不会移动机械臂。")
        self.refresh_tcp_button.setMinimumHeight(36)
        self.execute_result_button = QPushButton("执行结果")
        self.execute_result_button.setToolTip("执行最后一次 FK / IK / 末端增量计算出来的目标；没有计算结果时不会移动。")
        self.execute_result_button.setMinimumHeight(36)
        left_column.addWidget(fk_box)
        left_column.addWidget(ik_box)
        left_column.addStretch(1)

        output_box = QGroupBox("计算结果")
        output_layout = QVBoxLayout(output_box)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(180)
        output_layout.addWidget(self.output)
        right_column.addWidget(delta_box)
        right_column.addWidget(self.refresh_tcp_button)
        right_column.addWidget(self.execute_result_button)
        right_column.addWidget(output_box, 1)

        columns.addLayout(left_column, 1)
        columns.addLayout(right_column, 1)
        layout.addLayout(columns)

        self.fk_button.clicked.connect(lambda: self.fk_requested.emit([spin.value() for spin in self.fk_inputs]))
        self.ik_button.clicked.connect(self._request_ik)
        self.base_delta_button.clicked.connect(lambda: self.delta_requested.emit(self.dx_input.value(), self.dy_input.value(), self.dz_input.value(), "base"))
        self.tool_delta_button.clicked.connect(lambda: self.delta_requested.emit(self.dx_input.value(), self.dy_input.value(), self.dz_input.value(), "tool"))
        self.refresh_tcp_button.clicked.connect(self.refresh_tcp_requested.emit)
        self.execute_result_button.clicked.connect(self.execute_result_requested.emit)

    def _form(self, parent: QGroupBox) -> QFormLayout:
        form = QFormLayout(parent)
        form.setContentsMargins(14, 18, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return form

    def _spin(self, minimum: float, maximum: float, value: float, step: float, decimals: int = 2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setMinimumWidth(180)
        return spin

    def _request_ik(self) -> None:
        xyz = [self.x_input.value(), self.y_input.value(), self.z_input.value()]
        rpy = [self.roll_input.value(), self.pitch_input.value(), self.yaw_input.value()]
        rpy_rad = [value * 3.141592653589793 / 180.0 for value in rpy]
        self.ik_requested.emit(xyz, rpy_rad)

    def show_result(self, result: dict) -> None:
        self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
