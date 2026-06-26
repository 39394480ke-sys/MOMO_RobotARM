"""安全工具到阶段八 Web API 的桥接。"""

from __future__ import annotations

from typing import Any

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import api_error_info, clamp01, real_confirm_required, real_confirm_text, tool_result_fail, tool_result_ok, unwrap_api_data  # noqa: E402
from 通用_http import HTTPJsonError, request_json_object  # noqa: E402

from .安全策略_safety_policy import SafetyPolicy


class RobotToolBridge:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.policy = SafetyPolicy(config)
        self.base_url = str(config.get("robot_api", {}).get("base_url", "http://127.0.0.1:8010")).rstrip("/")
        self.timeout = float(config.get("robot_api", {}).get("timeout_sec", 6))
        self.confirm_text = real_confirm_text(config, "confirm_text", "real_confirm_text")

    def execute(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            default_mode = str(self.config.get("robot_api", {}).get("default_mode", "dry_run"))
            safe_args = self.policy.check(tool_name, args, robot_mode=default_mode)
            if tool_name not in {"get_robot_state", "stop_robot"}:
                ok, message = self.policy.check_api_available()
                if not ok:
                    return tool_result_fail(tool_name, message)
            mode = self._current_mode()
            safe_args = self.policy.check(tool_name, args, robot_mode=mode)
            result = self._dispatch(tool_name, safe_args)
            return tool_result_ok(tool_name, result)
        except ConnectionError:
            return tool_result_fail(tool_name, "机器人控制 API 不可用，请先启动阶段八 Web 服务。")
        except Exception as exc:
            return tool_result_fail(tool_name, f"工具调用失败：{exc}")

    def _dispatch(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        match tool_name:
            case "get_robot_state":
                return self._get("/api/v1/robot/state")
            case "stop_robot":
                return self._post("/api/v1/motion/stop", None)
            case "set_gripper":
                return self._post("/api/v1/motion/gripper", self._gripper_payload(float(args["open_ratio"])))
            case "rotate_joint":
                payload = {
                    "joint_key": args["joint_name"],
                    "delta_deg": args["delta_deg"],
                    "speed_percent": 50,
                    "confirm_text": self._confirm_if_real(),
                }
                return self._post("/api/v1/motion/joint-step", payload)
            case "run_robot_behavior":
                return self._run_behavior(args["name"])
            case "play_action":
                self._ensure_action_exists(args["name"])
                payload = {
                    "name": args["name"],
                    "speed": args.get("speed", 1.0),
                    "loop": args.get("loop", False),
                    "confirm_text": self._confirm_if_real(),
                }
                return self._post("/api/v1/actions/play", payload)
            case "start_face_follow":
                payload = {"dry_run": True, "confirm_text": ""}
                return self._post("/api/v1/follow/start", payload)
            case "stop_face_follow":
                return self._post("/api/v1/follow/stop", None)
            case _:
                raise ValueError(f"未知工具：{tool_name}")

    def _run_behavior(self, name: str) -> dict[str, Any]:
        if name == "home":
            return self._post("/api/v1/motion/home", {"speed_percent": 50, "confirm_text": self._confirm_if_real()})
        if name == "open_gripper":
            return self._post("/api/v1/motion/gripper", self._gripper_payload(1.0))
        if name == "close_gripper":
            return self._post("/api/v1/motion/gripper", self._gripper_payload(0.0))
        raise ValueError(f"不支持的内置行为：{name}")

    def _ensure_action_exists(self, name: str) -> None:
        data = self._get("/api/v1/actions")
        actions = data.get("actions", data.get("items", data.get("list", [])))
        names: set[str] = set()
        if isinstance(actions, list):
            for item in actions:
                if isinstance(item, dict):
                    names.add(str(item.get("name") or item.get("title") or ""))
                else:
                    names.add(str(item))
        if actions and name not in names:
            raise ValueError(f"动作库里不存在动作：{name}")

    def _current_mode(self) -> str:
        try:
            data = self._get("/api/v1/session/status")
            return str(data.get("mode") or self.config.get("robot_api", {}).get("default_mode", "dry_run"))
        except Exception:
            return str(self.config.get("robot_api", {}).get("default_mode", "dry_run"))

    def _confirm_if_real(self) -> str:
        if self._current_mode() == "real" and real_confirm_required(self.config, key="require_confirm_for_real"):
            return self.confirm_text
        return ""

    def _gripper_payload(self, open_ratio: float) -> dict[str, Any]:
        return {"open_ratio": clamp01(open_ratio), "wait": True, "confirm_text": self._confirm_if_real()}

    def _get(self, path: str) -> dict[str, Any]:
        return self._request_api("GET", path)

    def _post(self, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self._request_api("POST", path, payload or {})

    def _request_api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = request_json_object(
                f"{self.base_url}{path}",
                method=method,
                payload=payload,
                timeout=self.timeout,
                trust_env=False,
            )
        except HTTPJsonError as exc:
            if exc.status is None:
                raise ConnectionError(str(exc)) from exc
            return self._raise_api_error(exc.payload, exc.text)
        try:
            return unwrap_api_data(response, "阶段八 API 请求失败。")
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    def _raise_api_error(self, payload: Any, fallback: str) -> dict[str, Any]:
        info = api_error_info(payload, fallback)
        raise RuntimeError(str(info.get("message") or fallback))


def execute_tool(config: dict[str, Any], tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return RobotToolBridge(config).execute(tool_name, arguments)
