"""GUI 数值输入控件工具。"""

from __future__ import annotations

from PyQt5.QtWidgets import QDoubleSpinBox, QSpinBox


def make_double_spin(
    minimum: float,
    maximum: float,
    value: float,
    step: float,
    decimals: int = 2,
    suffix: str = "",
    *,
    minimum_width: int | None = None,
    minimum_height: int | None = None,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(float(minimum), float(maximum))
    spin.setSingleStep(float(step))
    spin.setDecimals(int(decimals))
    spin.setSuffix(str(suffix))
    spin.setValue(float(value))
    if minimum_width is not None:
        spin.setMinimumWidth(int(minimum_width))
    if minimum_height is not None:
        spin.setMinimumHeight(int(minimum_height))
    return spin


def make_int_spin(
    minimum: int,
    maximum: int,
    value: int,
    step: int = 1,
    suffix: str = "",
    *,
    minimum_width: int | None = None,
    minimum_height: int | None = None,
) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(int(minimum), int(maximum))
    spin.setSingleStep(int(step))
    spin.setSuffix(str(suffix))
    spin.setValue(int(value))
    if minimum_width is not None:
        spin.setMinimumWidth(int(minimum_width))
    if minimum_height is not None:
        spin.setMinimumHeight(int(minimum_height))
    return spin
