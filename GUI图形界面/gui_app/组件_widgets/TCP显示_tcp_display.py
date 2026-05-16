"""TCP 末端位姿显示。"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QLabel, QWidget


class TCPDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        self.labels = {}
        for index, key in enumerate(("X", "Y", "Z", "Roll", "Pitch", "Yaw")):
            tile = QWidget()
            tile.setObjectName("TelemetryTile")
            tile_layout = QGridLayout(tile)
            tile_layout.setContentsMargins(8, 6, 8, 6)
            tile_layout.setHorizontalSpacing(6)
            name = QLabel(key)
            name.setObjectName("TelemetryName")
            label = QLabel("--")
            label.setObjectName("TelemetryValue")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.labels[key] = label
            tile_layout.addWidget(name, 0, 0)
            tile_layout.addWidget(label, 0, 1)
            row = index // 3
            col = index % 3
            layout.addWidget(tile, row, col)
            layout.setColumnStretch(col, 1)

    def update_pose(self, pose: dict | None) -> None:
        pose = pose or {}
        xyz = pose.get("xyz") or [None, None, None]
        rpy = pose.get("rpy") or [None, None, None]
        for idx, key in enumerate(("X", "Y", "Z")):
            self.labels[key].setText("--" if xyz[idx] is None else f"{float(xyz[idx]):.4f} m")
        for idx, key in enumerate(("Roll", "Pitch", "Yaw")):
            self.labels[key].setText("--" if rpy[idx] is None else f"{float(rpy[idx]) * 57.29577951308232:.2f} deg")
