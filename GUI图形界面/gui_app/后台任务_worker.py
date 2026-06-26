"""PyQt 后台任务。

真实连接、移动、动作播放和状态轮询都放到线程里，避免 GUI 卡住。
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QThread, pyqtSignal

from gui_app.path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import result_fail as fail, tool_result_fail, tool_result_ok  # noqa: E402
from gui_app.结果格式化_result_format import result_message  # noqa: E402


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
                self.error_result.emit(result if isinstance(result, dict) else fail(str(result)))
        except Exception as exc:
            self.error_result.emit(fail(f"后台任务失败：{exc}", exc))


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


class GuiRobotToolBridge:
    """Agent tool adapter that calls the current GUI ControllerBridge."""

    def __init__(self, config: dict[str, Any], gui_bridge: Any):
        self.config = config
        self.gui_bridge = gui_bridge
        from agent.安全策略_safety_policy import SafetyPolicy

        self.policy = SafetyPolicy(config)

    def execute(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            mode = str(self.gui_bridge.get_mode())
            safe_args = self.policy.check(tool_name, args, robot_mode=mode)
            result = self._dispatch(tool_name, safe_args)
            if not result.get("ok", True):
                return tool_result_fail(tool_name, result_message(result))
            return tool_result_ok(tool_name, result.get("data", result), result_message(result, "GUI 工具调用成功。"))
        except Exception as exc:
            return tool_result_fail(tool_name, f"GUI 工具调用失败：{exc}")

    def _dispatch(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        match tool_name:
            case "get_robot_state":
                return self.gui_bridge.get_state()
            case "stop_robot":
                return self.gui_bridge.stop()
            case "set_gripper":
                return self.gui_bridge.set_gripper(float(args["open_ratio"]) * 100.0)
            case "rotate_joint":
                return self.gui_bridge.move_joint_delta(str(args["joint_name"]), float(args["delta_deg"]))
            case "run_robot_behavior":
                return self._run_behavior(str(args["name"]))
            case "play_action":
                return self.gui_bridge.play_action(str(args["name"]))
            case "start_face_follow" | "stop_face_follow":
                return {"ok": False, "message": "GUI AI 暂未直接接管视觉跟随，请使用视觉跟随页面。"}
            case _:
                raise ValueError(f"未知工具：{tool_name}")

    def _run_behavior(self, name: str) -> dict[str, Any]:
        if name == "home":
            return self.gui_bridge.home()
        if name == "open_gripper":
            return self.gui_bridge.set_gripper(100.0)
        if name == "close_gripper":
            return self.gui_bridge.set_gripper(0.0)
        raise ValueError(f"不支持的内置行为：{name}")


class AgentAskWorker(QThread):
    finished_result = pyqtSignal(dict)
    error_result = pyqtSignal(dict)

    def __init__(self, config: dict[str, Any] | None, text: str, gui_bridge: Any | None = None):
        super().__init__()
        self.config = config
        self.text = text
        self.gui_bridge = gui_bridge

    def run(self) -> None:
        try:
            if not self.config:
                raise RuntimeError("Agent 配置未加载。")
            _install_agent_path(self.config)
            from agent.对话应用_agent_app import AgentApp

            tool_bridge = GuiRobotToolBridge(self.config, self.gui_bridge) if self.gui_bridge is not None else None
            app = AgentApp(self.config, tool_bridge=tool_bridge)
            reply = app.ask_text(self.text, speak=False)
            app.client.close()
            result = _agent_reply_result(reply, "AI 回复已生成。")
            _emit_agent_result(self, result)
        except Exception as exc:
            self.error_result.emit(fail(f"AI 对话失败：{exc}", exc))


class AgentVoiceWorker(QThread):
    finished_result = pyqtSignal(dict)
    error_result = pyqtSignal(dict)

    def __init__(self, config: dict[str, Any] | None, gui_bridge: Any | None = None):
        super().__init__()
        self.config = config
        self.gui_bridge = gui_bridge

    def run(self) -> None:
        try:
            if not self.config:
                raise RuntimeError("Agent 配置未加载。")
            _install_agent_path(self.config)
            from agent.对话应用_agent_app import AgentApp

            tool_bridge = GuiRobotToolBridge(self.config, self.gui_bridge) if self.gui_bridge is not None else None
            app = AgentApp(self.config, tool_bridge=tool_bridge)
            speak = bool(self.config.get("tts", {}).get("enabled", True))
            reply = app.run_voice_turn(speak=speak)
            app.client.close()
            result = _agent_reply_result(reply, "语音回合已完成。")
            _emit_agent_result(self, result)
        except Exception as exc:
            self.error_result.emit(fail(f"语音回合失败：{exc}", exc))


def _install_agent_path(config: dict[str, Any]) -> None:
    base_dir = Path(config.get("_base_dir") or "").resolve()
    if base_dir.exists() and str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))


def _agent_reply_result(reply: Any, message: str) -> dict[str, Any]:
    text = str(getattr(reply, "text", "") or "")
    raw_payload = getattr(reply, "raw_payload", {}) or {}
    ok = not (isinstance(raw_payload, dict) and raw_payload.get("error"))
    return {
        "ok": ok,
        "message": message if ok else text or "Agent 处理失败。",
        "data": {
            "reply": text,
            "session_id": str(getattr(reply, "session_id", "") or ""),
            "raw_payload": raw_payload,
        },
    }


def _emit_agent_result(worker: QThread, result: dict[str, Any]) -> None:
    if result.get("ok"):
        worker.finished_result.emit(result)  # type: ignore[attr-defined]
    else:
        worker.error_result.emit(result)  # type: ignore[attr-defined]
