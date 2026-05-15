"""全局状态栏组件。"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QStatusBar


class GlobalStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel("模式：dry-run | 连接：未连接 | 标定：未知 | 动作：空闲")
        self.addPermanentWidget(self.label, 1)

    def update_status(
        self,
        mode: str,
        connected: bool,
        calibration_ok: bool | None,
        action_status: str,
        last_error: str = "",
    ) -> None:
        mode_text = {"simulation": "仿真", "dry_run": "dry-run", "real": "真实"}.get(mode, mode)
        conn_text = "已连接" if connected else "未连接"
        if calibration_ok is None:
            cal_text = "未知"
        else:
            cal_text = "完整" if calibration_ok else "不完整"
        error_text = f" | 错误：{last_error}" if last_error else ""
        self.label.setText(f"模式：{mode_text} | 连接：{conn_text} | 标定：{cal_text} | 动作：{action_status}{error_text}")

