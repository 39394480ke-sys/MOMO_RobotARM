"""第一版 3D 仿真视图。

优先保证 GUI 启动稳定。PyBullet 不可用时显示中文提示；可用时显示当前关节文本。
后续可以在这里扩展 DIRECT 渲染图片。
"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class SimView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = QLabel("正在检查 3D 仿真视图...")
        self.label.setMinimumHeight(180)
        self.label.setStyleSheet("background: #ffffff; border: 1px solid #cfd7e2; border-radius: 6px; padding: 10px;")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.pybullet_available = self._check_pybullet()
        if not self.pybullet_available:
            self.label.setText("PyBullet 未安装，3D 仿真视图不可用。")
        else:
            self.label.setText("PyBullet 可用。当前第一版显示关节状态；后续可扩展为 DIRECT 渲染图。")

    def _check_pybullet(self) -> bool:
        try:
            import pybullet  # noqa: F401

            return True
        except Exception:
            return False

    def update_state(self, joints_deg: dict) -> None:
        if not self.pybullet_available:
            return
        lines = ["PyBullet 可用，当前关节："]
        for key, value in (joints_deg or {}).items():
            lines.append(f"{key}: {float(value):.2f} deg")
        self.label.setText("\n".join(lines))

