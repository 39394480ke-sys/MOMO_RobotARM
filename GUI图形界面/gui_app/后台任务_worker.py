"""PyQt 后台任务。

真实连接、移动、动作播放和状态轮询都放到线程里，避免 GUI 卡住。
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QThread, pyqtSignal


class BridgeWorker(QThread):
    finished_result = pyqtSignal(dict)
    error_result = pyqtSignal(dict)

    def __init__(self, task: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            result = self.task(*self.args, **self.kwargs)
            if isinstance(result, dict) and result.get("ok"):
                self.finished_result.emit(result)
            else:
                self.error_result.emit(result if isinstance(result, dict) else {"ok": False, "message": str(result)})
        except Exception as exc:
            self.error_result.emit({"ok": False, "message": f"后台任务失败：{exc}", "error": str(exc)})


class ConnectWorker(BridgeWorker):
    pass


class MoveWorker(BridgeWorker):
    pass


class ActionPlayWorker(BridgeWorker):
    pass


class CalibrationStatusWorker(BridgeWorker):
    pass


class StatePollWorker(BridgeWorker):
    pass

