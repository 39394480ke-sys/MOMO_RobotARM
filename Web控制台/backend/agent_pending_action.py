"""AI 真实动作的单次、短时服务端确认状态。"""

from __future__ import annotations

from copy import deepcopy
import secrets
import threading
import time
from typing import Any, Callable


PENDING_NOT_FOUND = "AGENT_PENDING_NOT_FOUND"
PENDING_EXPIRED = "AGENT_PENDING_EXPIRED"
PENDING_ID_MISMATCH = "AGENT_PENDING_ID_MISMATCH"
PENDING_STATE_CHANGED = "AGENT_PENDING_STATE_CHANGED"


class PendingActionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code)


class PendingActionStore:
    """保存当前会话唯一的待确认动作。"""

    def __init__(self, ttl_sec: float = 30.0, clock: Callable[[], float] = time.time):
        self.ttl_sec = float(ttl_sec)
        self.clock = clock
        self._lock = threading.RLock()
        self._action: dict[str, Any] | None = None
        self._last_terminal: tuple[str, str] | None = None

    def create(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        summary: dict[str, Any],
        state_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            now = float(self.clock())
            self._action = {
                "id": secrets.token_urlsafe(24),
                "tool_name": str(tool_name),
                "arguments": deepcopy(arguments),
                "summary": deepcopy(summary),
                "state_snapshot": deepcopy(state_snapshot),
                "created_at": now,
                "expires_at": now + self.ttl_sec,
                "status": "pending",
            }
            self._last_terminal = None
            return self._public(self._action, now)

    def current(self) -> dict[str, Any] | None:
        with self._lock:
            now = float(self.clock())
            if self._action is None:
                return None
            if self._is_expired(self._action, now):
                self._expire_current()
                return None
            return self._public(self._action, now)

    def consume(self, action_id: str, current_snapshot: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now = float(self.clock())
            if self._action is not None and self._is_expired(self._action, now):
                self._expire_current()
            if self._action is None:
                if self._last_terminal and self._last_terminal[0] == PENDING_EXPIRED:
                    raise PendingActionError(*self._last_terminal)
                raise PendingActionError(PENDING_NOT_FOUND, "当前没有待确认动作。")
            if str(action_id) != self._action["id"]:
                raise PendingActionError(PENDING_ID_MISMATCH, "待确认动作已被替换，请确认最新动作。")

            action = self._action
            try:
                self._validate_snapshot(action, current_snapshot)
            except PendingActionError as exc:
                action["status"] = "invalidated"
                action["reason"] = exc.code
                self._action = None
                self._last_terminal = (exc.code, str(exc))
                raise

            action["status"] = "executed"
            action["executed_at"] = now
            self._action = None
            self._last_terminal = None
            return deepcopy(action)

    def invalidate(self, reason: str) -> dict[str, Any] | None:
        with self._lock:
            if self._action is None:
                return None
            action = self._action
            action["status"] = "invalidated"
            action["reason"] = str(reason)
            action["invalidated_at"] = float(self.clock())
            self._action = None
            self._last_terminal = None
            return deepcopy(action)

    def cancel(self, action_id: str) -> dict[str, Any]:
        with self._lock:
            action = self.current()
            if action is None:
                raise PendingActionError(PENDING_NOT_FOUND, "当前没有待确认动作。")
            if action["id"] != str(action_id):
                raise PendingActionError(PENDING_ID_MISMATCH, "待确认动作已被替换，请取消最新动作。")
            action["status"] = "cancelled"
            action["cancelled_at"] = float(self.clock())
            self._action = None
            self._last_terminal = None
            return action

    def _expire_current(self) -> None:
        if self._action is not None:
            self._action["status"] = "expired"
            self._action = None
        self._last_terminal = (PENDING_EXPIRED, "待确认动作已超过 30 秒，请重新生成。")

    @staticmethod
    def _is_expired(action: dict[str, Any], now: float) -> bool:
        return now > float(action["expires_at"])

    @staticmethod
    def _public(action: dict[str, Any], now: float) -> dict[str, Any]:
        payload = deepcopy(action)
        payload.pop("state_snapshot", None)
        payload["remaining_sec"] = max(0.0, round(float(action["expires_at"]) - now, 3))
        return payload

    @staticmethod
    def _validate_snapshot(action: dict[str, Any], current: dict[str, Any]) -> None:
        previous = action.get("state_snapshot", {})
        if str(previous.get("mode")) != str(current.get("mode")):
            raise PendingActionError(PENDING_STATE_CHANGED, "控制模式已变化，请重新生成动作。")
        if bool(previous.get("connected")) != bool(current.get("connected")):
            raise PendingActionError(PENDING_STATE_CHANGED, "连接状态已变化，请重新生成动作。")

        previous_joints = previous.get("joints", {}) if isinstance(previous.get("joints"), dict) else {}
        current_joints = current.get("joints", {}) if isinstance(current.get("joints"), dict) else {}
        tool_name = str(action.get("tool_name", ""))
        arguments = action.get("arguments", {}) if isinstance(action.get("arguments"), dict) else {}
        if tool_name == "move_joint":
            joint_names = [str(arguments.get("joint_name", ""))]
        elif tool_name == "move_joint_plan":
            moves = arguments.get("moves", []) if isinstance(arguments.get("moves"), list) else []
            joint_names = [str(move.get("joint_name", "")) for move in moves if isinstance(move, dict)]
        elif tool_name == "run_robot_behavior" and arguments.get("name") == "home":
            joint_names = list(previous_joints)
        else:
            joint_names = []

        for joint in joint_names:
            if not joint or joint not in previous_joints or joint not in current_joints:
                raise PendingActionError(PENDING_STATE_CHANGED, f"{joint.upper() or '关节'} 状态缺失，请重新生成动作。")
            tolerance = 0.5
            if abs(float(current_joints[joint]) - float(previous_joints[joint])) > tolerance:
                unit = "mm" if joint == "j10" else "°"
                raise PendingActionError(PENDING_STATE_CHANGED, f"{joint.upper()} 位置已变化超过 0.5{unit}，请重新生成动作。")
