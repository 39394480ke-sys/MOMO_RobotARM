"""视觉跟随控制器。

该控制器只读取视觉结果并生成小幅 joint-step 命令，执行时也只调用阶段八 Web API。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any, Callable

from .WebAPI客户端_robot_api_client import RobotAPIClient


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
        self._last_command: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error = ""
        self._step_count = 0

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
        self._pan_active = False
        self._tilt_active = False
        return self.get_status()

    def step_once(self) -> dict[str, Any]:
        latest = self._read_latest()
        self._last_result = latest
        if not latest.get("detected", False):
            self._pan_active = False
            self._tilt_active = False
            return self._remember_command({"ok": True, "action": "no_target", "commands": [], "message": "目标丢失，不下发动作。"})

        smoothed = latest.get("smoothed_offset") or {}
        if not smoothed.get("valid", False):
            return self._remember_command({"ok": True, "action": "invalid_offset", "commands": [], "message": "平滑偏移无效，不下发动作。"})

        ndx = float(smoothed.get("ndx", 0.0))
        ndy = float(smoothed.get("ndy", 0.0))
        commands: list[dict[str, Any]] = []

        pan_step = self._axis_step(
            axis="pan",
            norm_value=ndx,
            active_attr="_pan_active",
            gain_key="pan_gain_deg_per_norm",
            gain_alias="pan_gain",
            sign_key="pan_sign",
            dead_key="pan_dead_zone_norm",
            resume_key="pan_resume_zone_norm",
            min_key="min_pan_step_deg",
            min_zone_key="pan_min_step_zone_norm",
            max_key="max_pan_step_deg",
        )
        if pan_step is not None:
            commands.append({"joint_key": str(self.follow_cfg.get("pan_joint", "shoulder_pan")), "delta_deg": pan_step})

        tilt_step = self._axis_step(
            axis="tilt",
            norm_value=ndy,
            active_attr="_tilt_active",
            gain_key="tilt_gain_deg_per_norm",
            gain_alias="tilt_gain",
            sign_key="tilt_sign",
            dead_key="tilt_dead_zone_norm",
            resume_key="tilt_resume_zone_norm",
            min_key="min_tilt_step_deg",
            min_zone_key="tilt_min_step_zone_norm",
            max_key="max_tilt_step_deg",
        )
        if tilt_step is not None:
            commands.append({"joint_key": str(self.follow_cfg.get("tilt_joint", "elbow_flex")), "delta_deg": tilt_step})

        if not commands:
            return self._remember_command({"ok": True, "action": "dead_zone", "commands": [], "message": "目标在死区内，不下发动作。"})

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
                "action": "joint_step",
                "dry_run": self.dry_run,
                "commands": commands,
                "responses": responses,
                "ndx": ndx,
                "ndy": ndy,
                "move_duration_sec": self.move_duration_sec,
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
            },
            "pan_active": self._pan_active,
            "tilt_active": self._tilt_active,
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
                self._remember_command({"ok": False, "action": "error", "commands": [], "message": f"视觉跟随异常：{exc}"})
            time.sleep(max(0.02, self.poll_interval_sec))

    def _read_latest(self) -> dict[str, Any]:
        if self.latest_provider is not None:
            return self._unwrap_latest(dict(self.latest_provider()))
        if self.engine is not None:
            return self._unwrap_latest(dict(self.engine.get_latest_result()))
        request = urllib.request.Request(self.latest_url, method="GET")
        with urllib.request.urlopen(request, timeout=self.http_timeout_sec) as response:
            return self._unwrap_latest(json.loads(response.read().decode("utf-8")))

    @staticmethod
    def _unwrap_latest(payload: dict[str, Any]) -> dict[str, Any]:
        if "detected" in payload:
            return payload
        if payload.get("ok") is True and isinstance(payload.get("data"), dict):
            return dict(payload["data"])
        return payload

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
        active = bool(getattr(self, active_attr))
        abs_norm = abs(float(norm_value))
        dead_zone = float(self.follow_cfg.get(dead_key, 0.02))
        resume_zone = float(self.follow_cfg.get(resume_key, dead_zone))

        if active:
            if abs_norm <= dead_zone:
                setattr(self, active_attr, False)
                return None
        else:
            if abs_norm < resume_zone:
                return None
            setattr(self, active_attr, True)

        gain = float(self.follow_cfg.get(gain_key, self.follow_cfg.get(gain_alias, 1.0)))
        sign = float(self.follow_cfg.get(sign_key, 1.0))
        raw_step = float(norm_value) * gain * sign
        if abs(raw_step) <= 1e-9:
            return None

        min_step = float(self.follow_cfg.get(min_key, 0.0))
        min_zone = float(self.follow_cfg.get(min_zone_key, 1.0))
        max_step = float(self.follow_cfg.get(max_key, 1.0))

        step_abs = abs(raw_step)
        if abs_norm >= min_zone and min_step > 0:
            step_abs = max(step_abs, min_step)
        step_abs = min(step_abs, max_step)
        signed = step_abs if raw_step > 0 else -step_abs
        return round(signed, 4)

    def _remember_command(self, command: dict[str, Any]) -> dict[str, Any]:
        command = dict(command)
        command["timestamp"] = time.time()
        self._last_command = command
        return command
