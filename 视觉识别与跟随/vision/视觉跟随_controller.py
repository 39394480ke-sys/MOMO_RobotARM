"""视觉跟随控制器。

该控制器只读取视觉结果并生成小幅 joint-step 命令，执行时也只调用阶段八 Web API。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .路径工具_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    FOLLOW_JOINT_AXES,
    RailSweepPlanner,
    compute_axis_step,
    normalize_joint_key,
    read_smoothed_offset,
    unwrap_vision_payload,
    vision_target_guard,
)

from .WebAPI客户端_robot_api_client import RobotAPIClient, fetch_json_url


class VisionFollowController:
    def __init__(
        self,
        config: dict[str, Any],
        engine: Any | None = None,
        latest_url: str | None = None,
        latest_provider: Callable[[], dict[str, Any]] | None = None,
        dry_run: bool | None = None,
    ):
        self.config = dict(config or {})
        self.follow_cfg = dict(self.config.get("follow", self.config))
        self.engine = engine
        self.latest_url = latest_url or str(self.follow_cfg.get("latest_url", "http://127.0.0.1:8000/latest"))
        self.latest_provider = latest_provider
        self.poll_interval_sec = float(self.follow_cfg.get("poll_interval_sec", self.follow_cfg.get("poll_interval", 0.08)))
        self.http_timeout_sec = float(self.follow_cfg.get("http_timeout_sec", 1.0))
        self.move_duration_sec = float(self.follow_cfg.get("move_duration_sec", self.follow_cfg.get("move_duration", 0.20)))
        self.command_mode = str(self.follow_cfg.get("command_mode", "stream"))
        self.speed_percent = int(self.follow_cfg.get("speed_percent", 50))
        self.dry_run = bool(self.follow_cfg.get("dry_run_default", True) if dry_run is None else dry_run)
        self.robot_client = RobotAPIClient(
            str(self.follow_cfg.get("robot_api_base", "http://127.0.0.1:8010")),
            timeout_sec=self.http_timeout_sec,
            confirm_text=str(self.follow_cfg.get("confirm_text", "")),
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._pan_active = False
        self._tilt_active = False
        self._joint_active: dict[str, bool] = {joint: False for joint in FOLLOW_JOINT_AXES}
        self._last_command: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error = ""
        self._step_count = 0
        self._last_ndx: float | None = None
        self._last_ndy: float | None = None
        self.rail_cfg = self._load_rail_config()
        self._rail = RailSweepPlanner(
            self.rail_cfg,
            virtual_pos_mm=float(self.rail_cfg.get("start_mm", -140.0)),
            running=bool(self.rail_cfg.get("enabled", False)),
            phase="seek_start",
        )

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self.get_status()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="vision-follow", daemon=True)
            self._thread.start()
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._reset_joint_activity()
        self._rail.stop("idle")
        return self.get_status()

    def step_once(self) -> dict[str, Any]:
        latest = self._read_latest()
        self._last_result = latest
        target_safety = self._target_safety_check(latest)
        if target_safety is not None:
            self._pan_active = False
            self._tilt_active = False
            self._reset_joint_activity()
            return self._remember_command(target_safety)

        offset = read_smoothed_offset(latest)
        if offset is None:
            return self._remember_noop("invalid_offset", "平滑偏移无效，不下发动作。")
        ndx, ndy = offset
        jump_limit = float(self.follow_cfg.get("target_jump_limit_norm", 0.6))
        if self._last_ndx is not None and self._last_ndy is not None:
            if abs(ndx - self._last_ndx) > jump_limit or abs(ndy - self._last_ndy) > jump_limit:
                self._last_ndx = ndx
                self._last_ndy = ndy
                self._pan_active = False
                self._tilt_active = False
                self._reset_joint_activity()
                return self._remember_noop("target_jump_guard", "目标偏移突然跳变，本帧不下发动作。")
        self._last_ndx = ndx
        self._last_ndy = ndy
        commands: list[dict[str, Any]] = []

        commands.extend(self._selected_follow_joint_commands(ndx, ndy))

        commands.extend(self._rail_commands())

        if not commands:
            return self._remember_noop("dead_zone", "目标在死区内，不下发动作。")

        return self._execute_commands(commands, action="joint_step", ndx=ndx, ndy=ndy)

    def _target_safety_check(self, latest: dict[str, Any]) -> dict[str, Any] | None:
        guard = vision_target_guard(
            latest,
            min_width=float(self.follow_cfg.get("min_target_box_width", 20.0)),
            min_height=float(self.follow_cfg.get("min_target_box_height", 20.0)),
        )
        if guard is None:
            return None
        if guard.get("action") in {"no_target", "target_lost"}:
            self._last_ndx = None
            self._last_ndy = None
        return self._command_result(str(guard.get("action", "target_guard")), str(guard.get("message", "目标不可跟随，不下发动作。")))

    def _execute_commands(self, commands: list[dict[str, Any]], action: str, ndx: float, ndy: float) -> dict[str, Any]:
        responses = []
        if self.dry_run:
            responses = [{"ok": True, "dry_run": True, "message": "dry-run：未调用阶段八 API。", **cmd} for cmd in commands]
        else:
            for cmd in commands:
                responses.append(self.robot_client.joint_step(cmd["joint_key"], cmd["delta_deg"], self.speed_percent))

        self._step_count += 1
        ok = all(bool(item.get("ok", False)) for item in responses)
        if not ok:
            self._last_error = "阶段八 API 返回失败。"
        else:
            self._last_error = ""
        return self._remember_command(
            {
                "ok": ok,
                "action": action,
                "dry_run": self.dry_run,
                "commands": commands,
                "responses": responses,
                "ndx": ndx,
                "ndy": ndy,
                "move_duration_sec": self.move_duration_sec,
                "rail": self._rail_status(),
                "message": "已生成视觉跟随小步进命令。",
            }
        )

    def get_status(self) -> dict[str, Any]:
        latest = self._last_result or {}
        offset = latest.get("offset") or {}
        smoothed = latest.get("smoothed_offset") or {}
        return {
            "running": bool(self._running),
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "dry_run": self.dry_run,
            "latest_url": self.latest_url,
            "robot_api_base": self.robot_client.base_url,
            "effective_config": {
                "poll_interval_sec": self.poll_interval_sec,
                "move_duration_sec": self.move_duration_sec,
                "speed_percent": self.speed_percent,
                "pan_joint": self.follow_cfg.get("pan_joint", "shoulder_pan"),
                "tilt_joint": self.follow_cfg.get("tilt_joint", "elbow_flex"),
                "enabled_follow_joints": self._enabled_follow_joints(),
                "pan_sign": self.follow_cfg.get("pan_sign", 1.0),
                "tilt_sign": self.follow_cfg.get("tilt_sign", -1.0),
                "pan_gain_deg_per_norm": self.follow_cfg.get("pan_gain_deg_per_norm", self.follow_cfg.get("pan_gain", 1.0)),
                "tilt_gain_deg_per_norm": self.follow_cfg.get("tilt_gain_deg_per_norm", self.follow_cfg.get("tilt_gain", 1.0)),
                "pan_dead_zone_norm": self.follow_cfg.get("pan_dead_zone_norm", 0.02),
                "tilt_dead_zone_norm": self.follow_cfg.get("tilt_dead_zone_norm", 0.025),
                "pan_resume_zone_norm": self.follow_cfg.get("pan_resume_zone_norm", self.follow_cfg.get("pan_dead_zone_norm", 0.02)),
                "tilt_resume_zone_norm": self.follow_cfg.get("tilt_resume_zone_norm", self.follow_cfg.get("tilt_dead_zone_norm", 0.025)),
                "max_pan_step_deg": self.follow_cfg.get("max_pan_step_deg", 1.0),
                "max_tilt_step_deg": self.follow_cfg.get("max_tilt_step_deg", 1.0),
                "rail_cinematic": dict(self.rail_cfg),
            },
            "rail": self._rail_status(),
            "pan_active": self._pan_active,
            "tilt_active": self._tilt_active,
            "joint_active": dict(self._joint_active),
            "step_count": self._step_count,
            "last_command": self._last_command,
            "last_vision": {
                "detected": latest.get("detected", False),
                "direction": (latest.get("direction") or {}).get("combined"),
                "offset": {
                    "ndx": offset.get("ndx", 0.0),
                    "ndy": offset.get("ndy", 0.0),
                    "in_dead_zone": offset.get("in_dead_zone", True),
                    "target_center": offset.get("target_center"),
                    "desired_center": offset.get("desired_center"),
                },
                "smoothed_offset": {
                    "ndx": smoothed.get("ndx", 0.0),
                    "ndy": smoothed.get("ndy", 0.0),
                    "valid": smoothed.get("valid", False),
                },
                "message": latest.get("message", ""),
            },
            "last_error": self._last_error,
        }

    def _loop(self) -> None:
        while self._running:
            try:
                self.step_once()
            except Exception as exc:
                self._last_error = str(exc)
                self._remember_command(self._command_result("error", f"视觉跟随异常：{exc}", ok=False))
            time.sleep(max(0.02, self.poll_interval_sec))

    def _read_latest(self) -> dict[str, Any]:
        if self.latest_provider is not None:
            return unwrap_vision_payload(dict(self.latest_provider()))
        if self.engine is not None:
            return unwrap_vision_payload(dict(self.engine.get_latest_result()))
        return unwrap_vision_payload(fetch_json_url(self.latest_url, self.http_timeout_sec))

    def _enabled_follow_joints(self) -> list[str]:
        raw = self.follow_cfg.get("enabled_follow_joints")
        if not isinstance(raw, list) or not raw:
            raw = [self.follow_cfg.get("pan_joint", "j11"), self.follow_cfg.get("tilt_joint", "j13")]
        result: list[str] = []
        for item in raw:
            try:
                joint = normalize_joint_key(str(item))
            except Exception:
                continue
            if joint in FOLLOW_JOINT_AXES and joint not in result:
                result.append(joint)
        return result or ["j11", "j13"]

    def _selected_follow_joint_commands(self, ndx: float, ndy: float) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        selected = set(self._enabled_follow_joints())
        for joint in FOLLOW_JOINT_AXES:
            if joint not in selected:
                self._joint_active[joint] = False
                continue
            axis = FOLLOW_JOINT_AXES[joint]
            if axis == "pan":
                step = self._axis_step_for_joint(
                    joint,
                    ndx,
                    gain_key="pan_gain_deg_per_norm",
                    gain_alias="pan_gain",
                    sign_key="pan_sign",
                    dead_key="pan_dead_zone_norm",
                    resume_key="pan_resume_zone_norm",
                    min_key="min_pan_step_deg",
                    min_zone_key="pan_min_step_zone_norm",
                    max_key="max_pan_step_deg",
                )
            else:
                step = self._axis_step_for_joint(
                    joint,
                    ndy,
                    gain_key="tilt_gain_deg_per_norm",
                    gain_alias="tilt_gain",
                    sign_key="tilt_sign",
                    dead_key="tilt_dead_zone_norm",
                    resume_key="tilt_resume_zone_norm",
                    min_key="min_tilt_step_deg",
                    min_zone_key="tilt_min_step_zone_norm",
                    max_key="max_tilt_step_deg",
                )
            if step is not None:
                commands.append({"joint_key": joint, "delta_deg": step, "kind": "vision_follow", "axis": axis})
        return commands

    def _axis_step(
        self,
        axis: str,
        norm_value: float,
        active_attr: str,
        gain_key: str,
        gain_alias: str,
        sign_key: str,
        dead_key: str,
        resume_key: str,
        min_key: str,
        min_zone_key: str,
        max_key: str,
    ) -> float | None:
        dead_zone = float(self.follow_cfg.get(dead_key, 0.02))
        resume_zone = float(self.follow_cfg.get(resume_key, dead_zone))
        step, next_active = compute_axis_step(
            norm_value,
            active=bool(getattr(self, active_attr)),
            gain=float(self.follow_cfg.get(gain_key, self.follow_cfg.get(gain_alias, 1.0))),
            sign=float(self.follow_cfg.get(sign_key, 1.0)),
            dead=dead_zone,
            resume=resume_zone,
            min_step=float(self.follow_cfg.get(min_key, 0.0)),
            min_zone=float(self.follow_cfg.get(min_zone_key, 1.0)),
            max_step=float(self.follow_cfg.get(max_key, 1.0)),
        )
        setattr(self, active_attr, next_active)
        return step

    def _axis_step_for_joint(
        self,
        joint: str,
        norm_value: float,
        gain_key: str,
        gain_alias: str,
        sign_key: str,
        dead_key: str,
        resume_key: str,
        min_key: str,
        min_zone_key: str,
        max_key: str,
    ) -> float | None:
        dead_zone = float(self.follow_cfg.get(dead_key, 0.02))
        resume_zone = float(self.follow_cfg.get(resume_key, dead_zone))
        step, next_active = compute_axis_step(
            norm_value,
            active=bool(self._joint_active.get(joint, False)),
            gain=float(self.follow_cfg.get(gain_key, self.follow_cfg.get(gain_alias, 1.0))),
            sign=float(self.follow_cfg.get(sign_key, 1.0)),
            dead=dead_zone,
            resume=resume_zone,
            min_step=float(self.follow_cfg.get(min_key, 0.0)),
            min_zone=float(self.follow_cfg.get(min_zone_key, 1.0)),
            max_step=float(self.follow_cfg.get(max_key, 1.0)),
        )
        self._joint_active[joint] = next_active
        return step

    def _reset_joint_activity(self) -> None:
        self._pan_active = False
        self._tilt_active = False
        for joint in self._joint_active:
            self._joint_active[joint] = False

    def _load_rail_config(self) -> dict[str, Any]:
        raw = self.follow_cfg.get("rail_cinematic", {})
        return RailSweepPlanner.normalize_config(raw if isinstance(raw, dict) else {})

    def _rail_step(self) -> float | None:
        if not self._rail.running:
            return None
        return self._rail.step(default_dt_sec=self.poll_interval_sec, live_pos_mm=self._live_rail_mm_for_planner())

    def _rail_commands(self) -> list[dict[str, Any]]:
        rail_step = self._rail_step()
        if rail_step is None:
            return []
        return [{"joint_key": str(self.rail_cfg.get("joint", "j10")), "delta_deg": rail_step, "kind": "rail_cinematic"}]

    def _rail_current_mm(self) -> float:
        return self._rail.current_mm(self._live_rail_mm_for_planner())

    def _live_rail_mm_for_planner(self) -> float | None:
        if self.dry_run:
            return None
        try:
            payload = self.robot_client.get_robot_state()
            data = payload.get("data") if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                joints = data.get("joints_deg") or {}
                if isinstance(joints, dict) and self.rail_cfg.get("joint", "j10") in joints:
                    return float(joints[self.rail_cfg.get("joint", "j10")])
        except Exception:
            pass
        return None

    def _rail_status(self) -> dict[str, Any]:
        return self._rail.status()

    @staticmethod
    def _command_result(action: str, message: str, ok: bool = True, commands: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"ok": bool(ok), "action": str(action), "commands": list(commands or []), "message": str(message)}

    def _remember_noop(self, action: str, message: str) -> dict[str, Any]:
        return self._remember_command(self._command_result(action, message))

    def _remember_command(self, command: dict[str, Any]) -> dict[str, Any]:
        command = dict(command)
        command["timestamp"] = time.time()
        self._last_command = command
        return command
