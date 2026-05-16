"""全局状态栏组件。"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QStatusBar


class GlobalStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel("🌐 模式: dry-run  |  🔌 链路: 未连接  |  🎯 标定: 未知  |  ⚙️ 动作内核: 空闲  |  🚨 异常: 无")
        self.label.setObjectName("FooterStatusText")
        self.light = QLabel()
        self.light.setObjectName("FooterLightOk")
        self.addPermanentWidget(self.label, 1)
        self.addPermanentWidget(self.light, 0)

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
        error_text = last_error if last_error else "无"
        self.label.setText(f"🌐 模式: {mode_text}  |  🔌 链路: {conn_text}  |  🎯 标定: {cal_text}  |  ⚙️ 动作内核: {action_status}  |  🚨 异常: {error_text}")
        if last_error:
            self.light.setObjectName("FooterLightError")
        elif action_status and action_status not in ("空闲", "idle"):
            self.light.setObjectName("FooterLightWarn")
        else:
            self.light.setObjectName("FooterLightOk")
        self.light.style().unpolish(self.light)
        self.light.style().polish(self.light)
