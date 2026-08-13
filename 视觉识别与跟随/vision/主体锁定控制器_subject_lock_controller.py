"""主体锁定运镜的标定、持久化、回起点与连续播放控制器。"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .路径工具_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import read_smoothed_offset, smoothstep01, unwrap_vision_payload  # noqa: E402
from 通用_io import atomic_write_json, read_json_object  # noqa: E402

from .主体锁定运镜_subject_lock import (
    ShapePreservingHermiteCurve,
    build_playback_plan,
    calibration_positions,
    run_target_plan,
    validate_calibration_samples,
    validate_playback_speed,
)


class FineCenterPlanner:
    def __init__(
        self,
        *,
        initial_j11_deg: float,
        sign: float,
        max_speed_deg_s: float,
        max_accel_deg_s2: float,
        min_j11_deg: float,
        max_j11_deg: float,
        gain_deg_s_per_norm: float = 20.0,
    ):
        self.target = float(initial_j11_deg)
        self.velocity = 0.0
        self.sign = 1.0 if float(sign) >= 0 else -1.0
        self.max_speed = max(0.1, float(max_speed_deg_s))
        self.max_accel = max(0.1, float(max_accel_deg_s2))
        self.minimum = float(min_j11_deg)
        self.maximum = float(max_j11_deg)
        self.gain = max(0.0, float(gain_deg_s_per_norm))

    def step(self, ndx: float, *, dt: float, hold: bool = False) -> dict[str, Any]:
        dt = max(0.0, min(0.1, float(dt)))
        if hold:
            self.velocity = 0.0
            return self._result(False)
        desired = max(-self.max_speed, min(self.max_speed, float(ndx) * self.gain * self.sign))
        change = max(-self.max_accel * dt, min(self.max_accel * dt, desired - self.velocity))
        self.velocity += change
        unclamped = self.target + self.velocity * dt
        self.target = max(self.minimum, min(self.maximum, unclamped))
        at_limit = abs(self.target - unclamped) > 1e-9 or self.target <= self.minimum + 1e-9 or self.target >= self.maximum - 1e-9
        if at_limit and ((self.target <= self.minimum and self.velocity < 0) or (self.target >= self.maximum and self.velocity > 0)):
            self.velocity = 0.0
        return self._result(at_limit)

    def _result(self, at_limit: bool) -> dict[str, Any]:
        return {"target_deg": self.target, "velocity_deg_s": self.velocity, "at_limit": bool(at_limit)}


class SubjectLockController:
    DEFAULTS = {
        "control_update_hz": 40.0,
        "calibration_move_speed_mm_s": 3.0,
        "center_max_speed_deg_s": 5.0,
        "center_max_accel_deg_s2": 15.0,
        "center_gain_deg_s_per_norm": 20.0,
        "tilt_center_max_speed_deg_s": 5.0,
        "tilt_center_max_accel_deg_s2": 15.0,
        "tilt_center_gain_deg_s_per_norm": 20.0,
        "center_error_norm": 0.012,
        "vertical_center_error_norm": 0.015,
        "stable_sec": 1.5,
        "center_timeout_sec": 20.0,
        "vision_stale_timeout_sec": 0.25,
        "vision_loss_abort_sec": 1.0,
        "pan_sign": 1.0,
        "tilt_sign": 1.0,
        "j10_min_mm": -140.0,
        "j10_max_mm": 140.0,
        "j11_min_deg": -360.0,
        "j11_max_deg": 360.0,
        "j13_min_deg": -180.0,
        "j13_max_deg": 180.0,
        "max_j11_speed_deg_s": 12.0,
        "max_j11_accel_deg_s2": 30.0,
        "move_to_start_j10_speed_mm_s": 3.0,
        "move_to_start_j11_speed_deg_s": 5.0,
        "start_tolerance_j10_mm": 0.5,
        "start_tolerance_j11_deg": 0.5,
        "start_vision_error_norm": 0.03,
        "reference_joint_tolerance_deg": 2.0,
    }

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        latest_provider: Callable[[], Mapping[str, Any]],
        state_provider: Callable[[], Mapping[str, float]],
        stream_writer: Callable[[dict[str, float]], Mapping[str, Any]],
        stream_sync: Callable[[], Mapping[str, Any]],
        dry_run: bool,
        config: Mapping[str, Any] | None = None,
        target_validator: Callable[[dict[str, float]], Mapping[str, Any]] | None = None,
    ):
        self.profile_dir = Path(profile_dir).resolve()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.latest_provider = latest_provider
        self.state_provider = state_provider
        self.stream_writer = stream_writer
        self.stream_sync = stream_sync
        self.target_validator = target_validator
        self.dry_run = bool(dry_run)
        self.config = dict(self.DEFAULTS)
        self.config.update(dict(config or {}))
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sync_done = True
        self._vision_key: Any = None
        self._vision_at = 0.0
        self._status = self._idle_status()

    def _idle_status(self) -> dict[str, Any]:
        return {
            "running": False,
            "phase": "idle",
            "message": "主体锁定运镜空闲。",
            "dry_run": self.dry_run,
            "profile_id": "",
            "profile_name": "",
            "progress": 0.0,
            "calibration_point_index": 0,
            "calibration_point_count": 0,
            "horizontal_error_norm": None,
            "vertical_error_norm": None,
            "latest_vision_age_ms": None,
            "hold_reason": "",
            "targets_deg": {},
            "actual_update_hz": 0.0,
            "p95_interval_ms": 0.0,
            "max_interval_ms": 0.0,
            "skipped_tick_count": 0,
            "write_count": 0,
            "validation": None,
            "last_error": "",
            "at_start": False,
        }

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._status)
            result["thread_alive"] = bool(self._thread and self._thread.is_alive())
            return result

    def start_calibration(self, name: str, start_mm: float, end_mm: float, speed_mm_s: float) -> dict[str, Any]:
        self._check_idle()
        start = float(start_mm)
        end = float(end_mm)
        self._check_rail_range(start, end)
        if abs(end - start) < 0.05:
            raise ValueError("J10 标定行程至少需要 0.05 mm。")
        profile_id = _profile_id(name)
        with self._lock:
            self._stop_event = threading.Event()
            self._sync_done = False
            self._vision_key = None
            self._vision_at = 0.0
            self._status = self._idle_status()
            self._status.update(
                running=True,
                phase="starting",
                message="主体锁定标定正在启动。",
                profile_id=profile_id,
                profile_name=str(name).strip() or "主体锁定轨迹",
                calibration_point_count=11,
            )
            self._thread = threading.Thread(
                target=self._calibration_worker,
                args=(profile_id, self._status["profile_name"], start, end, abs(float(speed_mm_s))),
                name=f"subject-lock-calibration-{profile_id}",
                daemon=True,
            )
            self._thread.start()
        return self.get_status()

    def stop(self, reason: str = "manual_stop", join_timeout: float = 1.2) -> dict[str, Any]:
        self.request_stop(reason)
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=join_timeout)
        return self.get_status()

    def request_stop(self, reason: str = "manual_stop") -> None:
        self._stop_event.set()
        with self._lock:
            if self._status.get("running"):
                self._status.update(hold_reason=str(reason), message="主体锁定运镜正在停止。")

    def list_profiles(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.profile_dir.glob("subject_lock_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                profile = read_json_object(path)
            except Exception:
                continue
            items.append(self._profile_summary(profile, path))
        return items

    def load_profile(self, profile_id: str) -> dict[str, Any]:
        path = self._profile_path(profile_id)
        if not path.exists():
            raise FileNotFoundError(f"未找到主体锁定轨迹：{profile_id}")
        profile = read_json_object(path)
        if profile.get("schema") != "subject_lock_v1":
            raise ValueError("主体锁定轨迹格式不受支持。")
        profile["path"] = str(path)
        return profile

    def delete_profile(self, profile_id: str) -> dict[str, Any]:
        self._check_idle()
        path = self._profile_path(profile_id)
        if not path.exists():
            raise FileNotFoundError(f"未找到主体锁定轨迹：{profile_id}")
        path.unlink()
        return {"profile_id": profile_id, "message": "主体锁定轨迹已删除。"}

    def validate_profile(self, profile_id: str, speed_mm_s: float) -> dict[str, Any]:
        self._check_idle()
        profile = self.load_profile(profile_id)
        curve = ShapePreservingHermiteCurve.from_dict(profile["curve"])
        tilt_curve = self._tilt_curve(profile)
        validation = validate_playback_speed(
            curve,
            start_mm=float(profile["rail"]["start_mm"]),
            end_mm=float(profile["rail"]["end_mm"]),
            speed_mm_s=float(speed_mm_s),
            max_j11_speed_deg_s=float(self.config["max_j11_speed_deg_s"]),
            max_j11_accel_deg_s2=float(self.config["max_j11_accel_deg_s2"]),
            update_hz=float(self.config["control_update_hz"]),
            j10_limits=(float(self.config["j10_min_mm"]), float(self.config["j10_max_mm"])),
            j11_limits=(float(self.config["j11_min_deg"]), float(self.config["j11_max_deg"])),
        )
        validation = self._apply_target_validation(
            validation,
            curve,
            float(profile["rail"]["start_mm"]),
            float(profile["rail"]["end_mm"]),
            float(speed_mm_s),
            tilt_curve=tilt_curve,
        )
        profile["rail"]["requested_speed_mm_s"] = abs(float(speed_mm_s))
        profile["validation"] = validation
        profile["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(self._profile_path(profile_id), profile)
        with self._lock:
            self._status.update(profile_id=profile_id, profile_name=profile.get("name", ""), validation=validation, phase="ready" if validation["valid"] else "needs_speed", message=validation["message"])
        return profile

    def move_to_start(self, profile_id: str) -> dict[str, Any]:
        profile = self._validated_profile(profile_id)
        self._check_reference_pose(profile, self.state_provider())
        return self._start_operation("moving_to_start", profile, self._move_to_start_worker)

    def play(self, profile_id: str) -> dict[str, Any]:
        profile = self._validated_profile(profile_id)
        state = {str(key): float(value) for key, value in self.state_provider().items()}
        self._check_reference_pose(profile, state)
        start_j10 = float(profile["rail"]["start_mm"])
        start_j11 = float(ShapePreservingHermiteCurve.from_dict(profile["curve"]).evaluate(start_j10))
        tilt_curve = self._tilt_curve(profile)
        start_j13 = float(tilt_curve.evaluate(start_j10)) if tilt_curve is not None else float(state.get("j13", 0.0))
        if (
            abs(float(state.get("j10", 0.0)) - start_j10) > float(self.config["start_tolerance_j10_mm"])
            or abs(float(state.get("j11", 0.0)) - start_j11) > float(self.config["start_tolerance_j11_deg"])
            or (tilt_curve is not None and abs(float(state.get("j13", 0.0)) - start_j13) > float(self.config["start_tolerance_j11_deg"]))
        ):
            raise ValueError("机械臂尚未位于轨迹起点，请先执行“回到起点”。")
        self._assert_plan_targets(profile)
        return self._start_operation("playing", profile, self._play_worker)

    def _start_operation(self, phase: str, profile: dict[str, Any], worker: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        self._check_idle()
        with self._lock:
            self._stop_event = threading.Event()
            self._sync_done = False
            self._status = self._idle_status()
            self._status.update(running=True, phase=phase, profile_id=profile["profile_id"], profile_name=profile.get("name", ""), validation=profile.get("validation"), message="主体锁定运镜已启动。")
            self._thread = threading.Thread(target=worker, args=(profile,), name=f"subject-lock-{phase}", daemon=True)
            self._thread.start()
        return self.get_status()

    def _calibration_worker(self, profile_id: str, name: str, start: float, end: float, requested_speed: float) -> None:
        samples: list[dict[str, float]] = []
        reference_state: dict[str, float] = {}
        camera: dict[str, Any] = {}
        try:
            current = {str(key): float(value) for key, value in self.state_provider().items()}
            reference_state = dict(current)
            positions = calibration_positions(start, end)
            self._set_status(phase="centering", message="正在居中主体，然后开始标定。")
            centered, latest = self._center_at_point(current)
            if not centered:
                raise RuntimeError("自动标定开始前无法将主体稳定居中。")
            camera = dict(latest.get("camera", {})) if isinstance(latest.get("camera"), Mapping) else camera
            measured = {str(key): float(value) for key, value in self.state_provider().items()}
            current.update({
                "j10": float(measured.get("j10", current.get("j10", 0.0))),
                "j11": float(measured.get("j11", current.get("j11", 0.0))),
                "j13": float(measured.get("j13", current.get("j13", 0.0))),
            })
            for index, position in enumerate(positions):
                if self._stop_event.is_set():
                    break
                self._set_status(phase="moving_to_point", calibration_point_index=index + 1, progress=index / len(positions), message=f"正在前往标定点 {index + 1}/{len(positions)}。")
                move_speed = min(3.0, float(self.config["calibration_move_speed_mm_s"]))
                plan = _build_move_plan(
                    {"j10": float(current.get("j10", position)), "j11": float(current.get("j11", 0.0))},
                    {"j10": position, "j11": float(current.get("j11", 0.0))},
                    j10_speed=move_speed,
                    j11_speed=float(self.config["center_max_speed_deg_s"]),
                    update_hz=float(self.config["control_update_hz"]),
                )
                self._run_plan(
                    plan,
                    require_vision=True,
                    center_planners=self._center_planners(current),
                )
                current["j10"] = position
                streamed = self._status.get("targets_deg", {})
                if isinstance(streamed, Mapping) and "j11" in streamed:
                    current["j11"] = float(streamed["j11"])
                if isinstance(streamed, Mapping) and "j13" in streamed:
                    current["j13"] = float(streamed["j13"])
                centered, latest = self._center_at_point(current)
                camera = dict(latest.get("camera", {})) if isinstance(latest.get("camera"), Mapping) else camera
                if not centered:
                    raise RuntimeError("主体在标定点无法稳定居中。")
                measured = {str(key): float(value) for key, value in self.state_provider().items()}
                current.update({
                    "j10": float(measured.get("j10", current["j10"])),
                    "j11": float(measured.get("j11", current["j11"])),
                    "j13": float(measured.get("j13", current.get("j13", 0.0))),
                })
                samples.append({
                    "index": index,
                    "j10_mm": current["j10"],
                    "j11_deg": current["j11"],
                    "j13_deg": current["j13"],
                    "horizontal_error_norm": float(self._status.get("horizontal_error_norm") or 0.0),
                    "vertical_error_norm": float(self._status.get("vertical_error_norm") or 0.0),
                })
            if self._stop_event.is_set():
                self._set_status(running=False, phase="stopped", message="主体锁定标定已停止。")
                return
            samples = validate_calibration_samples(samples)
            curve = ShapePreservingHermiteCurve.from_points(samples)
            tilt_curve = ShapePreservingHermiteCurve.from_points(samples, "j13_deg")
            validation = validate_playback_speed(
                curve,
                start_mm=start,
                end_mm=end,
                speed_mm_s=requested_speed,
                max_j11_speed_deg_s=float(self.config["max_j11_speed_deg_s"]),
                max_j11_accel_deg_s2=float(self.config["max_j11_accel_deg_s2"]),
                update_hz=float(self.config["control_update_hz"]),
                j10_limits=(float(self.config["j10_min_mm"]), float(self.config["j10_max_mm"])),
                j11_limits=(float(self.config["j11_min_deg"]), float(self.config["j11_max_deg"])),
            )
            validation = self._apply_target_validation(validation, curve, start, end, requested_speed, tilt_curve=tilt_curve)
            profile = {
                "schema": "subject_lock_v1",
                "profile_id": profile_id,
                "name": name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "direction": "start_to_end",
                "rail": {"joint": "j10", "start_mm": start, "end_mm": end, "requested_speed_mm_s": requested_speed},
                "controlled_joints": ["j10", "j11", "j13"],
                "calibration_points": samples,
                "curve": curve.to_dict(),
                "tilt_curve": tilt_curve.to_dict(),
                "reference": {"joints_deg": reference_state, "camera": camera},
                "validation": validation,
            }
            atomic_write_json(self._profile_path(profile_id), profile)
            self._set_status(
                running=False,
                phase="ready" if validation["valid"] else "needs_speed",
                progress=1.0,
                calibration_point_count=len(samples),
                validation=validation,
                message=validation["message"],
            )
        except Exception as exc:
            self._set_status(running=False, phase="error", last_error=str(exc), message=f"主体锁定标定失败：{exc}")
        finally:
            self._sync_once()

    def _center_planners(self, current: Mapping[str, float]) -> dict[str, FineCenterPlanner]:
        return {
            "j11": FineCenterPlanner(
                initial_j11_deg=float(current.get("j11", 0.0)),
                sign=float(self.config["pan_sign"]),
                max_speed_deg_s=float(self.config["center_max_speed_deg_s"]),
                max_accel_deg_s2=float(self.config["center_max_accel_deg_s2"]),
                min_j11_deg=float(self.config["j11_min_deg"]),
                max_j11_deg=float(self.config["j11_max_deg"]),
                gain_deg_s_per_norm=float(self.config["center_gain_deg_s_per_norm"]),
            ),
            "j13": FineCenterPlanner(
                initial_j11_deg=float(current.get("j13", 0.0)),
                sign=float(self.config["tilt_sign"]),
                max_speed_deg_s=float(self.config["tilt_center_max_speed_deg_s"]),
                max_accel_deg_s2=float(self.config["tilt_center_max_accel_deg_s2"]),
                min_j11_deg=float(self.config["j13_min_deg"]),
                max_j11_deg=float(self.config["j13_max_deg"]),
                gain_deg_s_per_norm=float(self.config["tilt_center_gain_deg_s_per_norm"]),
            ),
        }

    def _center_at_point(self, current: dict[str, float]) -> tuple[bool, dict[str, Any]]:
        planners = self._center_planners(current)
        period = 1.0 / float(self.config["control_update_hz"])
        started = time.monotonic()
        deadline = started
        stable_since: float | None = None
        missing_since: float | None = None
        latest_at = 0.0
        latest_key: Any = None
        latest: dict[str, Any] = {}
        self._set_status(phase="centering", message="正在精细居中主体。")
        while not self._stop_event.is_set():
            if self._stop_event.wait(max(0.0, deadline - time.monotonic())):
                break
            now = time.monotonic()
            deadline = max(deadline + period, now)
            raw = unwrap_vision_payload(dict(self.latest_provider()))
            key = raw.get("frame_id", raw.get("timestamp"))
            if key is None or key != latest_key:
                latest_at = now
                latest_key = key
                latest = raw
            age = now - latest_at if latest_at else float("inf")
            offset = read_smoothed_offset(latest) if latest else None
            has_target = bool(latest.get("has_target", latest.get("detected", False)))
            stale = age > float(self.config["vision_stale_timeout_sec"])
            if stale or not has_target or offset is None:
                missing_since = missing_since or now
                for planner in planners.values():
                    planner.step(0.0, dt=period, hold=True)
                reason = "vision_stale" if stale else "target_lost"
                self._set_status(hold_reason=reason, latest_vision_age_ms=None if not latest_at else round(age * 1000.0, 3), message="视觉不可用，标定保持。")
                if now - missing_since >= float(self.config["vision_loss_abort_sec"]):
                    raise RuntimeError("视觉目标持续丢失或数据过期。")
                continue
            missing_since = None
            ndx = float(offset[0])
            ndy = float(offset[1])
            self._set_status(horizontal_error_norm=ndx, vertical_error_norm=ndy, latest_vision_age_ms=round(age * 1000.0, 3), hold_reason="")
            centered_x = abs(ndx) <= float(self.config["center_error_norm"])
            centered_y = abs(ndy) <= float(self.config["vertical_center_error_norm"])
            if centered_x and centered_y:
                for planner in planners.values():
                    planner.step(0.0, dt=period, hold=True)
                stable_since = stable_since or now
                if now - stable_since >= float(self.config["stable_sec"]):
                    current["j11"] = planners["j11"].target
                    current["j13"] = planners["j13"].target
                    return True, latest
            else:
                stable_since = None
                pan = planners["j11"].step(ndx, dt=period, hold=centered_x)
                tilt = planners["j13"].step(ndy, dt=period, hold=centered_y)
                if pan["at_limit"] or tilt["at_limit"]:
                    joint = "J11" if pan["at_limit"] else "J13"
                    raise RuntimeError(f"{joint} 已到限位但主体仍未居中。")
                response = self.stream_writer({
                    "j10": float(current["j10"]),
                    "j11": float(pan["target_deg"]),
                    "j13": float(tilt["target_deg"]),
                })
                if not bool(response.get("ok", False)):
                    raise RuntimeError(str(response.get("message") or "精细居中写入失败。"))
                current["j11"] = float(pan["target_deg"])
                current["j13"] = float(tilt["target_deg"])
                self._set_status(targets_deg={"j10": current["j10"], "j11": current["j11"], "j13": current["j13"]})
            if now - started >= float(self.config["center_timeout_sec"]):
                raise RuntimeError("单个标定点居中超时。")
        return False, latest

    def _move_to_start_worker(self, profile: dict[str, Any]) -> None:
        try:
            current = {str(key): float(value) for key, value in self.state_provider().items()}
            curve = ShapePreservingHermiteCurve.from_dict(profile["curve"])
            tilt_curve = self._tilt_curve(profile)
            start = float(profile["rail"]["start_mm"])
            target = {"j10": start, "j11": curve.evaluate(start)}
            if tilt_curve is not None:
                target["j13"] = tilt_curve.evaluate(start)
            plan = _build_move_plan(
                {joint: current.get(joint, 0.0) for joint in target},
                target,
                j10_speed=float(self.config["move_to_start_j10_speed_mm_s"]),
                j11_speed=float(self.config["move_to_start_j11_speed_deg_s"]),
                update_hz=float(self.config["control_update_hz"]),
            )
            self._run_plan(plan, require_vision=True)
            if self._stop_event.is_set():
                self._set_status(running=False, phase="stopped", message="回到起点已停止。")
                return
            latest = unwrap_vision_payload(dict(self.latest_provider()))
            offset = read_smoothed_offset(latest)
            if (
                not latest.get("has_target", latest.get("detected", False))
                or offset is None
                or abs(float(offset[0])) > float(self.config["start_vision_error_norm"])
                or abs(float(offset[1])) > float(self.config["start_vision_error_norm"])
            ):
                raise RuntimeError("已到轨迹起点，但主体未处于中心，请重新标定或调整主体。")
            self._set_status(
                running=False,
                phase="at_start",
                at_start=True,
                progress=1.0,
                horizontal_error_norm=float(offset[0]),
                vertical_error_norm=float(offset[1]),
                message="已到轨迹起点，可以正式播放。",
            )
        except Exception as exc:
            self._set_status(running=False, phase="error", last_error=str(exc), message=f"回到起点失败：{exc}")
        finally:
            self._sync_once()

    def _play_worker(self, profile: dict[str, Any]) -> None:
        try:
            curve = ShapePreservingHermiteCurve.from_dict(profile["curve"])
            plan = self._build_profile_plan(profile, curve)
            stats = self._run_plan(plan)
            if self._stop_event.is_set():
                self._set_status(running=False, phase="stopped", message="主体锁定播放已停止。", **stats)
            else:
                self._set_status(running=False, phase="finished", progress=1.0, message="主体锁定运镜播放完成。", **stats)
        except Exception as exc:
            self._set_status(running=False, phase="error", last_error=str(exc), message=f"主体锁定播放失败：{exc}")
        finally:
            self._sync_once()

    def _run_plan(
        self,
        plan: list[Mapping[str, Any]],
        *,
        require_vision: bool = False,
        center_planner: FineCenterPlanner | None = None,
        center_planners: Mapping[str, FineCenterPlanner] | None = None,
    ) -> dict[str, Any]:
        total = max(1, len(plan))
        writes_before = int(self._status.get("write_count", 0))

        def writer(targets: dict[str, float]) -> Mapping[str, Any]:
            if self._stop_event.is_set():
                return {"ok": False, "message": "主体锁定会话已停止。"}
            pause_sec = self._wait_for_fresh_target() if require_vision else 0.0
            targets = dict(targets)
            active_planners = dict(center_planners or ({"j11": center_planner} if center_planner is not None else {}))
            if active_planners:
                latest = unwrap_vision_payload(dict(self.latest_provider()))
                offset = read_smoothed_offset(latest)
                if offset is None or not latest.get("has_target", latest.get("detected", False)):
                    raise RuntimeError("导轨移动期间视觉目标丢失。")
                ndx = float(offset[0])
                ndy = float(offset[1])
                for joint, planner in active_planners.items():
                    error = ndx if joint == "j11" else ndy
                    centered_frame = planner.step(error, dt=1.0 / float(self.config["control_update_hz"]))
                    if centered_frame["at_limit"]:
                        raise RuntimeError(f"{joint.upper()} 已到限位但主体仍未居中。")
                    targets[joint] = float(centered_frame["target_deg"])
                self._set_status(horizontal_error_norm=ndx, vertical_error_norm=ndy)
            response = self.stream_writer(targets)
            if bool(response.get("ok", False)):
                current_write = int(self._status.get("write_count", 0)) + 1
                self._set_status(targets_deg=dict(targets), write_count=current_write, progress=min(0.999, current_write / max(total, current_write)))
            result = dict(response)
            result["pause_sec"] = pause_sec
            return result

        stats = run_target_plan(plan, stop_event=self._stop_event, write_target=writer)
        stats["write_count"] = writes_before + int(stats.get("write_count", 0))
        self._set_status(**stats)
        return stats

    def _wait_for_fresh_target(self) -> float:
        started = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            latest = unwrap_vision_payload(dict(self.latest_provider()))
            key = latest.get("frame_id", latest.get("timestamp"))
            if key is None or key != self._vision_key:
                self._vision_key = key
                self._vision_at = now
            age = now - self._vision_at if self._vision_at else float("inf")
            offset = read_smoothed_offset(latest)
            has_target = bool(latest.get("has_target", latest.get("detected", False)))
            stale = age > float(self.config["vision_stale_timeout_sec"])
            if has_target and offset is not None and not stale:
                self._set_status(
                    hold_reason="",
                    latest_vision_age_ms=round(age * 1000.0, 3),
                    horizontal_error_norm=float(offset[0]),
                    vertical_error_norm=float(offset[1]),
                )
                return now - started
            reason = "vision_stale" if stale else "target_lost"
            self._set_status(hold_reason=reason, latest_vision_age_ms=None if not self._vision_at else round(age * 1000.0, 3), message="视觉不可用，运动保持。")
            if now - started >= float(self.config["vision_loss_abort_sec"]):
                raise RuntimeError("视觉目标持续丢失或数据过期。")
            self._stop_event.wait(0.01)
        raise RuntimeError("主体锁定会话已停止。")

    def _sync_once(self) -> None:
        with self._lock:
            if self._sync_done:
                return
            self._sync_done = True
        try:
            self.stream_sync()
        except Exception as exc:
            self._set_status(last_error=str(exc))

    def _validated_profile(self, profile_id: str) -> dict[str, Any]:
        self._check_idle()
        profile = self.load_profile(profile_id)
        validation = profile.get("validation") if isinstance(profile.get("validation"), Mapping) else {}
        if not bool(validation.get("valid", False)):
            raise ValueError("轨迹尚未通过速度与安全检查。")
        return profile

    def _apply_target_validation(
        self,
        validation: dict[str, Any],
        curve: ShapePreservingHermiteCurve,
        start_mm: float,
        end_mm: float,
        speed_mm_s: float,
        *,
        tilt_curve: ShapePreservingHermiteCurve | None = None,
    ) -> dict[str, Any]:
        result = dict(validation)
        if not result.get("valid") or self.target_validator is None:
            result["raw_checked"] = self.target_validator is not None
            return result
        plan = build_playback_plan(
            curve,
            start_mm=start_mm,
            end_mm=end_mm,
            speed_mm_s=speed_mm_s,
            update_hz=float(self.config["control_update_hz"]),
        )
        if tilt_curve is not None:
            for frame in plan:
                frame["targets_deg"]["j13"] = tilt_curve.evaluate(float(frame["targets_deg"]["j10"]))
        for frame in plan:
            response = self.target_validator(dict(frame["targets_deg"]))
            if not bool(response.get("ok", False)):
                result.update(
                    valid=False,
                    raw_checked=True,
                    safe_max_speed_mm_s=0.0,
                    message=str(response.get("message") or response.get("error") or "轨迹 raw 安全检查未通过。"),
                )
                return result
        result["raw_checked"] = True
        return result

    def _assert_plan_targets(self, profile: Mapping[str, Any]) -> None:
        if self.target_validator is None:
            return
        curve = ShapePreservingHermiteCurve.from_dict(profile["curve"])
        tilt_curve = self._tilt_curve(profile)
        validation = self._apply_target_validation(
            {"valid": True},
            curve,
            float(profile["rail"]["start_mm"]),
            float(profile["rail"]["end_mm"]),
            float(profile["rail"]["requested_speed_mm_s"]),
            tilt_curve=tilt_curve,
        )
        if not validation.get("valid"):
            raise ValueError(f"轨迹安全检查失败：{validation.get('message', '未知错误')}")

    def _check_reference_pose(self, profile: Mapping[str, Any], state: Mapping[str, Any]) -> None:
        reference = profile.get("reference", {}) if isinstance(profile.get("reference"), Mapping) else {}
        joints = reference.get("joints_deg", {}) if isinstance(reference.get("joints_deg"), Mapping) else {}
        tolerance = float(self.config["reference_joint_tolerance_deg"])
        mismatched = [
            joint
            for joint in ("j12", "j14", "j15")
            if joint in joints and abs(float(state.get(joint, 0.0)) - float(joints[joint])) > tolerance
        ]
        if mismatched:
            raise ValueError(f"机械臂参考姿态已变化（{', '.join(mismatched)}），请重新标定主体锁定轨迹。")

    @staticmethod
    def _tilt_curve(profile: Mapping[str, Any]) -> ShapePreservingHermiteCurve | None:
        payload = profile.get("tilt_curve")
        return ShapePreservingHermiteCurve.from_dict(payload) if isinstance(payload, Mapping) else None

    def _build_profile_plan(
        self,
        profile: Mapping[str, Any],
        curve: ShapePreservingHermiteCurve | None = None,
    ) -> list[dict[str, Any]]:
        pan_curve = curve or ShapePreservingHermiteCurve.from_dict(profile["curve"])
        plan = build_playback_plan(
            pan_curve,
            start_mm=float(profile["rail"]["start_mm"]),
            end_mm=float(profile["rail"]["end_mm"]),
            speed_mm_s=float(profile["rail"]["requested_speed_mm_s"]),
            update_hz=float(self.config["control_update_hz"]),
        )
        tilt_curve = self._tilt_curve(profile)
        if tilt_curve is not None:
            for frame in plan:
                frame["targets_deg"]["j13"] = round(tilt_curve.evaluate(float(frame["targets_deg"]["j10"])), 6)
        return plan

    def _check_idle(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("主体锁定运镜正在运行，请先停止。")

    def _check_rail_range(self, start: float, end: float) -> None:
        minimum = float(self.config["j10_min_mm"])
        maximum = float(self.config["j10_max_mm"])
        if not minimum <= start <= maximum or not minimum <= end <= maximum:
            raise ValueError(f"J10 起终点必须位于 {minimum:g} 到 {maximum:g} mm。")

    def _profile_path(self, profile_id: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", str(profile_id)).strip("_")
        if not safe or safe != str(profile_id):
            raise ValueError("主体锁定轨迹 ID 无效。")
        return self.profile_dir / f"subject_lock_{safe}.json"

    @staticmethod
    def _profile_summary(profile: Mapping[str, Any], path: Path) -> dict[str, Any]:
        return {
            "schema": profile.get("schema"),
            "profile_id": profile.get("profile_id"),
            "name": profile.get("name"),
            "created_at": profile.get("created_at"),
            "rail": profile.get("rail", {}),
            "validation": profile.get("validation"),
            "calibration_point_count": len(profile.get("calibration_points", [])) if isinstance(profile.get("calibration_points"), list) else 0,
            "path": str(path),
        }

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)


def _profile_id(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", str(name).strip()).strip("_") or "subject"
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return f"{base}_{stamp}"


def _build_move_plan(
    current: Mapping[str, float],
    target: Mapping[str, float],
    *,
    j10_speed: float,
    j11_speed: float,
    update_hz: float,
) -> list[dict[str, Any]]:
    j10_delta = abs(float(target["j10"]) - float(current["j10"]))
    j11_delta = abs(float(target["j11"]) - float(current["j11"]))
    j13_delta = abs(float(target.get("j13", 0.0)) - float(current.get("j13", target.get("j13", 0.0))))
    duration = max(
        0.05,
        j10_delta / max(0.05, float(j10_speed)),
        j11_delta / max(0.1, float(j11_speed)),
        j13_delta / max(0.1, float(j11_speed)),
    )
    steps = max(2, int(round(duration * max(2.0, float(update_hz)))) + 1)
    interval = duration / (steps - 1)
    plan: list[dict[str, Any]] = []
    for index in range(steps):
        progress = smoothstep01(index / (steps - 1))
        targets = {
            joint: float(current[joint]) + (float(target[joint]) - float(current[joint])) * progress
            for joint in target
        }
        plan.append({"index": index, "time_sec": index * interval, "targets_deg": targets})
    return plan
