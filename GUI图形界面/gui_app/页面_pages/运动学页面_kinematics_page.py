"""运动学页面。"""

from __future__ import annotations

import json
from collections.abc import Mapping

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from gui_app.运动文本格式化_motion_text_format import append_joint_lines, append_tcp_lines
from gui_app.结果格式化_result_format import result_message
from gui_app.组件_widgets.布局工具_layout_tools import make_form_layout
from gui_app.组件_widgets.数值输入工具_spinbox_tools import make_double_spin


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
        columns.setSpacing(10)
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        fk_box = QGroupBox("FK 正运动学测试")
        fk_form = self._form(fk_box)
        self.fk_inputs = []
        for idx in range(5):
            spin = self._spin(-360, 360, 0, 1)
            self.fk_inputs.append(spin)
            fk_form.addRow(f"J{idx + 1}", spin)
        self.fk_button = QPushButton("计算 FK")
        self.fk_button.setObjectName("PrimaryButton")
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
        self.ik_button.setObjectName("PrimaryButton")
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
        self.base_delta_button = QPushButton("计算 Base 坐标系增量")
        self.tool_delta_button = QPushButton("计算 Tool 坐标系增量")
        self.base_delta_button.setObjectName("PrimaryButton")
        self.tool_delta_button.setObjectName("PrimaryButton")
        self.base_delta_button.setMinimumWidth(180)
        self.tool_delta_button.setMinimumWidth(180)
        delta_form.addRow("", self.base_delta_button)
        delta_form.addRow("", self.tool_delta_button)

        self.refresh_tcp_button = QPushButton("刷新当前 TCP")
        self.refresh_tcp_button.setObjectName("GhostButton")
        self.refresh_tcp_button.setToolTip("读取当前关节状态并计算当前末端 TCP 位姿；不会移动机械臂。")
        self.refresh_tcp_button.setMinimumHeight(36)
        self.execute_result_button = QPushButton("执行计算结果 EXECUTE TARGET")
        self.execute_result_button.setObjectName("ExecuteButton")
        self.execute_result_button.setToolTip("执行最后一次 FK / IK / 末端增量计算出来的目标；没有计算结果时不会移动。")
        self.execute_result_button.setMinimumHeight(50)
        self.execute_result_button.setEnabled(False)
        left_column.addWidget(fk_box)
        left_column.addWidget(ik_box)
        left_column.addStretch(1)

        output_box = QGroupBox("计算结果")
        output_layout = QVBoxLayout(output_box)
        self.output = QTextEdit()
        self.output.setObjectName("DetailText")
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
        form = make_form_layout(parent)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return form

    def _spin(self, minimum: float, maximum: float, value: float, step: float, decimals: int = 2):
        return make_double_spin(minimum, maximum, value, step, decimals, minimum_width=180)

    def _request_ik(self) -> None:
        xyz = [self.x_input.value(), self.y_input.value(), self.z_input.value()]
        rpy = [self.roll_input.value(), self.pitch_input.value(), self.yaw_input.value()]
        rpy_rad = [value * 3.141592653589793 / 180.0 for value in rpy]
        self.ik_requested.emit(xyz, rpy_rad)

    def show_result(self, result: dict) -> None:
        self.output.setPlainText(self._format_result(result))

    def set_execute_available(self, available: bool) -> None:
        self.execute_result_button.setEnabled(bool(available))

    def _format_result(self, result: dict) -> str:
        ok = bool(result.get("ok"))
        lines = [f"状态: {'成功' if ok else '失败'}"]
        message = result_message(result, "")
        if message:
            lines.append(f"消息: {message}")
        data = result.get("data")
        if isinstance(data, Mapping):
            append_tcp_lines(lines, "TCP", data.get("tcp_pose") or data.get("target_tcp_pose"))
            targets = data.get("target_joints_deg") or data.get("targets_deg")
            append_joint_lines(lines, "目标关节角度", targets)
            ik = data.get("ik")
            if isinstance(ik, Mapping):
                append_tcp_lines(lines, "IK 目标位姿", {"xyz": ik.get("xyz"), "rpy": ik.get("rpy")})
                joints = ik.get("joints_deg") or ik.get("target_joints_deg")
                append_joint_lines(lines, "IK 关节解", joints)
        if len(lines) <= 2 and data is not None:
            lines.append("")
            lines.append(json.dumps(data, ensure_ascii=False, indent=2))
        return "\n".join(lines)
