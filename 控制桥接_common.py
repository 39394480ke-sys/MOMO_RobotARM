"""GUI/Web 控制桥接层共享工具。

这里只放低风险、无界面状态的公共逻辑：关节常量、统一返回结构、
阶段路径安装和 dry-run/real 运行时配置生成。
"""

from __future__ import annotations

import importlib.util
import tempfile
import math
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from 通用_io import atomic_write_json, read_json_object_or_default, read_structured
from 通用路径 import ensure_paths_on_sys_path


JOINT_ORDER = ["j10", "j11", "j12", "j13", "j14", "j15"]
MULTI_TURN_JOINTS = ["j10", "j11", "j12", "j13", "j14", "j15"]
GRIPPER_JOINT = "gripper"
SERVO_IDS = {
    "j10": 10,
    "j11": 11,
    "j12": 12,
    "j13": 13,
    "j14": 14,
    "j15": 15,
    GRIPPER_JOINT: 16,
}
LEGACY_JOINT_ALIASES = {
    "j0": "j10",
    "j1": "j11",
    "j2": "j12",
    "j3": "j13",
    "j4": "j14",
    "j5": "j15",
    "J0": "j10",
    "J1": "j11",
    "J2": "j12",
    "J3": "j13",
    "J4": "j14",
    "J5": "j15",
    "J10": "j10",
    "J11": "j11",
    "J12": "j12",
    "J13": "j13",
    "J14": "j14",
    "J15": "j15",
    "0": "j10",
    "1": "j11",
    "2": "j12",
    "3": "j13",
    "4": "j14",
    "5": "j15",
    "SHOULDER_PAN": "j11",
    "SHOULDER_LIFT": "j12",
    "ELBOW_FLEX": "j13",
    "WRIST_FLEX": "j14",
    "WRIST_ROLL": "j15",
    "shoulder_pan": "j11",
    "shoulder_lift": "j12",
    "elbow_flex": "j13",
    "wrist_flex": "j14",
    "wrist_roll": "j15",
}
URDF_JOINT_NAME_ALIASES = {
    **{joint: joint.upper() for joint in JOINT_ORDER},
    **{alias: joint.upper() for alias, joint in LEGACY_JOINT_ALIASES.items() if joint in JOINT_ORDER},
}
JOINT_LABELS = {
    "j10": "J10 底盘导轨",
    "j11": "J11 底座旋转",
    "j12": "J12 肩部抬升",
    "j13": "J13 肘部弯曲",
    "j14": "J14 腕部俯仰",
    "j15": "J15 腕部旋转",
    GRIPPER_JOINT: "J16 夹爪",
}
COMPACT_JOINT_LABELS = {
    key: value.replace(" ", "_")
    for key, value in JOINT_LABELS.items()
}
IMPORT_NAME_ALIASES = {
    "pyyaml": ["yaml"],
    "opencv-contrib-python": ["cv2"],
    "feetech-servo-sdk": ["feetech_servo_sdk", "feetech", "scservo_sdk"],
    "pyserial": ["serial"],
}
DEFAULT_REAL_CONFIRM_TEXT = "我确认机械臂周围安全"
DEFAULT_MOTION_TUNING = {
    "default_speed_percent": 50.0,
    "quick_step_duration_s": 0.8,
    "quick_step_frames": 12,
    "continuous_update_hz": 20.0,
    "continuous_target_horizon_s": 0.25,
    "playback_update_hz": 20.0,
    "jog_direction_overrides": {joint: 1 for joint in JOINT_ORDER},
}
FOLLOW_JOINT_AXES = {
    "j11": "pan",
    "j12": "tilt",
    "j13": "tilt",
    "j14": "tilt",
    "j15": "pan",
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def clamp_range(value: float, lower: float, upper: float) -> float:
    low = float(lower)
    high = float(upper)
    if low > high:
        low, high = high, low
    return max(low, min(high, float(value)))


def clamp_symmetric(value: float, limit: float) -> float:
    max_abs = abs(float(limit))
    return clamp_range(value, -max_abs, max_abs)


def clamp_percent(value: float) -> float:
    return clamp_range(value, 0.0, 100.0)


def normalize_motion_tuning(
    values: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    *,
    joint_order: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """统一 GUI/Web/动作/AI 运镜可共享的运动调参口径。"""

    source: dict[str, Any] = {}
    if isinstance(values, Mapping):
        source.update(values)
    if isinstance(overrides, Mapping):
        source.update(overrides)
    order = list(joint_order or JOINT_ORDER)

    def read_float(key: str, default: float, low: float, high: float) -> float:
        try:
            value = float(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        return clamp_range(value, low, high)

    def read_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        return int(clamp_range(value, low, high))

    raw_overrides = source.get("jog_direction_overrides", {})
    direction_overrides: dict[str, int] = {}
    if isinstance(raw_overrides, Mapping):
        for joint in order:
            value = raw_overrides.get(joint, raw_overrides.get(str(joint).upper(), 1))
            text = str(value).strip().lower()
            direction_overrides[joint] = -1 if text in {"-1", "负", "反", "reverse"} or value == -1 else 1
    else:
        direction_overrides = {joint: 1 for joint in order}

    return {
        "default_speed_percent": read_float("default_speed_percent", float(DEFAULT_MOTION_TUNING["default_speed_percent"]), 10.0, 100.0),
        "quick_step_duration_s": read_float("quick_step_duration_s", float(DEFAULT_MOTION_TUNING["quick_step_duration_s"]), 0.05, 10.0),
        "quick_step_frames": read_int("quick_step_frames", int(DEFAULT_MOTION_TUNING["quick_step_frames"]), 1, 240),
        "continuous_update_hz": read_float("continuous_update_hz", float(DEFAULT_MOTION_TUNING["continuous_update_hz"]), 2.0, 60.0),
        "continuous_target_horizon_s": read_float("continuous_target_horizon_s", float(DEFAULT_MOTION_TUNING["continuous_target_horizon_s"]), 0.0, 2.0),
        "playback_update_hz": read_float("playback_update_hz", float(DEFAULT_MOTION_TUNING["playback_update_hz"]), 2.0, 60.0),
        "jog_direction_overrides": direction_overrides,
    }


def normalize_motion_speed_percent(value: Any, default: float | None = None) -> float:
    fallback = float(DEFAULT_MOTION_TUNING["default_speed_percent"] if default is None else default)
    try:
        percent = float(value)
    except (TypeError, ValueError):
        percent = fallback
    return clamp_range(percent, 10.0, 100.0)


def motion_speed_scale(value: Any, *, min_scale: float = 0.1, max_scale: float = 1.0) -> float:
    return clamp_range(normalize_motion_speed_percent(value) / 100.0, min_scale, max_scale)


def cinematic_real_speed_percent(value: Any) -> float:
    return clamp_range(normalize_motion_speed_percent(value), 20.0, 35.0)


def normalize_playback_speed(value: Any, default: float = 1.0) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = float(default)
    return clamp_range(speed, 0.1, 3.0)


def smoothstep01(value: float) -> float:
    """0..1 smoothstep easing used by action playback and AI cinematic plans."""

    u = clamp01(value)
    return u * u * (3.0 - 2.0 * u)


def eased_end_progress(
    value: float,
    duration_sec: float,
    ease_sec: float,
    *,
    max_ease_fraction: float = 0.45,
) -> float:
    """首尾 ease、中段匀速的 0..1 进度曲线。"""

    u = clamp01(value)
    duration = float(duration_sec)
    ease = max(0.0, float(ease_sec))
    if ease <= 1e-6 or duration <= 1e-6:
        return u
    ease_fraction = min(float(max_ease_fraction), ease / duration)
    if ease_fraction <= 1e-6:
        return u
    velocity = 1.0 / max(1e-9, 1.0 - ease_fraction)
    ease_distance = 0.5 * velocity * ease_fraction
    if u < ease_fraction:
        return ease_distance * smoothstep01(u / ease_fraction)
    if u > 1.0 - ease_fraction:
        s = (u - (1.0 - ease_fraction)) / ease_fraction
        return 1.0 - ease_distance * (1.0 - smoothstep01(s))
    return ease_distance + velocity * (u - ease_fraction)


def bounded_catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Catmull-Rom interpolation clamped to the local segment endpoints."""

    u = clamp01(t)
    value = 0.5 * (
        (2.0 * float(p1))
        + (-float(p0) + float(p2)) * u
        + (2.0 * float(p0) - 5.0 * float(p1) + 4.0 * float(p2) - float(p3)) * u * u
        + (-float(p0) + 3.0 * float(p1) - 3.0 * float(p2) + float(p3)) * u * u * u
    )
    lower = min(float(p1), float(p2))
    upper = max(float(p1), float(p2))
    return clamp_range(value, lower, upper)


class RailSweepPlanner:
    """Small state machine for J10 rail cinematic sweep commands."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        virtual_pos_mm: float | None = None,
        running: bool | None = None,
        phase: str = "idle",
    ):
        self.config = self.normalize_config(config or {})
        start = float(self.config.get("start_mm", -140.0))
        self.virtual_pos_mm = float(start if virtual_pos_mm is None else virtual_pos_mm)
        self.running = bool(self.config.get("enabled", False) if running is None else running)
        self.phase = str(phase or ("seek_start" if self.running else "idle"))
        self.last_command_at = 0.0
        self.error_message = ""

    @staticmethod
    def normalize_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        cfg = dict(config or {})
        fallback_speed = abs(float(cfg.get("step_mm", 1.0))) / max(0.02, float(cfg.get("interval_sec", 0.20)))
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "joint": str(cfg.get("joint", "j10")),
            "start_mm": float(cfg.get("start_mm", -140.0)),
            "end_mm": float(cfg.get("end_mm", 140.0)),
            "speed_mm_s": abs(float(cfg.get("speed_mm_s", fallback_speed))),
            "bounce": bool(cfg.get("bounce", False)),
        }

    def configure(self, config: Mapping[str, Any]) -> None:
        previous = dict(self.config)
        previous.update(dict(config or {}))
        self.config = self.normalize_config(previous)

    def reset(self, live_pos_mm: float, *, running: bool | None = None, phase: str | None = None) -> None:
        self.running = bool(self.config.get("enabled", False) if running is None else running)
        self.phase = str(phase or ("seek_start" if self.running else "idle"))
        self.virtual_pos_mm = float(live_pos_mm)
        self.last_command_at = 0.0
        self.error_message = ""

    def stop(self, phase: str = "idle") -> None:
        self.running = False
        self.phase = str(phase)

    def mark_error(self, message: str) -> None:
        self.running = False
        self.phase = "error"
        self.error_message = str(message or "J10 命令失败")

    def current_mm(self, live_pos_mm: float | None = None) -> float:
        if live_pos_mm is not None:
            self.virtual_pos_mm = float(live_pos_mm)
        return float(self.virtual_pos_mm)

    def step(self, *, default_dt_sec: float, live_pos_mm: float | None = None, now: float | None = None) -> float | None:
        if not self.running:
            return None
        now_value = time.monotonic() if now is None else float(now)
        if self.last_command_at <= 0:
            dt = max(0.02, float(default_dt_sec))
        else:
            dt = max(0.02, min(0.25, now_value - self.last_command_at))
        self.last_command_at = now_value

        speed_mm_s = max(0.1, float(self.config.get("speed_mm_s", 5.0)))
        start_mm = float(self.config.get("start_mm", -140.0))
        end_mm = float(self.config.get("end_mm", 140.0))
        current_mm = self.current_mm(live_pos_mm)
        max_delta_mm = speed_mm_s * dt

        if self.phase == "seek_start" and abs(current_mm - start_mm) <= max(0.02, max_delta_mm * 0.5):
            self.phase = "sweep"
            self.virtual_pos_mm = start_mm
            current_mm = start_mm

        target_mm = start_mm if self.phase == "seek_start" else end_mm
        delta = self.limited_delta(current_mm, target_mm, max_delta_mm)
        if delta is None:
            if self.phase == "seek_start":
                self.phase = "sweep"
                target_mm = end_mm
                delta = self.limited_delta(start_mm, target_mm, max_delta_mm)
            elif self.config.get("bounce", False):
                self.config["start_mm"], self.config["end_mm"] = end_mm, start_mm
                self.phase = "sweep"
                return None
            else:
                self.stop("finished")
                return None
        if delta is None:
            return None
        self.virtual_pos_mm = current_mm + float(delta)
        return round(float(delta), 4)

    def command(self, *, default_dt_sec: float, live_pos_mm: float | None = None, now: float | None = None) -> list[dict[str, Any]]:
        delta = self.step(default_dt_sec=default_dt_sec, live_pos_mm=live_pos_mm, now=now)
        if delta is None:
            return []
        return [{"joint_key": str(self.config.get("joint", "j10")), "delta_deg": delta, "kind": "rail_cinematic"}]

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.get("enabled", False)),
            "running": bool(self.running),
            "phase": self.phase,
            "joint": self.config.get("joint", "j10"),
            "start_mm": self.config.get("start_mm", -140.0),
            "end_mm": self.config.get("end_mm", 140.0),
            "speed_mm_s": self.config.get("speed_mm_s", 5.0),
            "bounce": self.config.get("bounce", False),
            "virtual_pos_mm": round(float(self.virtual_pos_mm), 4),
        }

    @staticmethod
    def limited_delta(current_mm: float, target_mm: float, max_delta_mm: float) -> float | None:
        remaining = float(target_mm) - float(current_mm)
        if abs(remaining) <= 0.02:
            return None
        max_delta = max(0.02, float(max_delta_mm))
        if abs(remaining) <= max_delta:
            return remaining
        return max_delta if remaining > 0 else -max_delta


def compute_axis_step(
    norm_value: float,
    *,
    active: bool,
    gain: float,
    sign: float,
    dead: float,
    resume: float,
    min_step: float,
    min_zone: float,
    max_step: float,
) -> tuple[float | None, bool]:
    """Compute one vision-follow axis step and the next active state."""

    abs_norm = abs(float(norm_value))
    if active:
        if abs_norm <= float(dead):
            return None, False
    else:
        if abs_norm < float(resume):
            return None, False
        active = True

    raw_step = float(norm_value) * float(gain) * float(sign)
    if abs(raw_step) <= 1e-9:
        return None, active

    step_abs = abs(raw_step)
    if abs_norm >= float(min_zone) and float(min_step) > 0:
        step_abs = max(step_abs, float(min_step))
    step_abs = min(step_abs, float(max_step))
    signed = step_abs if raw_step > 0 else -step_abs
    return round(signed, 4), active


def vision_target_guard(latest: Mapping[str, Any], *, min_width: float = 20.0, min_height: float = 20.0) -> dict[str, str] | None:
    """Return a no-move reason when a vision target is unsafe for follow control."""

    has_target = bool(latest.get("has_target", latest.get("detected", False)))
    tracking_state = str(latest.get("tracking_state", "tracking" if has_target else "idle"))
    if not has_target:
        if tracking_state == "lost":
            return {"action": "target_lost", "message": "目标丢失，不下发动作。"}
        return {"action": "no_target", "message": "没有有效目标，不下发动作。"}
    if tracking_state == "lost":
        return {"action": "target_lost", "message": "目标跟踪状态为 lost，不下发动作。"}

    bbox = latest.get("bbox")
    target = latest.get("target") if isinstance(latest.get("target"), Mapping) else {}
    if bbox is None and isinstance(target, Mapping):
        bbox = target.get("bbox")
    if not bbox:
        return None
    try:
        _x, _y, width, height = [float(value) for value in list(bbox)[:4]]
    except Exception:
        return {"action": "invalid_target_bbox", "message": "目标框无效，不下发动作。"}
    if width < float(min_width) or height < float(min_height):
        return {"action": "target_too_small", "message": "目标框太小，不下发动作。"}
    return None


def read_smoothed_offset(latest: Mapping[str, Any]) -> tuple[float, float] | None:
    """Return valid smoothed ``(ndx, ndy)`` from a vision payload."""

    smoothed = latest.get("smoothed_offset") if isinstance(latest.get("smoothed_offset"), Mapping) else {}
    if not smoothed.get("valid", False):
        return None
    return float(smoothed.get("ndx", 0.0)), float(smoothed.get("ndy", 0.0))


def unwrap_vision_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap either a raw vision result or a standard ``{"ok": true, "data": ...}`` response."""

    data = dict(payload or {})
    if "detected" in data:
        return data
    if data.get("ok") is True and isinstance(data.get("data"), Mapping):
        return dict(data["data"])
    return data


def result_ok(message: str = "成功", data: Any | None = None) -> dict[str, Any]:
    return {"ok": True, "message": str(message), "data": data if data is not None else {}}


def result_fail(message: str, error: Any | None = None, data: Any | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "message": str(message),
        "error": str(error or message),
        "data": data if data is not None else {},
    }


def tool_result_ok(tool_name: str, result: Any | None = None, message: str | None = None) -> dict[str, Any]:
    payload = {"ok": True, "tool": str(tool_name), "result": result if result is not None else {}}
    if message is not None:
        payload["message"] = str(message)
    return payload


def tool_result_fail(tool_name: str, error: Any) -> dict[str, Any]:
    return {"ok": False, "tool": str(tool_name), "error": str(error)}


def sanitize_action_name(name: Any, *, fallback_prefix: str = "GUI录制", max_length: int = 80) -> str:
    """Return a filesystem-safe action name shared by GUI/Web/AI workflows."""

    text = str(name or "").strip()
    if not text:
        text = f"{fallback_prefix}_{time.strftime('%Y%m%d_%H%M%S')}"
    for char in '/\\:*?"<>|':
        text = text.replace(char, "_")
    return text[: max(1, int(max_length))]


def api_success(data: Any | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data if data is not None else {}, "error": None}


def api_error(code: str, message: str, data: Any | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "data": data,
        "error": {"code": str(code), "message": str(message)},
    }


def api_error_info(
    payload: Any,
    fallback_message: str = "请求失败",
    fallback_code: str = "HTTP_ERROR",
) -> dict[str, Any]:
    """从标准 API 响应中提取错误 code/message/data。"""
    if isinstance(payload, Mapping):
        error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
        return {
            "code": str(error.get("code") or payload.get("code") or fallback_code),
            "message": str(error.get("message") or payload.get("message") or fallback_message),
            "data": payload.get("data"),
        }
    return {"code": str(fallback_code), "message": str(fallback_message), "data": None}


def api_error_from_payload(
    payload: Any,
    fallback_message: str = "请求失败",
    fallback_code: str = "HTTP_ERROR",
) -> dict[str, Any]:
    """把任意 API 错误 payload 转成标准失败响应。"""

    info = api_error_info(payload, fallback_message, fallback_code)
    return api_error(str(info["code"]), str(info["message"]), data=info.get("data"))


def unwrap_api_data(payload: Mapping[str, Any], fallback_message: str = "API 请求失败。") -> dict[str, Any]:
    """解包 ``{\"ok\": true, \"data\": ...}``，失败时抛出 ValueError。"""
    if not isinstance(payload, Mapping):
        raise ValueError("API 返回非标准 JSON 对象。")
    if not bool(payload.get("ok", False)):
        raise ValueError(api_error_info(payload, fallback_message).get("message", fallback_message))
    data = payload.get("data", {})
    return data if isinstance(data, dict) else {"value": data}


def normalize_bridge_result(result: Any, default_message: str, data: Any | None = None) -> dict[str, Any]:
    if isinstance(result, dict) and "ok" in result:
        return result
    if hasattr(result, "成功"):
        success = bool(getattr(result, "成功"))
        message = str(getattr(result, "消息", default_message))
        return result_ok(message, data) if success else result_fail(message, data=data)
    if isinstance(result, bool):
        return result_ok(default_message, data) if result else result_fail(default_message, data=data)
    return result_ok(default_message, data)


def normalize_control_mode(mode: str, simulation_value: str = "sim") -> str:
    value = str(mode).strip().lower()
    aliases = {
        "simulation": simulation_value,
        "sim": simulation_value,
        "模拟": simulation_value,
        "仿真": simulation_value,
        "dryrun": "dry_run",
        "dry-run": "dry_run",
        "真实": "real",
    }
    value = aliases.get(value, value)
    valid = {simulation_value, "dry_run", "real"}
    if value not in valid:
        raise ValueError(f"未知模式：{mode}")
    return value


def safety_config(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    value = (config or {}).get("safety", {}) if isinstance(config, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def real_confirm_text(config: Mapping[str, Any] | None, *keys: str) -> str:
    safety = safety_config(config)
    for key in keys or ("real_confirm_text", "confirm_text"):
        value = safety.get(key)
        if value:
            return str(value)
    return DEFAULT_REAL_CONFIRM_TEXT


def real_confirm_required(config: Mapping[str, Any] | None, key: str = "real_mode_requires_confirm") -> bool:
    return bool(safety_config(config).get(key, True))


def real_confirm_matches(config: Mapping[str, Any] | None, confirm_text: str, *keys: str, required_key: str = "real_mode_requires_confirm") -> bool:
    if not real_confirm_required(config, required_key):
        return True
    return str(confirm_text).strip() == real_confirm_text(config, *keys)


def exception_error_text(exc: Exception, include_type: bool = False) -> str:
    if include_type:
        return "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return str(exc)


def exception_traceback(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def build_exception_context(message: str, exc: Exception, *, include_type: bool = False) -> dict[str, str]:
    return {
        "last_error": str(exc),
        "message": f"{message}：{exc}",
        "error": exception_error_text(exc, include_type=include_type),
        "traceback": exception_traceback(exc),
    }


def read_controller_state(controller: Any, prefer_detailed: bool = True) -> dict[str, Any]:
    if controller is None:
        return {}
    method_names = ["get_state"]
    if prefer_detailed:
        method_names.extend(["获取详细状态", "获取当前状态"])
    else:
        method_names.append("获取当前状态")
    for method_name in method_names:
        if hasattr(controller, method_name):
            state = getattr(controller, method_name)()
            return state if isinstance(state, dict) else {}
    return {}


def normalize_joint_key(value: str) -> str:
    text = str(value).strip()
    if text in JOINT_ORDER:
        return text
    alias = LEGACY_JOINT_ALIASES.get(text) or LEGACY_JOINT_ALIASES.get(text.upper())
    if alias:
        return alias
    raise ValueError(f"未知关节：{value}")


def joint_label(joint_key: str, compact: bool = False) -> str:
    labels = COMPACT_JOINT_LABELS if compact else JOINT_LABELS
    return labels.get(str(joint_key), str(joint_key))


def normalize_joint_targets(
    targets: Mapping[str, Any] | list[Any] | tuple[Any, ...] | Any,
    joint_order: list[str] | tuple[str, ...] | None = None,
    *,
    ignore_unknown: bool = False,
    legacy_5_joint_list: bool = False,
    fill_missing: bool = True,
) -> dict[str, float]:
    order = list(joint_order or JOINT_ORDER)
    if isinstance(targets, Mapping):
        normalized = {joint: 0.0 for joint in order}
        for key, value in targets.items():
            try:
                joint = normalize_joint_key(str(key))
            except ValueError:
                if ignore_unknown:
                    continue
                raise
            if joint in normalized:
                normalized[joint] = float(value)
            elif not ignore_unknown:
                raise ValueError(f"关节 {joint} 不在目标关节序列中。")
        return normalized
    if isinstance(targets, (list, tuple)):
        if legacy_5_joint_list and len(targets) == 5 and order == JOINT_ORDER:
            return {joint: float(targets[index - 1]) if index else 0.0 for index, joint in enumerate(order)}
        if fill_missing:
            return {joint: float(targets[index]) if index < len(targets) else 0.0 for index, joint in enumerate(order)}
        return {joint: float(targets[index]) for index, joint in enumerate(order) if index < len(targets)}
    return {joint: 0.0 for joint in order}


def build_motion_progress_payload(
    targets_deg: Mapping[str, Any],
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "source": str(source),
        "targets_deg": {str(joint): float(value) for joint, value in targets_deg.items()},
    }
    payload.update(extra)
    return payload


def safe_call_callback(callback: Any, *args: Any, **kwargs: Any) -> bool:
    if not callable(callback):
        return False
    try:
        callback(*args, **kwargs)
        return True
    except Exception:
        return False


def extract_joints_from_state(
    state: Mapping[str, Any] | Any,
    joint_order: list[str] | tuple[str, ...] | None = None,
    *,
    keys: tuple[str, ...] = ("关节角度", "joints_deg", "joint_targets_deg"),
    ignore_unknown: bool = False,
    legacy_5_joint_list: bool = False,
    fill_missing: bool = True,
) -> dict[str, float]:
    order = list(joint_order or JOINT_ORDER)
    if not isinstance(state, Mapping):
        state = {}
    for key in keys:
        if key not in state:
            continue
        joints_raw = state[key]
        if isinstance(joints_raw, (Mapping, list, tuple)):
            return normalize_joint_targets(
                joints_raw,
                order,
                ignore_unknown=ignore_unknown,
                legacy_5_joint_list=legacy_5_joint_list,
                fill_missing=fill_missing,
            )
    return {joint: 0.0 for joint in order}


def extract_gripper_open_percent(gripper_raw: Any) -> float:
    if isinstance(gripper_raw, Mapping):
        if gripper_raw.get("open_ratio") is not None:
            value = float(gripper_raw.get("open_ratio", 0.5)) * 100.0
        else:
            value = gripper_raw.get("open_percent", gripper_raw.get("open_value", gripper_raw.get("开合", 50.0)))
    elif gripper_raw is None:
        value = 50.0
    else:
        value = gripper_raw
    return clamp_percent(value)


def gripper_available_from_config(mode: str, real_config_path: str | Path) -> bool:
    if str(mode) not in {"dry_run", "real"}:
        return True
    try:
        real_config = read_structured(real_config_path)
        return bool(real_config.get("transport", {}).get("gripper_available", True))
    except Exception:
        return True


def gripper_available_from_state(gripper_raw: Any, fallback_available: bool = True) -> bool:
    if isinstance(gripper_raw, Mapping) and gripper_raw.get("available") is False:
        return False
    return bool(fallback_available)


def normalize_gripper_state(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get("gripper_state", state.get("gripper", state.get("夹爪"))) if isinstance(state, Mapping) else None
    if raw is None:
        return {"available": False}
    if isinstance(raw, Mapping):
        if raw.get("available") is False:
            return {"available": False}
        present_raw = raw.get("present_raw", raw.get("raw", raw.get("goal_raw")))
        open_ratio = raw.get("open_ratio")
        open_percent = raw.get("open_percent", raw.get("open_value", raw.get("开合")))
        payload: dict[str, Any] = {"available": True}
        if present_raw is not None:
            payload["present_raw"] = int(round(float(present_raw)))
        if open_ratio is not None:
            payload["open_ratio"] = float(open_ratio)
            payload["open_percent"] = int(round(float(open_ratio) * 100))
        elif open_percent is not None:
            payload["open_percent"] = int(round(float(open_percent)))
            payload["open_ratio"] = float(open_percent) / 100.0
        return payload
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return {"available": False}
    return {"available": True, "open_ratio": value / 100.0, "open_percent": int(round(value))}


def normalize_multi_turn_state(state: Mapping[str, Any], multi_turn_joints: list[str] | tuple[str, ...]) -> dict[str, dict[str, Any]]:
    source = (state.get("multi_turn_state") or {}) if isinstance(state, Mapping) else {}
    if not isinstance(source, Mapping):
        source = {}
    result: dict[str, dict[str, Any]] = {}
    for joint in multi_turn_joints:
        item = source.get(joint, {})
        if isinstance(item, Mapping):
            current_raw = item.get("current_raw", item.get("present_raw", item.get("goal_raw")))
            relative_raw = item.get("relative_raw")
            continuous_raw = item.get("continuous_raw")
            if continuous_raw is None:
                continuous_raw = relative_raw if relative_raw is not None else 0
            result[joint] = {
                "startup_raw": item.get("startup_raw", item.get("home_present_raw")),
                "current_raw": current_raw,
                "continuous_raw": continuous_raw,
                "relative_raw": relative_raw if relative_raw is not None else continuous_raw,
                "motor_deg": item.get("motor_deg"),
                "joint_deg": item.get("joint_deg"),
                "goal_raw": item.get("goal_raw"),
            }
        else:
            result[joint] = {
                "startup_raw": None,
                "current_raw": None,
                "continuous_raw": 0,
                "relative_raw": 0,
                "motor_deg": None,
                "joint_deg": None,
                "goal_raw": None,
            }
    return result


def normalize_raw_present_position(raw_present_position: Any) -> dict[str, int] | None:
    if raw_present_position is None:
        return None
    try:
        raw_items = dict(raw_present_position).items()
    except (TypeError, ValueError):
        return None
    return {
        str(key): int(round(float(value)))
        for key, value in raw_items
        if value is not None
    }


def gripper_available_for_controller(controller: Any, connected: bool, mode: str, real_config_path: str | Path) -> bool:
    fallback_available = gripper_available_from_config(mode, real_config_path)
    if controller is not None and connected and hasattr(controller, "get_state"):
        try:
            state = read_controller_state(controller, prefer_detailed=False)
            gripper_raw = state.get("夹爪", state.get("gripper", {})) if isinstance(state, Mapping) else {}
            return gripper_available_from_state(gripper_raw, fallback_available)
        except Exception:
            pass
    return fallback_available


def set_controller_gripper(
    controller: Any,
    open_percent: float,
    *,
    connected: bool,
    mode: str,
    real_config_path: str | Path,
    include_open_ratio: bool = False,
) -> dict[str, Any]:
    if not gripper_available_for_controller(controller, connected, mode, real_config_path):
        return result_fail("当前配置中夹爪舵机不可用。")
    value = clamp_percent(open_percent)
    if hasattr(controller, "set_gripper"):
        result = controller.set_gripper(value)
    elif hasattr(controller, "设置夹爪"):
        result = controller.设置夹爪(value)
    else:
        return result_fail("当前控制器不支持夹爪控制。")
    data = {"open_percent": value}
    if include_open_ratio:
        data["open_ratio"] = value / 100.0
    normalized = normalize_bridge_result(result, "夹爪控制完成。", data)
    normalized_data = normalized.setdefault("data", {})
    if isinstance(normalized_data, dict):
        for key, item in data.items():
            normalized_data.setdefault(key, item)
    else:
        normalized["data"] = data
    return normalized


def current_joints_for_controller(controller: Any, prefer_detailed: bool = False) -> dict[str, float]:
    if controller is not None:
        try:
            return extract_joints_from_state(read_controller_state(controller, prefer_detailed=prefer_detailed))
        except Exception:
            pass
    return {joint: 0.0 for joint in JOINT_ORDER}


def normalize_robot_state_payload(
    state: Mapping[str, Any] | Any,
    mode: str,
    connected: bool,
    real_config_path: str | Path,
    *,
    include_gripper_state: bool = False,
    include_open_ratio: bool = False,
) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        state = {}
    gripper_raw = state.get("夹爪", state.get("gripper", state.get("gripper_state", {}) if include_gripper_state else {}))
    open_percent = extract_gripper_open_percent(gripper_raw)
    gripper = {
        "available": gripper_available_from_state(gripper_raw, gripper_available_from_config(mode, real_config_path)),
        "open_percent": float(open_percent),
    }
    if include_open_ratio:
        gripper["open_ratio"] = clamp01(float(open_percent) / 100.0)
    return {
        "mode": str(mode),
        "connected": bool(connected),
        "joints_deg": extract_joints_from_state(state),
        "joint_labels": dict(JOINT_LABELS),
        "gripper": gripper,
        "raw": dict(state),
    }


def targets_to_kinematics_q(targets: Mapping[str, float]) -> list[float]:
    values: list[float] = []
    for joint in JOINT_ORDER:
        value = float(targets.get(joint, 0.0))
        values.append(value / 1000.0 if joint == "j10" else math.radians(value))
    return values


def kinematics_q_to_targets(q_values: list[float] | tuple[float, ...]) -> dict[str, float]:
    targets: dict[str, float] = {}
    for idx, joint in enumerate(JOINT_ORDER):
        value = float(q_values[idx]) if idx < len(q_values) else 0.0
        targets[joint] = value * 1000.0 if joint == "j10" else math.degrees(value)
    return targets


def approximate_tcp_pose(joints: Mapping[str, float]) -> dict[str, Any]:
    """无 PyBullet/URDF 时的只读兜底，不替代阶段五 FK/IK。"""

    rail = float(joints.get("j10", 0.0)) / 1000.0
    base = math.radians(float(joints.get("j11", 0.0)))
    shoulder = math.radians(float(joints.get("j12", 0.0)))
    elbow = math.radians(float(joints.get("j13", 0.0)))
    wrist = math.radians(float(joints.get("j14", 0.0)))
    l1, l2, l3 = 0.12, 0.12, 0.08
    reach = l1 * math.cos(shoulder) + l2 * math.cos(shoulder + elbow) + l3 * math.cos(shoulder + elbow + wrist)
    z = 0.08 + l1 * math.sin(shoulder) + l2 * math.sin(shoulder + elbow) + l3 * math.sin(shoulder + elbow + wrist)
    return {
        "xyz": [round(rail + reach * math.cos(base), 6), round(reach * math.sin(base), 6), round(z, 6)],
        "rpy": [0.0, round(shoulder + elbow + wrist, 6), round(base + math.radians(float(joints.get("j15", 0.0))), 6)],
        "source": "approximate_fk_without_stage5",
    }


def state_tcp_pose(kinematics_model: Any | None, joints: Mapping[str, Any] | Any) -> dict[str, Any]:
    """状态刷新用 TCP 位姿：复用已加载模型，否则不主动加载 PyBullet。"""
    targets = normalize_joint_targets(joints if isinstance(joints, Mapping) else {})
    if kinematics_model is not None:
        pose = kinematics_model.forward(targets_to_kinematics_q(targets))
        pose["source"] = pose.get("source", "stage5_fk_cached")
        return pose
    return approximate_tcp_pose(targets)


def compute_tcp_pose_payload(kinematics_model: Any | None, joints: Mapping[str, Any] | Any) -> dict[str, Any]:
    """显式 TCP 查询：有阶段五模型则精确 FK，否则返回近似兜底。"""

    targets = normalize_joint_targets(joints if isinstance(joints, Mapping) else {})
    if kinematics_model is not None:
        pose = kinematics_model.forward(targets_to_kinematics_q(targets))
        pose["source"] = pose.get("source", "stage5_fk")
    else:
        pose = approximate_tcp_pose(targets)
    return {"tcp_pose": pose}


def build_pose_payload_from_state(state: Mapping[str, Any], default_gripper: float = 50.0) -> dict[str, Any]:
    joints = state.get("joints_deg", {}) if isinstance(state, Mapping) else {}
    gripper = state.get("gripper", {}) if isinstance(state, Mapping) else {}
    if isinstance(gripper, Mapping):
        open_percent = gripper.get("open_percent", default_gripper)
    else:
        open_percent = default_gripper
    return {
        "关节角度": [float(joints.get(joint, 0.0)) if isinstance(joints, Mapping) else 0.0 for joint in JOINT_ORDER],
        "夹爪": float(open_percent),
    }


def save_pose_from_state(manager: Any, name: str, state: Mapping[str, Any], description: str) -> dict[str, Any]:
    payload = build_pose_payload_from_state(state)
    manager.保存姿态(name, payload, description)
    return payload


def delete_pose_from_manager(manager: Any, name: str) -> bool:
    return bool(manager.删除姿态(name))


def list_pose_items(manager: Any, include_description: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name in manager.列出姿态():
        pose = manager.获取姿态(name)
        item = {"name": name, "pose": pose}
        if include_description:
            item["description"] = (pose or {}).get("说明", "") if isinstance(pose, Mapping) else ""
        items.append(item)
    return items


def list_action_items(library: Any) -> list[dict[str, Any]]:
    return [{"name": name, "summary": library.summarize_action(name)} for name in library.list_actions()]


def load_action_detail(library: Any, name: str) -> dict[str, Any]:
    action = library.load_action(name)
    return {"name": name, "summary": library.summarize_action(action), "action": action}


def append_action_pose(sequence: dict[str, Any], pose: dict[str, Any]) -> dict[str, Any]:
    from 动作工具_common import append_sequence_pose

    return append_sequence_pose(sequence, pose)


def refresh_action_pose_count(sequence: dict[str, Any]) -> dict[str, Any]:
    from 动作工具_common import refresh_sequence_pose_count

    return refresh_sequence_pose_count(sequence)


def play_action_from_library(library: Any, player: Any, name: str, speed: float = 1.0, loop: bool = False) -> bool:
    sequence = library.load_action(name)
    return bool(player.play(sequence, loop=bool(loop), speed=float(speed)))


def load_pose_manager(project_root: str | Path, sim_config_path: str | Path) -> Any:
    from 姿态管理_pose_manager import 姿态管理器

    sim_config = read_structured(sim_config_path)
    pose_path = Path(project_root).resolve() / "仿真控制系统" / sim_config.get("文件", {}).get("姿态库", "姿态管理/姿态库.json")
    return 姿态管理器(pose_path, sim_config.get("默认姿态", {}))


def load_action_library(action_config_path: str | Path) -> Any:
    from 动作文件管理_action_library import ActionLibrary
    from 动作工具_common import load_config

    return ActionLibrary(load_config(action_config_path))


def load_sequence_player(controller: Any, action_config_path: str | Path, playback_update_hz: float | None = None) -> Any:
    from 动作回放器_sequence_player import SequencePlayer
    from 动作工具_common import load_config

    config = load_config(action_config_path)
    config.setdefault("safety", {})["require_confirm_before_real_replay"] = False
    if playback_update_hz is not None:
        config.setdefault("playback", {})["update_hz"] = float(playback_update_hz)
    return SequencePlayer(controller, config)


def build_recording_sequence(name: str, source: str, action_config_path: str | Path) -> dict[str, Any]:
    from 动作工具_common import build_empty_sequence, load_config

    config = load_config(action_config_path)
    return build_empty_sequence(name=name, source=source, config=config)


def load_action_recorder(controller: Any, action_config_path: str | Path) -> Any:
    from 动作录制器_action_recorder import ActionRecorder
    from 动作工具_common import load_config

    return ActionRecorder(controller, load_config(action_config_path))


def load_sim_controller(sim_config_path: str | Path) -> Any:
    from 机械臂模型_robot_arm import 机械臂模型

    return 机械臂模型(read_structured(sim_config_path))


def load_real_controller(
    real_config_path: str | Path,
    *,
    dry_run: bool,
    runtime_state_path: str | Path,
    temp_dir_name: str,
    serial_port: str | None = None,
) -> Any:
    from 真实机械臂控制器_real_arm_controller import RealArmController

    runtime_config = make_runtime_real_config(
        real_config_path,
        dry_run=dry_run,
        runtime_state_path=runtime_state_path,
        temp_dir_name=temp_dir_name,
        serial_port=serial_port,
    )
    return RealArmController(runtime_config)


def load_kinematics_model(config_path: str | Path) -> tuple[Any | None, str]:
    try:
        from 运动学模型_kinematics_model import 创建运动学模型

        return 创建运动学模型(config_path, use_gui=False), ""
    except Exception as exc:
        return None, str(exc)


def compute_fk_payload(model: Any | None, joints_deg: Mapping[str, Any] | list[Any] | tuple[Any, ...], allow_approx: bool) -> dict[str, Any]:
    targets = normalize_joint_targets(joints_deg)
    if model is None:
        if not allow_approx:
            raise RuntimeError("运动学模型不可用。")
        pose = approximate_tcp_pose(targets)
    else:
        pose = model.forward(targets_to_kinematics_q(targets))
        pose["source"] = pose.get("source", "stage5_fk")
    return {"tcp_pose": pose, "target_joints_deg": targets, "source": "fk"}


def compute_ik_payload(
    model: Any,
    xyz: list[float],
    rpy: list[float] | None,
    current_joints: Mapping[str, float],
) -> dict[str, Any]:
    ik = model.inverse(
        target_xyz=[float(value) for value in xyz[:3]],
        target_rpy=[float(value) for value in rpy] if rpy is not None else None,
        seed_q_user=targets_to_kinematics_q(current_joints),
    )
    return {"ik": ik, "target_joints_deg": kinematics_q_to_targets(ik["q_user_rad"]), "source": "ik"}


def resolve_calibration_file_path(real_config_path: str | Path, real_config: Mapping[str, Any] | None = None) -> Path:
    config_path = Path(real_config_path).resolve()
    config = real_config or read_structured(config_path)
    cal_path = Path(config.get("calibration", {}).get("path", "标定文件.json"))
    if not cal_path.is_absolute():
        cal_path = config_path.parent / cal_path
    return cal_path


def load_calibration_report(real_config_path: str | Path) -> dict[str, Any]:
    from 标定管理_calibration_manager import CalibrationManager
    from 真实机械臂控制器_real_arm_controller import 读取配置

    config_path = Path(real_config_path).resolve()
    config = 读取配置(config_path)
    cal_path = resolve_calibration_file_path(config_path, config)
    return CalibrationManager(cal_path, config).calibration_report()


def load_calibration_raw_items(real_config_path: str | Path) -> dict[str, Any]:
    config_path = Path(real_config_path).resolve()
    real_config = read_structured(config_path)
    cal_path = resolve_calibration_file_path(config_path, real_config)
    if not cal_path.exists():
        return {}
    data = read_json_object_or_default(cal_path)
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def python_module_available(name: str, aliases: Mapping[str, Iterable[str]] | None = None) -> bool:
    import_names = list((aliases or IMPORT_NAME_ALIASES).get(name, [name]))
    return any(importlib.util.find_spec(import_name) is not None for import_name in import_names)


def check_python_packages(names: Iterable[str], aliases: Mapping[str, Iterable[str]] | None = None) -> dict[str, bool]:
    return {str(name): python_module_available(str(name), aliases=aliases) for name in names}


def check_python_modules(module_names: Iterable[str]) -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = {}
    for module_name in module_names:
        available = python_module_available(str(module_name))
        data[str(module_name)] = {"available": available, "message": "可用" if available else "未安装或不可导入"}
    return data


def resolve_base_path(path_value: str | Path, base_dir: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (Path(base_dir).resolve() / path).resolve()


def resolve_config_path(
    config: Mapping[str, Any],
    base_dir: str | Path,
    key: str,
    label: str,
    fallback_names: list[str] | None = None,
    require_exists: bool = False,
) -> Path:
    value = config.get("controller", {}).get(key)
    if not value:
        raise KeyError(f"{label} 配置缺少 controller.{key}")
    path = resolve_base_path(value, base_dir)
    if path.exists() or not (fallback_names or require_exists):
        return path
    for name in fallback_names or []:
        fallback = path.parent / name
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"配置文件不存在：{path}")


def make_config_resolver(
    config: Mapping[str, Any],
    base_dir: str | Path,
    label: str,
    *,
    require_exists: bool = False,
) -> Callable[[str, list[str] | None], Path]:
    """创建绑定当前 stage 的 controller 配置路径解析器。"""

    def resolve(key: str, fallback_names: list[str] | None = None) -> Path:
        return resolve_config_path(
            config,
            base_dir,
            key,
            label,
            fallback_names=fallback_names,
            require_exists=require_exists,
        )

    return resolve


def stage_import_paths(project_root: str | Path, include_vision: bool = False) -> list[Path]:
    root = Path(project_root).resolve()
    paths = [
        root,
        root / "仿真控制系统",
        root / "仿真控制系统" / "姿态管理",
        root / "真实舵机控制",
        root / "URDF运动学仿真",
        root / "动作录制与回放增强",
    ]
    if include_vision:
        paths.append(root / "视觉识别与跟随")
    return paths


def ensure_import_paths(paths: Iterable[str | Path]) -> None:
    ensure_paths_on_sys_path(paths)


def install_stage_paths(project_root: str | Path, include_vision: bool = False) -> None:
    ensure_import_paths(stage_import_paths(project_root, include_vision=include_vision))


def make_runtime_real_config(
    real_config_path: str | Path,
    dry_run: bool,
    runtime_state_path: str | Path,
    temp_dir_name: str,
    serial_port: str | None = None,
) -> Path:
    """生成只用于本次 GUI/Web 会话的硬件配置副本。

    真实硬件仍由阶段四控制器读取该副本并执行安全/标定逻辑；这里不直接写舵机。
    """

    source = Path(real_config_path).resolve()
    data = read_structured(source)
    transport = data.setdefault("transport", {})
    transport["dry_run"] = bool(dry_run)
    transport["runtime_mode_locked"] = True
    if serial_port:
        transport["port"] = serial_port

    calibration = data.setdefault("calibration", {})
    calibration_path = Path(calibration.get("path", "标定文件.json"))
    if not calibration_path.is_absolute():
        calibration["path"] = str((source.parent / calibration_path).resolve())

    data.setdefault("files", {})["runtime_state"] = str(Path(runtime_state_path).resolve())

    temp_dir = Path(tempfile.gettempdir()) / temp_dir_name
    temp_dir.mkdir(parents=True, exist_ok=True)
    target = temp_dir / ("dry_run_真实配置_runtime.json" if dry_run else "real_真实配置_runtime.json")
    atomic_write_json(target, data)
    return target
