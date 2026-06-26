"""GUI 全局状态。

这个 Store 只保存界面需要展示的状态，不直接控制机械臂。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gui_app.结果格式化_result_format import result_message


@dataclass
class GUIState:
    mode: str = "dry_run"
    connected: bool = False
    connection_text: str = "未连接"
    calibration_ok: bool = False
    action_status: str = "空闲"
    last_message: str = ""
    last_error: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    tcp_pose: dict[str, Any] = field(default_factory=dict)


class AppStore:
    """简单状态容器，主窗口和页面共享。"""

    def __init__(self) -> None:
        self.gui_state = GUIState()

    def update_from_result(self, result: dict[str, Any]) -> None:
        if result.get("ok"):
            self.gui_state.last_message = result_message(result, "")
            self.gui_state.last_error = ""
        else:
            self.gui_state.last_error = result_message(result, "")

    def set_state_payload(self, payload: dict[str, Any]) -> None:
        self.gui_state.state = payload
        self.gui_state.connected = bool(payload.get("connected", payload.get("已连接", self.gui_state.connected)))
        self.gui_state.connection_text = "已连接" if self.gui_state.connected else "未连接"
