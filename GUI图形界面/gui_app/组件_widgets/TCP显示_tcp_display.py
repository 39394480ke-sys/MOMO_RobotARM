"""TCP 末端位姿显示。"""

from __future__ import annotations

import math
from PyQt5.QtWidgets import QFormLayout, QLabel, QWidget


class TCPDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        self.labels = {}
        for key in ("X", "Y", "Z", "Roll", "Pitch", "Yaw"):
            label = QLabel("--")
            self.labels[key] = label
            layout.addRow(key, label)

    def update_pose(self, pose: dict | None) -> None:
        pose = pose or {}
        xyz = pose.get("xyz") or [None, None, None]
        rpy = pose.get("rpy") or [None, None, None]
        for idx, key in enumerate(("X", "Y", "Z")):
            self.labels[key].setText("--" if xyz[idx] is None else f"{float(xyz[idx]):.4f} m")
        for idx, key in enumerate(("Roll", "Pitch", "Yaw")):
            self.labels[key].setText("--" if rpy[idx] is None else f"{math.degrees(float(rpy[idx])):.2f} deg")

