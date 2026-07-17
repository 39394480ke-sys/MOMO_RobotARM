"""Agent 工具调用安全策略。

这一层只校验工具请求，不直接控制机械臂。真正动作统一通过阶段八 Web API。
"""

from __future__ import annotations

import math
from typing import Any

from .工具定义_robot_tools import ALLOWED_JOINT_NAMES, JOINT_ALIAS, SUPPORTED_BEHAVIORS
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_http import HTTPJsonError, request_json_object  # noqa: E402


ALWAYS_ALLOWED = {"get_robot_state", "stop_robot"}

JOINT_RULES: dict[str, dict[str, Any]] = {
    "j10": {"unit": "mm", "modes": {"relative", "absolute"}, "minimum": -50.0, "maximum": 50.0},
    "j11": {"unit": "deg", "modes": {"relative", "absolute"}, "minimum": -180.0, "maximum": 180.0},
    "j12": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j13": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j14": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j15": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
}


def normalize_joint_name(name: str) -> str:
    value = str(name).strip()
    if value not in ALLOWED_JOINT_NAMES:
        raise ValueError(f"不支持的关节名称：{name}")
    return JOINT_ALIAS.get(value, value)


class SafetyPolicy:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.safety = config.get("safety", {})

    def check(self, tool_name: str, arguments: dict[str, Any], robot_mode: str | None = None) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON 对象。")
        if self._contains_forbidden_raw(arguments):
            raise ValueError("Agent 不允许提供 raw 舵机值。")
        if tool_name not in set(self.safety.get("allowed_tools", [])):
            raise ValueError(f"未知或未授权工具：{tool_name}")
        if tool_name in ALWAYS_ALLOWED:
            return dict(arguments)

        mode = str(robot_mode or self.config.get("robot_api", {}).get("default_mode", "dry_run"))
        if mode == "real" and not bool(self.safety.get("allow_real_robot_tools", False)):
            raise ValueError("当前是真实模式，Agent 默认禁止移动真实机械臂；请改为 dry-run 或在配置中显式开启。")

        match tool_name:
            case "set_gripper":
                return self._check_gripper(arguments)
            case "move_joint":
                return self._check_move_joint_shape(arguments)
            case "rotate_joint":
                return self._check_rotate_joint(arguments)
            case "run_robot_behavior":
                return self._check_behavior(arguments)
            case "play_action":
                return self._check_play_action(arguments)
            case "start_face_follow" | "stop_face_follow":
                return {}
            case _:
                raise ValueError(f"未知工具：{tool_name}")

    def check_api_available(self) -> tuple[bool, str]:
        base_url = str(self.config.get("robot_api", {}).get("base_url", "http://127.0.0.1:8010")).rstrip("/")
        timeout = float(self.config.get("robot_api", {}).get("timeout_sec", 6))
        try:
            request_json_object(f"{base_url}/api/v1/health", timeout=timeout, trust_env=False)
            return True, ""
        except (HTTPJsonError, OSError, TimeoutError, ValueError):
            return False, "机器人控制 API 不可用，请先启动阶段八 Web 服务。"

    def _check_gripper(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            open_ratio = float(arguments["open_ratio"])
        except Exception as exc:
            raise ValueError("set_gripper 需要 open_ratio，范围 0 到 1。") from exc
        if not 0.0 <= open_ratio <= 1.0:
            raise ValueError("set_gripper 的 open_ratio 必须在 0 到 1 之间。")
        return {"open_ratio": open_ratio}

    def _check_rotate_joint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        joint = normalize_joint_name(str(arguments.get("joint_name", "")))
        if "gripper" in joint.lower():
            raise ValueError("夹爪不能通过 rotate_joint 控制，请使用 set_gripper。")
        try:
            delta = float(arguments["delta_deg"])
        except Exception as exc:
            raise ValueError("rotate_joint 需要 delta_deg 数字参数。") from exc
        if not math.isfinite(delta):
            raise ValueError("关节运动数值必须是有限数字。")
        return {"joint_name": joint, "delta_deg": delta}

    def _check_move_joint_shape(self, arguments: dict[str, Any]) -> dict[str, Any]:
        joint = normalize_joint_name(str(arguments.get("joint_name", "")))
        mode = str(arguments.get("mode", "")).strip().lower()
        if mode not in {"relative", "absolute"}:
            raise ValueError("move_joint.mode 必须是 relative 或 absolute。")
        try:
            value = float(arguments["value"])
        except Exception as exc:
            raise ValueError("move_joint 需要数字 value。") from exc
        if not math.isfinite(value):
            raise ValueError("关节运动数值必须是有限数字。")
        return {"joint_name": joint, "mode": mode, "value": value}

    def validate_move_joint(
        self,
        arguments: dict[str, Any],
        current_joints: dict[str, Any],
        *,
        legacy: bool = False,
    ) -> dict[str, Any]:
        if self._contains_forbidden_raw(arguments):
            raise ValueError("Agent 不允许提供 raw 舵机值。")
        if legacy:
            normalized = self._check_move_joint_shape(
                {
                    "joint_name": arguments.get("joint_name"),
                    "mode": "relative",
                    "value": arguments.get("delta_deg"),
                }
            )
        else:
            normalized = self._check_move_joint_shape(arguments)
        joint = normalized["joint_name"]
        mode = normalized["mode"]
        value = float(normalized["value"])
        rule = JOINT_RULES[joint]
        if mode not in rule["modes"]:
            raise ValueError(f"{joint.upper()} 不支持 {mode} 模式。")
        try:
            current = float(current_joints[joint])
        except Exception as exc:
            raise ValueError(f"无法读取 {joint.upper()} 当前值。") from exc
        if not math.isfinite(current):
            raise ValueError(f"{joint.upper()} 当前值不是有限数字。")
        target = value if mode == "absolute" else current + value
        delta = target - current
        if not math.isfinite(target):
            raise ValueError("关节运动目标必须是有限数字。")
        max_delta = rule.get("max_delta")
        if max_delta is not None and abs(delta) > float(max_delta):
            raise ValueError(f"{joint.upper()} 单次运动不能超过 ±{float(max_delta):g}°。")
        minimum = rule.get("minimum")
        maximum = rule.get("maximum")
        if minimum is not None and maximum is not None and not float(minimum) <= target <= float(maximum):
            suffix = "mm" if rule["unit"] == "mm" else "°"
            raise ValueError(f"{joint.upper()} 目标 {target:g}{suffix} 超出安全范围 {minimum:g} 到 {maximum:g}{suffix}。")
        return {
            "joint_name": joint,
            "mode": mode,
            "value": value,
            "current_value": current,
            "delta": delta,
            "target": target,
            "unit": rule["unit"],
        }

    def _check_behavior(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip()
        if name not in SUPPORTED_BEHAVIORS:
            raise ValueError(f"不支持的内置行为：{name}")
        return {"name": name}

    def _check_play_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip()
        if not name:
            raise ValueError("play_action 需要动作名称。")
        return {
            "name": name,
            "speed": float(arguments.get("speed", 1.0)),
            "loop": bool(arguments.get("loop", False)),
        }

    def _contains_forbidden_raw(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key).lower() in {"raw", "raw_value", "raw_values", "servo_raw", "position_raw"}:
                    return True
                if self._contains_forbidden_raw(nested):
                    return True
        elif isinstance(value, list):
            return any(self._contains_forbidden_raw(item) for item in value)
        return False
