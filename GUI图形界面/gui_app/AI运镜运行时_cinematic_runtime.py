"""AI 运镜试拍运行时。

这个模块只保存试拍/回放状态与计划生成逻辑，不创建 Qt 控件。
视觉跟随页面负责画面与实时跟随，AI 运镜页面负责参数输入。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from 控制桥接_common import FOLLOW_JOINT_AXES, RailSweepPlanner, clamp_symmetric, eased_end_progress, normalize_joint_targets, read_smoothed_offset, smoothstep01
from 通用_io import atomic_write_json, latest_matching_file, read_json_object, timestamped_json_path


class CinematicRehearsalRuntime:
    """Manage AI 运镜 trial capture and sampling playback without GUI widgets."""

    def __init__(self, project_root: str | Path, config_provider: Callable[[], Mapping[str, Any]]):
        self.project_root = Path(project_root).resolve()
        self.vision_root = self.project_root / "视觉识别与跟随"
        self.record_dir = self.vision_root / "runtime" / "cinematic_records"
        self._config_provider = config_provider
        self.settings = self._default_settings()
        self.rail_planner = RailSweepPlanner(self.rail_settings(), virtual_pos_mm=0.0, running=False, phase="idle")
        self.mode = "follow"
        self.rehearsal_record: dict[str, Any] | None = None
        self.loaded_record_path: Path | None = None
        self.rehearsal_samples: list[dict[str, Any]] = []
        self.sparse_playback_plan: list[dict[str, Any]] = []
        self.playback_plan: list[dict[str, Any]] = []
        self.playback_index = 0
        self.last_sample_at = 0.0
        self._reset_rehearsal_data(clear_loaded_path=False)

    @property
    def rail_running(self) -> bool:
        return bool(self.rail_planner.running)

    @property
    def rail_phase(self) -> str:
        return str(self.rail_planner.phase)

    @property
    def rail_virtual_pos_mm(self) -> float:
        return float(self.rail_planner.virtual_pos_mm)

    def _default_settings(self) -> dict[str, Any]:
        follow = self._follow_cfg()
        rail = follow.get("rail_cinematic", {}) if isinstance(follow.get("rail_cinematic"), dict) else {}
        two_step = follow.get("two_step_cinematic", {}) if isinstance(follow.get("two_step_cinematic"), dict) else {}
        fallback_speed = float(rail.get("step_mm", 1.0)) / max(0.02, float(rail.get("interval_sec", 0.2)))
        return {
            "rail": {
                "enabled": bool(rail.get("enabled", False)),
                "joint": str(rail.get("joint", "j10")),
                "start_mm": float(rail.get("start_mm", -140.0)),
                "end_mm": float(rail.get("end_mm", 140.0)),
                "speed_mm_s": float(rail.get("speed_mm_s", fallback_speed)),
            },
            "two_step": {
                "sample_interval_sec": float(two_step.get("sample_interval_sec", 0.12)),
                "playback_smooth": float(two_step.get("playback_smooth", 0.55)),
                "playback_speed_scale": float(two_step.get("playback_speed_scale", 1.0)),
                "max_compensation_deg": float(two_step.get("max_compensation_deg", 4.0)),
                "offset_stop_norm": float(two_step.get("offset_stop_norm", 0.65)),
                "playback_hz": float(two_step.get("playback_hz", 20.0)),
                "ease_sec": float(two_step.get("ease_sec", 0.8)),
                "min_rail_step_mm": float(two_step.get("min_rail_step_mm", 0.25)),
            },
        }

    def apply_settings(self, settings: Mapping[str, Any]) -> None:
        rail = settings.get("rail", {}) if isinstance(settings.get("rail"), Mapping) else {}
        two_step = settings.get("two_step", {}) if isinstance(settings.get("two_step"), Mapping) else {}
        for key in ("enabled", "start_mm", "end_mm", "speed_mm_s"):
            if key in rail:
                self.settings["rail"][key] = bool(rail[key]) if key == "enabled" else float(rail[key])
        self.rail_planner.configure(self.rail_settings())
        for key in ("sample_interval_sec", "playback_smooth", "playback_speed_scale", "max_compensation_deg", "offset_stop_norm", "playback_hz", "ease_sec", "min_rail_step_mm"):
            if key in two_step:
                self.settings["two_step"][key] = float(two_step[key])

    def start_follow(self, live_rail_mm: float) -> None:
        self.mode = "follow"
        self.rail_planner.reset(live_rail_mm, running=False, phase="idle")

    def stop(self) -> None:
        self.mode = "follow"
        self.rail_planner.stop("idle")

    def start_rehearsal(self, live_rail_mm: float) -> None:
        self.mode = "rehearsal"
        self.rehearsal_record = None
        self._reset_rehearsal_data(clear_loaded_path=False)
        self._reset_rail_state(live_rail_mm, force_enabled=True)

    def start_playback(self, context: Mapping[str, Any]) -> tuple[bool, str]:
        if self.rehearsal_record is None:
            ok, message = self.load_latest_record()
            if not ok:
                return False, message
        if self.rehearsal_record is None:
            return False, "没有可回放的试拍记录"
        self.playback_plan = self.build_playback_plan(self.rehearsal_record, context)
        if not self.playback_plan:
            return False, "试拍记录采样不足，无法生成回放轨迹"
        self.mode = "playback"
        self.playback_index = 0
        return True, f"0/{len(self.playback_plan)}"

    def clear_record(self) -> tuple[bool, str]:
        self.rehearsal_record = None
        self._reset_rehearsal_data(clear_loaded_path=True)
        return True, "AI 运镜试拍记录已清除"

    def save_record(self) -> tuple[bool, str]:
        if self.rehearsal_record is None:
            return False, "没有可保存的试拍记录"
        path = self._save_record(self.rehearsal_record)
        self.loaded_record_path = path
        return True, str(path.name)

    def load_latest_record(self) -> tuple[bool, str]:
        try:
            latest_path = latest_matching_file(self.record_dir, "cinematic_rehearsal_*.json")
            if latest_path is None:
                return False, "没有找到试拍记录"
            self.rehearsal_record = read_json_object(latest_path)
            self.loaded_record_path = latest_path
            count = len(self.rehearsal_record.get("samples", [])) if self.rehearsal_record else 0
            return True, f"{count} 点 {latest_path.name}"
        except Exception as exc:
            return False, f"加载记录失败：{exc}"

    def mark_rail_error(self, message: str) -> None:
        self.rail_planner.mark_error(message)

    def build_rail_commands(self, *, timer_interval_ms: int, latest_robot_state: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self.mode != "rehearsal" or not self.rail_planner.running:
            return []
        return self.rail_planner.command(default_dt_sec=float(timer_interval_ms) / 1000.0)

    def record_sample(self, result: Mapping[str, Any], latest_robot_state: Mapping[str, Any]) -> tuple[bool, str]:
        now = time.monotonic()
        two_step = self.two_step_settings()
        if self.last_sample_at > 0 and now - self.last_sample_at < float(two_step["sample_interval_sec"]):
            return False, ""
        if not result.get("has_target", result.get("detected", False)):
            return False, ""
        offset = read_smoothed_offset(result)
        if offset is None:
            return False, ""
        ndx, ndy = offset
        message = ""
        if max(abs(ndx), abs(ndy)) > float(two_step["offset_stop_norm"]):
            message = f"偏移过大 {ndx:+.3f},{ndy:+.3f}；试拍继续记录，请降低导轨速度或增益"
        target = result.get("target") if isinstance(result.get("target"), Mapping) else {}
        joints = latest_robot_state.get("joints_deg", {}) if isinstance(latest_robot_state.get("joints_deg"), Mapping) else {}
        self.rehearsal_samples.append(
            {
                "timestamp": time.time(),
                "j10_mm": self.rail_current_mm(latest_robot_state),
                "ndx": ndx,
                "ndy": ndy,
                "bbox": result.get("bbox") or target.get("bbox"),
                "joints_deg": normalize_joint_targets(joints),
            }
        )
        self.last_sample_at = now
        return True, message

    def finalize_rehearsal_record(self, context: Mapping[str, Any]) -> tuple[bool, str, Path | None]:
        if not self.rehearsal_samples:
            self.mode = "follow"
            return False, "试拍没有采到有效目标", None
        rail = self.rail_settings()
        two_step = self.two_step_settings()
        selected = sorted(str(joint) for joint in context.get("selected_joints", []) if str(joint) in FOLLOW_JOINT_AXES)
        record = {
            "mode": "rehearsal",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rail": {
                "start_mm": float(rail["start_mm"]),
                "end_mm": float(rail["end_mm"]),
                "speed_mm_s": float(rail["speed_mm_s"]),
                "sample_interval_sec": float(two_step["sample_interval_sec"]),
            },
            "follow_joints": selected,
            "parameters": {
                "playback_smooth": float(two_step["playback_smooth"]),
                "playback_speed": float(two_step["playback_speed_scale"]),
                "max_comp_deg": float(two_step["max_compensation_deg"]),
                "offset_stop_norm": float(two_step["offset_stop_norm"]),
                "playback_hz": float(two_step["playback_hz"]),
                "ease_sec": float(two_step["ease_sec"]),
                "min_rail_step_mm": float(two_step["min_rail_step_mm"]),
            },
            "samples": list(self.rehearsal_samples),
            "playback_plan": [],
            "dense_playback_plan": [],
        }
        sparse = self._build_sparse_playback_plan(record, context)
        record["playback_plan"] = sparse
        record["dense_playback_plan"] = self._build_dense_playback_plan(sparse, record)
        self.rehearsal_record = record
        path = self._save_record(record)
        self.loaded_record_path = path
        self.mode = "follow"
        self.rail_planner.stop("finished")
        return True, f"{len(self.rehearsal_samples)} 点 {path.name}", path

    def build_playback_plan(self, record: dict[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
        sparse = self._build_sparse_playback_plan(record, context)
        self.sparse_playback_plan = sparse
        dense = self._build_dense_playback_plan(sparse, record)
        record["playback_plan"] = sparse
        record["dense_playback_plan"] = dense
        return dense

    def build_playback_commands(self, selected_joints: set[str]) -> list[dict[str, Any]]:
        if self.playback_index >= len(self.playback_plan):
            self.mode = "follow"
            return []
        point = self.playback_plan[self.playback_index]
        self.playback_index += 1
        targets = point.get("targets_deg", {}) if isinstance(point.get("targets_deg"), Mapping) else {}
        return [
            {"joint_key": joint, "target_deg": float(value), "kind": "cinematic_playback", "plan_index": int(point.get("index", self.playback_index - 1))}
            for joint, value in targets.items()
            if joint == "j10" or joint in selected_joints
        ]

    def playback_interval_ms(self) -> int:
        hz = max(1.0, float(self.two_step_settings()["playback_hz"]))
        return max(20, int(round(1000.0 / hz)))

    def rail_current_mm(self, latest_robot_state: Mapping[str, Any]) -> float:
        if self.rail_planner.running:
            return float(self.rail_planner.virtual_pos_mm)
        return self._read_live_rail_mm(latest_robot_state, float(self.rail_planner.virtual_pos_mm))

    def rail_status_text(self, *, follow_running: bool, latest_robot_state: Mapping[str, Any]) -> str:
        if self.mode == "follow":
            return "关闭"
        if self.rail_planner.phase == "error":
            return "J10 错误"
        if not bool(self.rail_settings().get("enabled", False)):
            if self.mode == "rehearsal" and self.rail_planner.running:
                return f"试拍 {self.rail_current_mm(latest_robot_state):.1f}mm"
            return "关闭"
        if not follow_running:
            return "待启动"
        if self.rail_planner.phase == "seek_start":
            return f"回起点 {self.rail_current_mm(latest_robot_state):.1f}mm"
        if self.rail_planner.phase == "sweep":
            return f"扫轨中 {self.rail_current_mm(latest_robot_state):.1f}mm"
        if self.rail_planner.phase == "finished":
            return "已到终点"
        return "待启动"

    def sample_status_text(self) -> str:
        return f"{len(self.rehearsal_samples)} / {len(self.playback_plan)}"

    def rail_settings(self) -> dict[str, Any]:
        rail = dict(self.settings.get("rail", {}))
        rail.setdefault("joint", "j10")
        return rail

    def two_step_settings(self) -> dict[str, Any]:
        return dict(self.settings.get("two_step", {}))

    def _reset_rehearsal_data(self, *, clear_loaded_path: bool) -> None:
        self.rehearsal_samples = []
        self.sparse_playback_plan = []
        self.playback_plan = []
        self.playback_index = 0
        self.last_sample_at = 0.0
        if clear_loaded_path:
            self.loaded_record_path = None

    def _build_sparse_playback_plan(self, record: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
        samples = [item for item in record.get("samples", []) if isinstance(item, Mapping)]
        if len(samples) < 2:
            return []
        selected = [joint for joint in record.get("follow_joints", sorted(context.get("selected_joints", []))) if joint in FOLLOW_JOINT_AXES]
        if not selected:
            selected = sorted(str(joint) for joint in context.get("selected_joints", []) if str(joint) in FOLLOW_JOINT_AXES)
        two_step = self.two_step_settings()
        samples = self._monotonic_samples_in_capture_order(samples, min_progress_mm=max(0.01, float(two_step["min_rail_step_mm"]) * 0.25))
        if len(samples) < 2:
            return []
        smooth = max(0.0, min(0.95, float(two_step["playback_smooth"])))
        max_comp = max(0.0, float(two_step["max_compensation_deg"]))
        signs = context.get("signs", {}) if isinstance(context.get("signs"), Mapping) else {}
        pan_gain = float(context.get("pan_gain", 4.8))
        tilt_gain = float(context.get("tilt_gain", 4.8))
        previous_targets: dict[str, float] = {}
        plan: list[dict[str, Any]] = []
        for index, sample in enumerate(samples):
            joints = sample.get("joints_deg", {}) if isinstance(sample.get("joints_deg"), Mapping) else {}
            ndx = float(sample.get("ndx", 0.0))
            ndy = float(sample.get("ndy", 0.0))
            targets: dict[str, float] = {"j10": float(sample.get("j10_mm", 0.0))}
            for joint in selected:
                axis = FOLLOW_JOINT_AXES[joint]
                norm = ndx if axis == "pan" else ndy
                gain = pan_gain if axis == "pan" else tilt_gain
                correction = clamp_symmetric(norm * gain * float(signs.get(joint, 1.0)), max_comp)
                raw_target = float(joints.get(joint, 0.0)) + correction
                if joint in previous_targets:
                    raw_target = smooth * previous_targets[joint] + (1.0 - smooth) * raw_target
                targets[joint] = round(raw_target, 4)
                previous_targets[joint] = targets[joint]
            plan.append({"index": index, "timestamp": float(sample.get("timestamp", 0.0)), "j10_mm": targets["j10"], "targets_deg": targets, "source_error": {"ndx": ndx, "ndy": ndy}})
        return plan

    def _build_dense_playback_plan(self, sparse: list[dict[str, Any]], record: Mapping[str, Any]) -> list[dict[str, Any]]:
        if len(sparse) < 2:
            return []
        two_step = self.two_step_settings()
        hz = max(1.0, float(two_step["playback_hz"]))
        speed_scale = max(0.2, float(two_step["playback_speed_scale"]))
        rail_cfg = record.get("rail", {}) if isinstance(record.get("rail"), Mapping) else {}
        rail_speed = max(0.1, abs(float(rail_cfg.get("speed_mm_s", self.rail_settings()["speed_mm_s"]))))
        min_step = max(0.01, float(two_step["min_rail_step_mm"]))
        start_j10 = float(sparse[0].get("j10_mm", 0.0))
        end_j10 = float(sparse[-1].get("j10_mm", start_j10))
        distance = abs(end_j10 - start_j10)
        duration = max(0.2, distance / (rail_speed * speed_scale))
        steps = max(len(sparse), int(round(duration * hz)) + 1, int(round(distance / min_step)) + 1 if distance > 0 else 2, 2)
        interval = duration / max(1, steps - 1)
        source_positions = [float(item.get("j10_mm", 0.0)) for item in sparse]
        if source_positions[-1] < source_positions[0]:
            source_norms = [(source_positions[0] - pos) / max(distance, 1e-9) for pos in source_positions]
        else:
            source_norms = [(pos - source_positions[0]) / max(distance, 1e-9) for pos in source_positions]
        source_norms[0] = 0.0
        source_norms[-1] = 1.0

        selected = [joint for joint in sparse[0].get("targets_deg", {}) if joint != "j10"]
        dense: list[dict[str, Any]] = []
        for index in range(steps):
            linear_u = index / max(1, steps - 1)
            u = self._ease_progress(linear_u, duration)
            j10 = start_j10 + (end_j10 - start_j10) * u
            targets: dict[str, float] = {"j10": round(j10, 4)}
            left = self._left_index_for_u(source_norms, u)
            right = min(left + 1, len(sparse) - 1)
            span = max(1e-9, source_norms[right] - source_norms[left])
            ratio = smoothstep01((u - source_norms[left]) / span)
            for joint in selected:
                left_targets = sparse[left].get("targets_deg", {}) if isinstance(sparse[left].get("targets_deg"), Mapping) else {}
                right_targets = sparse[right].get("targets_deg", {}) if isinstance(sparse[right].get("targets_deg"), Mapping) else {}
                left_value = float(left_targets.get(joint, 0.0))
                right_value = float(right_targets.get(joint, left_value))
                raw = left_value + (right_value - left_value) * ratio
                targets[joint] = round(raw, 4)
            dense.append({"index": index, "time_sec": round(index * interval, 4), "j10_mm": targets["j10"], "targets_deg": targets, "source_index": left})
        return dense

    @staticmethod
    def _monotonic_samples_in_capture_order(samples: list[Mapping[str, Any]], *, min_progress_mm: float) -> list[Mapping[str, Any]]:
        ordered = sorted(samples, key=lambda item: float(item.get("timestamp", 0.0)))
        if len(ordered) < 2:
            return ordered
        start = float(ordered[0].get("j10_mm", 0.0))
        end = float(ordered[-1].get("j10_mm", start))
        direction = 1.0 if end >= start else -1.0
        kept: list[Mapping[str, Any]] = [ordered[0]]
        last_progress = 0.0
        for sample in ordered[1:-1]:
            progress = (float(sample.get("j10_mm", start)) - start) * direction
            if progress + 1e-6 < last_progress:
                continue
            if progress - last_progress < float(min_progress_mm):
                continue
            kept.append(sample)
            last_progress = progress
        if kept[-1] is not ordered[-1]:
            kept.append(ordered[-1])
        return kept

    def _reset_rail_state(self, live_rail_mm: float, *, force_enabled: bool = False) -> None:
        self.rail_planner.configure(self.rail_settings())
        self.rail_planner.reset(live_rail_mm, running=bool(self.rail_settings().get("enabled", False) or force_enabled))

    def _read_live_rail_mm(self, latest_robot_state: Mapping[str, Any], fallback: float) -> float:
        joints = latest_robot_state.get("joints_deg", {}) if isinstance(latest_robot_state.get("joints_deg"), Mapping) else {}
        if "j10" in joints:
            try:
                value = float(joints["j10"])
                self.rail_planner.current_mm(value)
                return value
            except (TypeError, ValueError):
                pass
        return float(fallback)

    def _save_record(self, record: dict[str, Any]) -> Path:
        self.record_dir.mkdir(parents=True, exist_ok=True)
        created = str(record.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        path = timestamped_json_path(self.record_dir, "cinematic_rehearsal", created)
        atomic_write_json(path, record)
        return path

    def _follow_cfg(self) -> dict[str, Any]:
        config = self._config_provider()
        follow = config.get("follow", {}) if isinstance(config, Mapping) else {}
        return dict(follow) if isinstance(follow, Mapping) else {}

    def _ease_progress(self, u: float, duration: float) -> float:
        return eased_end_progress(u, duration, float(self.two_step_settings()["ease_sec"]))

    @staticmethod
    def _left_index_for_u(norms: list[float], u: float) -> int:
        if len(norms) <= 1:
            return 0
        for index in range(len(norms) - 1):
            if norms[index] <= u <= norms[index + 1]:
                return index
        return max(0, len(norms) - 2)
