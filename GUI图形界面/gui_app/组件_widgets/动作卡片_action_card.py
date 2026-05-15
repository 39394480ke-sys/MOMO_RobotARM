"""动作摘要卡片。"""

from __future__ import annotations

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ActionCard(QWidget):
    def __init__(self, name: str, summary: dict, parent=None):
        super().__init__(parent)
        self.name = name
        layout = QHBoxLayout(self)
        text_layout = QVBoxLayout()
        title = QLabel(name)
        title.setStyleSheet("font-weight: 700;")
        summary_text = (
            f"pose_count={summary.get('pose_count', 0)} | "
            f"gripper={summary.get('是否包含 gripper', False)} | "
            f"tcp_pose={summary.get('是否包含 tcp_pose', False)} | "
            f"multi_turn={summary.get('是否包含 multi_turn_state', False)}"
        )
        text_layout.addWidget(title)
        text_layout.addWidget(QLabel(summary_text))
        self.play_button = QPushButton("播放")
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.play_button)

