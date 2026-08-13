"""视觉跟随控制器。

该控制器只读取视觉结果并生成小幅 joint-step 命令，执行时也只调用阶段八 Web API。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
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
from .连续跟随_control import ContinuousFollowPlanner


MANUAL_TRACKER_PROFILE = {
    "gain_scale": 1.0,
    "max_step_deg": 0.0,
    "min_step_deg": -1.0,
    "dead_zone_norm": 0.06,
    "resume_zone_norm": 0.10,
    "min_step_zone_norm": -1.0,
}

SPEED_BASELINE_PERCENT = 60.0
MIN_SPEED_STEP_SCALE = 0.2
MAX_SPEED_STEP_SCALE = 2.0


class VisionFollowController:
    def __init__(
        self,
        config: dict[str, Any],
        engine: Any | None = None,
        latest_url: str | None = None,
        latest_provider: Callable[[], dict[str, Any]] | None = None,
        dry_run: bool | None = None,
        initial_state_provider: Callable[[], dict[str, float]] | None = None,
        stream_writer: Callable[[dict[str, float]], dict[str, Any]] | None = None,
        stream_sync: Callable[[], dict[str, Any]] | None = None,
    ):
        self.config = dict(config or {})
        self.follow_cfg = dict(self.config.get("follow", self.config))
        self.engine = engine
        self.latest_url = latest_url or str(self.follow_cfg.get("latest_url", "http://127.0.0.1:8000/latest"))
        self.latest_provider = latest_provider
        self.initial_state_provider = initial_state_provider
        self.stream_writer = stream_writer
        self.stream_sync = stream_sync
        self.poll_interval_sec = float(self.follow_cfg.get("poll_interval_sec", self.follow_cfg.get("poll_interval", 0.08)))
        self.http_timeout_sec = float(self.follow_cfg.get("http_timeout_sec", 1.0))
        self.move_duration_sec = float(self.follow_cfg.get("move_duration_sec", self.follow_cfg.get("move_duration", 0.20)))
        self.command_mode = str(self.follow_cfg.get("command_mode", "stream"))
        self.speed_percent = int(self.follow_cfg.get("speed_percent", 50))
        self._speed_step_scale = self._calc_speed_step_scale(self.speed_percent)
        self.dry_run = bool(self.follow_cfg.get("dry_run_default", True) if dry_run is None else dry_run)
        self.robot_client = RobotAPIClient(
            str(self.follow_cfg.get("robot_api_base", "http://127.0.0.1:8010")),
            timeout_sec=self.http_timeout_sec,
            confirm_text=str(self.follow_cfg.get("confirm_text", "")),
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self._sample_thread: threading.Thread | None = None
        self._control_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_generation = 0
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
        self._step_latest_source_frame_id: Any = None
        self._manual_axis_command_at: dict[str, float] = {}
        self.control_update_hz = max(2.0, min(60.0, float(self.follow_cfg.get("control_update_hz", 40.0))))
        self.vision_stale_timeout_sec = max(0.05, float(self.follow_cfg.get("vision_stale_timeout_sec", 0.25)))
        self.thread_join_timeout_sec = max(0.05, float(self.follow_cfg.get("thread_join_timeout_sec", 1.0)))
        self._stream_latest: dict[str, Any] = {}
        self._stream_latest_at = 0.0
        self._stream_latest_key: Any = None
        self._stream_targets: dict[str, float] = {}
        self._stream_velocities: dict[str, float] = {}
        self._hold_reason = "starting"
        self._tick_count = 0
        self._write_count = 0
        self._skipped_tick_count = 0
        self._intervals: deque[float] = deque(maxlen=256)
        self._stream_sync_done = False
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
            if self._worker_threads_alive():
                self._hold_reason = "previous_run_still_stopping"
                self._last_error = "上一轮视觉跟随线程尚未退出，已拒绝重新启动。"
                return self.get_status()
            self._run_generation += 1
            generation = self._run_generation
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._reset_run_state_locked()
            self._running = True
            self._last_error = ""
            if self._uses_continuous_stream():
                self._stream_sync_done = False
                self._sample_thread = threading.Thread(
                    target=self._sample_loop,
                    args=(stop_event, generation),
                    name="vision-follow-sample",
                    daemon=True,
                )
                self._control_thread = threading.Thread(
                    target=self._control_loop,
                    args=(stop_event, generation),
                    name="vision-follow-control",
                    daemon=True,
                )
                self._sample_thread.start()
                self._control_thread.start()
                return self.get_status()
            self._thread = threading.Thread(
                target=self._loop,
                args=(stop_event, generation),
                name="vision-follow",
                daemon=True,
            )
            self._thread.start()
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        self.request_stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.thread_join_timeout_sec)
        for thread in (self._sample_thread, self._control_thread):
            if thread and thread.is_alive():
                thread.join(timeout=self.thread_join_timeout_sec)
        self._sync_stream_once()
        self._reset_joint_activity()
        self._rail.stop("idle")
        return self.get_status()

    def request_stop(self) -> None:
        """非阻塞请求停止，供持有 Web 运动锁的互斥路径使用。"""

        with self._lock:
            self._running = False
            self._stop_event.set()

    def _worker_threads_alive(self) -> bool:
        return any(
            thread is not None and thread.is_alive()
            for thread in (self._thread, self._sample_thread, self._control_thread)
        )

    def _reset_run_state_locked(self) -> None:
        self._stream_latest = {}
        self._stream_latest_at = 0.0
        self._stream_latest_key = None
        self._last_result = None
        self._step_latest_source_frame_id = None
        self._stream_targets = {}
        self._stream_velocities = {}
        self._hold_reason = "starting"
        self._last_command = None
        self._last_ndx = None
        self._last_ndy = None
        self._reset_joint_activity()

    def _finish_run(self, generation: int) -> None:
        with self._lock:
            if generation == self._run_generation:
                self._running = False

    def _sync_stream_once(self) -> None:
        if not self._uses_continuous_stream() or self.stream_sync is None:
            return
        with self._lock:
            if self._stream_sync_done:
                return
            self._stream_sync_done = True
        self.stream_sync()

    def step_once(self, stop_event: threading.Event | None = None) -> dict[str, Any]:
        latest = self._read_latest()
        if stop_event is not None and stop_event.is_set():
            self._reset_joint_activity()
            return self._remember_noop("stopping", "视觉跟随正在停止，不下发动作。")
        self._last_result = latest
        freshness_hold = self._vision_freshness_hold_reason(latest)
        if not freshness_hold:
            source_frame_id = latest.get("source_frame_id")
            if source_frame_id == self._step_latest_source_frame_id:
                freshness_hold = "vision_frame_repeated"
            else:
                self._step_latest_source_frame_id = source_frame_id
        if freshness_hold:
            self._last_ndx = None
            self._last_ndy = None
            self._reset_joint_activity()
            return self._remember_noop(freshness_hold, self._freshness_message(freshness_hold))
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

        commands.extend(self._selected_follow_joint_commands(ndx, ndy, latest))

        commands.extend(self._rail_commands())

        if not commands:
            return self._remember_noop("dead_zone", "目标在死区内，不下发动作。")
        if stop_event is not None and stop_event.is_set():
            self._reset_joint_activity()
            return self._remember_noop("stopping", "视觉跟随正在停止，不下发动作。")

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
        intervals = list(self._intervals)
        sorted_intervals = sorted(intervals)
        p95 = sorted_intervals[min(len(sorted_intervals) - 1, int(len(sorted_intervals) * 0.95))] if intervals else 0.0
        mean_interval = sum(intervals) / len(intervals) if intervals else 0.0
        latest_frame_age = self._source_frame_age_sec(latest)
        return {
            "running": bool(self._running),
            "thread_alive": bool(
                (self._thread and self._thread.is_alive())
                or (self._sample_thread and self._sample_thread.is_alive())
                or (self._control_thread and self._control_thread.is_alive())
            ),
            "control_mode": "continuous_position_stream" if self._uses_continuous_stream() else "joint_step",
            "control_update_hz": self.control_update_hz,
            "actual_update_hz": round(1.0 / mean_interval, 3) if mean_interval > 0 else 0.0,
            "mean_interval_ms": round(mean_interval * 1000.0, 3),
            "p95_interval_ms": round(p95 * 1000.0, 3),
            "max_interval_ms": round(max(intervals) * 1000.0, 3) if intervals else 0.0,
            "tick_count": self._tick_count,
            "write_count": self._write_count,
            "skipped_tick_count": self._skipped_tick_count,
            "latest_vision_age_ms": round(latest_frame_age * 1000.0, 3) if latest_frame_age is not None else None,
            "latest_processing_latency_ms": self._milliseconds_or_none(latest.get("processing_latency_sec")),
            "latest_source_frame_id": latest.get("source_frame_id"),
            "dropped_source_frames": latest.get("dropped_source_frames", 0),
            "hold_reason": self._hold_reason,
            "targets_deg": dict(self._stream_targets),
            "velocities_deg_s": dict(self._stream_velocities),
            "dry_run": self.dry_run,
            "latest_url": self.latest_url,
            "robot_api_base": self.robot_client.base_url,
            "effective_config": {
                "poll_interval_sec": self.poll_interval_sec,
                "control_update_hz": self.control_update_hz,
                "vision_stale_timeout_sec": self.vision_stale_timeout_sec,
                "max_pan_speed_deg_s": float(self.follow_cfg.get("max_pan_speed_deg_s", 12.0)),
                "max_tilt_speed_deg_s": float(self.follow_cfg.get("max_tilt_speed_deg_s", 10.0)),
                "pan_accel_deg_s2": float(self.follow_cfg.get("pan_accel_deg_s2", 30.0)),
                "tilt_accel_deg_s2": float(self.follow_cfg.get("tilt_accel_deg_s2", 25.0)),
                "move_duration_sec": self.move_duration_sec,
                "speed_percent": self.speed_percent,
                "speed_step_scale": self._speed_step_scale,
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
                "min_pan_step_deg": self.follow_cfg.get("min_pan_step_deg", 0.0),
                "min_tilt_step_deg": self.follow_cfg.get("min_tilt_step_deg", 0.0),
                "pan_min_step_zone_norm": self.follow_cfg.get("pan_min_step_zone_norm", 1.0),
                "tilt_min_step_zone_norm": self.follow_cfg.get("tilt_min_step_zone_norm", 1.0),
                "max_pan_step_deg": self.follow_cfg.get("max_pan_step_deg", 1.0),
                "max_tilt_step_deg": self.follow_cfg.get("max_tilt_step_deg", 1.0),
                "manual_tracker_profile": self._manual_tracker_profile(),
                "rail_cinematic": dict(self.rail_cfg),
            },
            "rail": self._rail_status(),
            "pan_active": self._pan_active,
            "tilt_active": self._tilt_active,
            "joint_active": dict(self._joint_active),
            "step_count": self._tick_count if self._uses_continuous_stream() else self._step_count,
            "last_command": self._last_command,
            "last_vision": {
                "source_frame_id": latest.get("source_frame_id"),
                "frame_received_at": latest.get("frame_received_at"),
                "processed_at": latest.get("processed_at"),
                "processing_latency_sec": latest.get("processing_latency_sec"),
                "dropped_source_frames": latest.get("dropped_source_frames", 0),
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

    def _loop(self, stop_event: threading.Event, generation: int) -> None:
        while not stop_event.is_set():
            try:
                self.step_once(stop_event=stop_event)
            except Exception as exc:
                self._last_error = str(exc)
                self._remember_command(self._command_result("error", f"视觉跟随异常：{exc}", ok=False))
            stop_event.wait(max(0.02, self.poll_interval_sec))
        self._finish_run(generation)

    def _uses_continuous_stream(self) -> bool:
        return self.command_mode.strip().lower() in {"stream", "continuous", "continuous_position_stream"} and (
            self.dry_run or (self.initial_state_provider is not None and self.stream_writer is not None)
        )

    def _sample_loop(self, stop_event: threading.Event, generation: int) -> None:
        while not stop_event.is_set():
            try:
                latest = self._read_latest()
                now = time.monotonic()
                key = latest.get("source_frame_id")
                with self._lock:
                    if stop_event.is_set() or generation != self._run_generation:
                        break
                    self._stream_latest = latest
                    if key is not None and key != self._stream_latest_key:
                        self._stream_latest_at = now
                        self._stream_latest_key = key
                    self._last_result = latest
            except Exception as exc:
                self._last_error = str(exc)
            stop_event.wait(max(0.01, self.poll_interval_sec))

    def _control_loop(self, stop_event: threading.Event, generation: int) -> None:
        initial = self.initial_state_provider() if self.initial_state_provider is not None else {}
        planner = ContinuousFollowPlanner(self.follow_cfg, initial)
        rail_target = float(initial.get("j10", self._rail.virtual_pos_mm))
        self._rail.reset(rail_target, running=bool(self.rail_cfg.get("enabled", False)), phase="seek_start")
        period = 1.0 / self.control_update_hz
        last_tick = time.monotonic()
        deadline = last_tick + period
        previous_tick: float | None = None
        while not stop_event.is_set():
            if stop_event.wait(max(0.0, deadline - time.monotonic())):
                break
            now = time.monotonic()
            if now - deadline >= period:
                skipped = int((now - deadline) // period)
                self._skipped_tick_count += skipped
                deadline += skipped * period
            dt = max(0.0, now - last_tick)
            last_tick = now
            deadline += period
            if previous_tick is not None:
                self._intervals.append(now - previous_tick)
            previous_tick = now
            with self._lock:
                latest = dict(self._stream_latest)
                latest_at = self._stream_latest_at
            hold = ""
            guard = self._target_safety_check(latest) if latest else self._command_result("no_target", "没有视觉结果。")
            offset = read_smoothed_offset(latest) if latest else None
            freshness_hold = (
                self._vision_freshness_hold_reason(latest, latest_source_seen_at=latest_at, now_monotonic=now)
                if latest
                else "vision_metadata_missing"
            )
            if freshness_hold:
                hold = freshness_hold
            elif guard is not None:
                hold = str(guard.get("action", "target_guard"))
            elif offset is None:
                hold = "invalid_offset"
            ndx, ndy = offset or (0.0, 0.0)
            frame = planner.step(
                ndx,
                ndy,
                dt=dt,
                hold_reason=hold,
                manual_tracker=self._is_manual_tracker(latest),
            )
            targets = dict(frame.targets_deg)
            rail_step = self._rail.step(default_dt_sec=dt, live_pos_mm=rail_target) if self._rail.running else None
            if rail_step is not None:
                rail_target += rail_step
                targets["j10"] = rail_target
            response = {
                "ok": True,
                "dry_run": True,
                "data": {"written_joints": [] if hold else list(targets)},
            }
            if stop_event.is_set():
                break
            if not hold and not self.dry_run and self.stream_writer is not None:
                response = self.stream_writer(targets)
            if stop_event.is_set() or generation != self._run_generation:
                break
            if not hold:
                self._write_count += len(response.get("data", {}).get("written_joints", targets)) if response.get("ok") else 0
            self._tick_count += 1
            self._stream_targets = targets
            self._stream_velocities = dict(frame.velocities_deg_s)
            self._hold_reason = hold
            self._last_command = {
                "ok": bool(response.get("ok", False)),
                "action": "position_stream" if not hold else "hold",
                "targets_deg": targets,
                "velocities_deg_s": dict(frame.velocities_deg_s),
                "hold_reason": hold,
                "response": response,
                "timestamp": time.time(),
            }
            if not response.get("ok", False) and not stop_event.is_set():
                self._last_error = str(response.get("message") or response.get("error") or "连续视觉跟随写入失败。")
                stop_event.set()
                self._finish_run(generation)
        self._finish_run(generation)
        self._sync_stream_once()

    def _read_latest(self) -> dict[str, Any]:
        if self.latest_provider is not None:
            return unwrap_vision_payload(dict(self.latest_provider()))
        if self.engine is not None:
            return unwrap_vision_payload(dict(self.engine.get_latest_result()))
        return unwrap_vision_payload(fetch_json_url(self.latest_url, self.http_timeout_sec))

    def _vision_freshness_hold_reason(
        self,
        latest: dict[str, Any],
        *,
        latest_source_seen_at: float = 0.0,
        now_monotonic: float | None = None,
    ) -> str:
        required = ("source_frame_id", "frame_received_at", "processed_at", "processing_latency_sec")
        if any(latest.get(key) is None for key in required):
            return "vision_metadata_missing"
        if str(latest.get("source_frame_id", "")).strip() == "":
            return "vision_metadata_missing"
        try:
            frame_received_at = float(latest["frame_received_at"])
            processed_at = float(latest["processed_at"])
            reported_latency = float(latest["processing_latency_sec"])
        except (TypeError, ValueError, KeyError):
            return "vision_metadata_invalid"
        if not all(math.isfinite(value) for value in (frame_received_at, processed_at, reported_latency)):
            return "vision_metadata_invalid"
        measured_latency = processed_at - frame_received_at
        if reported_latency < 0.0 or measured_latency < -0.01:
            return "vision_metadata_invalid"
        if max(reported_latency, measured_latency) > self.vision_stale_timeout_sec:
            return "vision_processing_stale"
        frame_age = time.time() - frame_received_at
        if frame_age < -1.0:
            return "vision_metadata_invalid"
        if frame_age > self.vision_stale_timeout_sec:
            return "vision_frame_stale"
        if latest_source_seen_at:
            monotonic_now = time.monotonic() if now_monotonic is None else float(now_monotonic)
            if monotonic_now - latest_source_seen_at > self.vision_stale_timeout_sec:
                return "vision_not_updating"
        return ""

    @staticmethod
    def _source_frame_age_sec(latest: dict[str, Any]) -> float | None:
        try:
            received_at = float(latest.get("frame_received_at"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(received_at):
            return None
        return max(0.0, time.time() - received_at)

    @staticmethod
    def _milliseconds_or_none(value: Any) -> float | None:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(seconds):
            return None
        return round(max(0.0, seconds) * 1000.0, 3)

    @staticmethod
    def _freshness_message(reason: str) -> str:
        messages = {
            "vision_metadata_missing": "视觉结果缺少源帧时间元数据，不下发动作。",
            "vision_metadata_invalid": "视觉结果的源帧时间元数据无效，不下发动作。",
            "vision_frame_repeated": "视觉源帧重复，本次不下发动作。",
            "vision_frame_stale": "视觉源帧已过期，不下发动作。",
            "vision_processing_stale": "视觉帧处理延迟超限，不下发动作。",
            "vision_not_updating": "视觉源帧长时间未更新，不下发动作。",
        }
        return messages.get(reason, "视觉结果不可用，不下发动作。")

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

    def _selected_follow_joint_commands(self, ndx: float, ndy: float, latest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        selected = set(self._enabled_follow_joints())
        manual_tracker = self._is_manual_tracker(latest or {})
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
                    manual_tracker=manual_tracker,
                    axis=axis,
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
                    manual_tracker=manual_tracker,
                    axis=axis,
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
        manual_tracker: bool = False,
        axis: str = "",
    ) -> float | None:
        dead_zone = float(self.follow_cfg.get(dead_key, 0.02))
        resume_zone = float(self.follow_cfg.get(resume_key, dead_zone))
        gain = float(self.follow_cfg.get(gain_key, self.follow_cfg.get(gain_alias, 1.0)))
        min_step = float(self.follow_cfg.get(min_key, 0.0))
        min_zone = float(self.follow_cfg.get(min_zone_key, 1.0))
        max_step = float(self.follow_cfg.get(max_key, 1.0))
        gain *= self._speed_step_scale
        if manual_tracker:
            profile = self._manual_tracker_profile()
            dead_zone = float(profile["dead_zone_norm"])
            resume_zone = float(profile["resume_zone_norm"])
            gain *= float(profile["gain_scale"])
            if float(profile["min_step_deg"]) >= 0:
                min_step = float(profile["min_step_deg"])
            if float(profile["min_step_zone_norm"]) >= 0:
                min_zone = float(profile["min_step_zone_norm"])
            if float(profile["max_step_deg"]) > 0:
                max_step = min(max_step, float(profile["max_step_deg"]))
        step, next_active = compute_axis_step(
            norm_value,
            active=bool(self._joint_active.get(joint, False)),
            gain=gain,
            sign=float(self.follow_cfg.get(sign_key, 1.0)),
            dead=dead_zone,
            resume=resume_zone,
            min_step=min_step,
            min_zone=min_zone,
            max_step=max_step,
        )
        self._joint_active[joint] = next_active
        if step is not None and manual_tracker and self._manual_axis_throttled(axis or FOLLOW_JOINT_AXES.get(joint, "")):
            return None
        if step is not None and manual_tracker:
            self._manual_axis_command_at[axis or FOLLOW_JOINT_AXES.get(joint, "")] = time.monotonic()
        return step

    def _reset_joint_activity(self) -> None:
        self._pan_active = False
        self._tilt_active = False
        for joint in self._joint_active:
            self._joint_active[joint] = False
        self._manual_axis_command_at.clear()

    def _manual_tracker_profile(self) -> dict[str, float]:
        raw = self.follow_cfg.get("manual_tracker_profile", {})
        raw_profile = raw if isinstance(raw, dict) else {}

        def read_float(key: str) -> float:
            try:
                return float(raw_profile.get(key, MANUAL_TRACKER_PROFILE[key]))
            except (TypeError, ValueError):
                return float(MANUAL_TRACKER_PROFILE[key])

        return {key: read_float(key) for key in MANUAL_TRACKER_PROFILE}

    def _manual_axis_throttled(self, axis: str) -> bool:
        if not axis:
            return False
        min_interval = max(0.15, float(self.move_duration_sec))
        last_at = float(self._manual_axis_command_at.get(axis, 0.0))
        return last_at > 0 and time.monotonic() - last_at < min_interval

    @staticmethod
    def _calc_speed_step_scale(speed_percent: int | float) -> float:
        try:
            raw = float(speed_percent)
        except (TypeError, ValueError):
            raw = SPEED_BASELINE_PERCENT
        scale = raw / SPEED_BASELINE_PERCENT
        scale = max(MIN_SPEED_STEP_SCALE, min(MAX_SPEED_STEP_SCALE, scale))
        return round(scale, 4)

    @staticmethod
    def _is_manual_tracker(latest: dict[str, Any]) -> bool:
        target = latest.get("target") if isinstance(latest.get("target"), dict) else {}
        return str(latest.get("target_source") or target.get("source") or "").strip().lower() == "manual_tracker"

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
