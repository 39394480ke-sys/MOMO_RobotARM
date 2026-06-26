"""夹爪控制组件。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget


class GripperControl(QWidget):
    value_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        self.open_button = QPushButton("张开夹爪")
        self.close_button = QPushButton("闭合夹爪")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.value_label = QLabel("50%")

        layout.addWidget(self.close_button)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        layout.addWidget(self.open_button)

        self.open_button.clicked.connect(lambda: self._emit_value(100))
        self.close_button.clicked.connect(lambda: self._emit_value(0))
        self.slider.valueChanged.connect(lambda value: self.value_label.setText(f"{value}%"))
        self.slider.sliderReleased.connect(lambda: self._emit_value(self.slider.value()))

    def _emit_value(self, value: int) -> None:
        self.slider.setValue(int(value))
        self.value_requested.emit(float(value))

    def set_value(self, value: float) -> None:
        self.slider.setValue(int(round(float(value))))

    def set_available(self, available: bool) -> None:
        self.open_button.setEnabled(bool(available))
        self.close_button.setEnabled(bool(available))
        self.slider.setEnabled(bool(available))
        if not available:
            self.value_label.setText("未安装")
