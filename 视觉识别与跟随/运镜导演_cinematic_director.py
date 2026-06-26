"""AI 摄影导演式运镜分析与轨迹生成。

本模块不直接控制机械臂，只把试拍视频/采样记录转换成可审阅的
关键帧与动作库 JSON。真实执行仍交给 GUI ControllerBridge 和动作回放器。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from vision.路径工具_path_utils import PROJECT_ROOT, ensure_project_root_on_path

ACTION_DIR = PROJECT_ROOT / "动作录制与回放增强"
ensure_project_root_on_path()

from 控制桥接_common import ensure_import_paths  # noqa: E402

ensure_import_paths((ACTION_DIR,))

from 动作工具_common import JOINT_ORDER, build_empty_sequence, normalize_joint_targets, now_text, refresh_sequence_pose_count  # noqa: E402
from 通用_io import atomic_write_json, read_json_object, resolve_path, timestamped_json_path  # noqa: E402


@dataclass
class DirectorDefaults:
    min_keyframes: int = 3
    max_keyframes: int = 8
    target_fps: float = 20.0
    dry_run_speed_percent: float = 50.0
    real_speed_percent: float = 30.0
    min_keyframe_gap_sec: float = 0.8
    max_joint_speed: dict[str, float] | None = None
    prefer_start_rail_side: bool = True
    strict_start_rail_side: bool = True
    rail_side_min_window_mm: float = 35.0
    rail_side_window_ratio: float = 0.38
    min_segment_duration_sec: float = 1.15
    endpoint_duration_scale: float = 1.55


class CinematicDirector:
    """从试拍采样中提取镜头语义，并生成平滑 Teach & Repeat 轨迹。"""

    def __init__(self, project_root: str | Path | None = None, defaults: DirectorDefaults | None = None):
        self.project_root = Path(project_root or PROJECT_ROOT).resolve()
        self.defaults = defaults or DirectorDefaults()
        if self.defaults.max_joint_speed is None:
            self.defaults.max_joint_speed = {
                "j10": 18.0,
                "j11": 32.0,
                "j12": 26.0,
                "j13": 32.0,
                "j14": 32.0,
                "j15": 45.0,
            }

    def load_record(self, path: str | Path) -> dict[str, Any]:
        record_path = self._resolve_path(path)
        data = read_json_object(record_path)
        data["_record_path"] = str(record_path)
        return data

    def analyze_take(self, video_path: str | Path | None = None, record: Mapping[str, Any] | None = None) -> dict[str, Any]:
        record_data = dict(record or {})
        samples = self._normalize_samples(record_data.get("samples", []))
        video_meta, video_metrics = self._analyze_video(video_path)
        sample_metrics = self._analyze_samples(samples, video_meta)
        metrics = self._merge_metrics(video_metrics, sample_metrics)
        intervals = self._classify_intervals(metrics)
        candidates = self._candidate_keyframes(metrics, intervals)
        return {
            "created_at": now_text(),
            "take_video": video_meta,
            "sample_count": len(samples),
            "samples": samples,
            "motion_analysis": {
                "summary": self._analysis_summary(metrics, intervals),
                "frame_metrics": metrics,
                "jitter_intervals": intervals["jitter"],
                "stable_intervals": intervals["stable"],
                "candidate_keyframes": candidates,
            },
        }

    def select_keyframes(
        self,
        project: Mapping[str, Any],
        min_count: int | None = None,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]:
        analysis = project.get("motion_analysis", {}) if isinstance(project.get("motion_analysis"), Mapping) else {}
        metrics = [item for item in analysis.get("frame_metrics", []) if isinstance(item, dict)]
        samples = [item for item in project.get("samples", []) if isinstance(item, dict)]
        if not metrics:
            raise ValueError("没有可用于选帧的运动分析结果。")

        min_count = max(3, min(8, int(min_count or self.defaults.min_keyframes)))
        max_count = max(min_count, min(8, int(max_count or self.defaults.max_keyframes)))
        duration = max(float(metrics[-1].get("time", 0.0)), 0.1)
        gap = max(self.defaults.min_keyframe_gap_sec, duration / max_count * 0.45)

        ranked = sorted(metrics, key=lambda item: float(item.get("director_score", 0.0)), reverse=True)
        ranked = self._prefer_same_rail_side(ranked, samples, min_count)
        chosen: list[dict[str, Any]] = []
        for metric in ranked:
            if len(chosen) >= max_count:
                break
            if self._too_close(metric, chosen, gap):
                continue
            sample = self._nearest_sample(samples, metric)
            keyframe = self._build_keyframe(len(chosen) + 1, metric, sample)
            if not keyframe.get("pose", {}).get("joints_deg"):
                keyframe["executable"] = False
                keyframe["reason"] += "；缺少同步关节状态，仅可作为镜头建议"
            chosen.append(keyframe)

        if len(chosen) < min_count:
            relaxed_gap = max(0.25, gap * 0.45)
            for metric in ranked:
                if len(chosen) >= min_count:
                    break
                if self._too_close(metric, chosen, relaxed_gap):
                    continue
                sample = self._nearest_sample(samples, metric)
                chosen.append(self._build_keyframe(len(chosen) + 1, metric, sample))

        chosen = sorted(chosen, key=lambda item: float(item["time"]))
        for index, item in enumerate(chosen, start=1):
            item["id"] = f"K{index}"
        return chosen

    def build_trajectory(self, keyframes: list[dict[str, Any]]) -> dict[str, Any]:
        usable = [item for item in keyframes if item.get("pose", {}).get("joints_deg")]
        if len(usable) < 2:
            raise ValueError("至少需要 2 个带同步关节姿态的关键帧才能生成轨迹。")

        points: list[dict[str, Any]] = []
        for index, keyframe in enumerate(usable):
            pose = keyframe["pose"]["joints_deg"]
            points.append(
                {
                    "index": index,
                    "time": float(keyframe.get("time", 0.0)),
                    "keyframe_id": keyframe.get("id", f"K{index + 1}"),
                    "targets_deg": normalize_joint_targets(pose, JOINT_ORDER),
                    "dwell_time": float(keyframe.get("dwell_time", 0.0)),
                }
            )

        points = self._assign_keypoint_durations(points)
        return {
            "type": "teach_repeat_keyframe_interpolation",
            "points": points,
            "key_points": points,
            "blending_strategy": {
                "enabled": True,
                "mode": "pass_through",
                "blend_radius_equivalent": "只保存导演关键姿态；中间关键帧 hold=0，由动作库播放器做平滑插值。",
            },
            "speed_profile": {
                "start": "ease-in",
                "middle": "action-library smooth interpolation",
                "end": "ease-out",
                "target_fps": self.defaults.target_fps,
                "min_segment_duration_sec": self.defaults.min_segment_duration_sec,
                "endpoint_duration_scale": self.defaults.endpoint_duration_scale,
            },
            "recommended_execution": {
                "dry_run_speed_percent": self.defaults.dry_run_speed_percent,
                "real_speed_percent": self.defaults.real_speed_percent,
                "acceleration_limit": "software eased interpolation; do not bypass servo safety",
                "enable_blend": True,
                "skip_jittery_start_end": True,
                "recommended_takes": "3-10 takes; choose best semantic take before real replay",
            },
        }

    def build_action_payload(self, name: str, project: Mapping[str, Any], trajectory: Mapping[str, Any]) -> dict[str, Any]:
        sequence = build_empty_sequence(
            name=name,
            description="AI 摄影导演从试拍语义重建的平滑运镜动作",
            source="ai_cinematic_director",
        )
        poses = []
        points = [item for item in trajectory.get("key_points", trajectory.get("points", [])) if isinstance(item, dict)]
        for index, point in enumerate(points, start=1):
            targets = normalize_joint_targets(point.get("targets_deg", {}), JOINT_ORDER)
            duration = float(point.get("duration_sec", 1.2))
            pose = {
                "index": index,
                "name": f"director_keyframe_{index:02d}",
                "recorded_at": now_text(),
                "duration_sec": max(0.45, duration),
                "hold_sec": float(point.get("hold_sec", 0.0)),
                "joint_targets_deg": targets,
                "replay_joint_targets_deg": targets,
                "tcp_pose": None,
                "raw_present_position": None,
                "multi_turn_state": {},
                "replay_multi_turn_continuous_raw": {},
                "gripper": {"available": False},
                "cinematic_point": {
                    "source_keyframe": point.get("keyframe_id"),
                    "curve_t": 1.0,
                    "pass_through": bool(point.get("pass_through", True)),
                    "duration_policy": "action_library_distance_duration",
                },
            }
            poses.append(pose)
        sequence["poses"] = poses
        refresh_sequence_pose_count(sequence)
        sequence["playback"]["default_interval_sec"] = 0.0
        sequence["cinematic"] = {
            "schema_version": "cinematic_director_v1",
            "pass_through": True,
            "keyframes": list(project.get("director_keyframes", [])),
            "trajectory_plan": dict(trajectory),
        }
        return sequence

    def save_project(self, project: Mapping[str, Any], output_dir: str | Path | None = None) -> Path:
        base = Path(output_dir or self.project_root / "视觉识别与跟随" / "runtime" / "cinematic_director_projects")
        base.mkdir(parents=True, exist_ok=True)
        path = timestamped_json_path(base, "cinematic_director")
        atomic_write_json(path, dict(project))
        return path

    def _analyze_video(self, video_path: str | Path | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not video_path:
            return {"path": "", "available": False, "fps": 0.0, "frame_count": 0, "duration_sec": 0.0}, []
        path = self._resolve_path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"视频不存在：{path}")
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"OpenCV/numpy 不可用，无法分析视频：{exc}") from exc

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"视频打开失败：{path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        metrics: list[dict[str, Any]] = []
        prev_gray = None
        prev_points = None
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            motion = 0.0
            if prev_gray is not None:
                if prev_points is None or len(prev_points) < 8:
                    prev_points = cv2.goodFeaturesToTrack(prev_gray, maxCorners=80, qualityLevel=0.01, minDistance=8)
                if prev_points is not None:
                    next_points, status, _err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_points, None)
                    if next_points is not None and status is not None:
                        good_prev = prev_points[status.flatten() == 1]
                        good_next = next_points[status.flatten() == 1]
                        if len(good_prev) > 0:
                            delta = good_next.reshape(-1, 2) - good_prev.reshape(-1, 2)
                            motion = float(np.median(np.linalg.norm(delta, axis=1)))
                    prev_points = cv2.goodFeaturesToTrack(gray, maxCorners=80, qualityLevel=0.01, minDistance=8)
            metrics.append(
                {
                    "frame_index": index,
                    "time": index / max(1.0, fps),
                    "sharpness": sharpness,
                    "motion_energy": motion,
                    "source": "video",
                }
            )
            prev_gray = gray
            index += 1
        cap.release()
        duration = index / max(1.0, fps)
        return {"path": str(path), "available": True, "fps": fps, "frame_count": index or frame_count, "duration_sec": duration}, metrics

    def _analyze_samples(self, samples: list[dict[str, Any]], video_meta: Mapping[str, Any]) -> list[dict[str, Any]]:
        if not samples:
            return []
        first_ts = float(samples[0].get("timestamp", 0.0))
        fps = float(video_meta.get("fps") or 0.0)
        metrics = []
        prev = None
        for index, sample in enumerate(samples):
            timestamp = float(sample.get("timestamp", first_ts + index * 0.12))
            time_sec = float(sample.get("time", timestamp - first_ts))
            frame_index = int(sample.get("frame_index", round(time_sec * fps) if fps > 0 else index))
            ndx = float(sample.get("ndx", 0.0))
            ndy = float(sample.get("ndy", 0.0))
            joint_motion = 0.0
            offset_motion = 0.0
            if prev is not None:
                dt = max(0.001, timestamp - float(prev.get("timestamp", timestamp - 0.12)))
                offset_motion = math.hypot(ndx - float(prev.get("ndx", 0.0)), ndy - float(prev.get("ndy", 0.0))) / dt
                joints = sample.get("joints_deg", {}) if isinstance(sample.get("joints_deg"), Mapping) else {}
                prev_joints = prev.get("joints_deg", {}) if isinstance(prev.get("joints_deg"), Mapping) else {}
                joint_motion = max(abs(float(joints.get(j, 0.0)) - float(prev_joints.get(j, 0.0))) / dt for j in JOINT_ORDER)
            composition = max(0.0, 1.0 - min(1.0, math.hypot(ndx, ndy) / 0.65))
            metrics.append(
                {
                    "frame_index": frame_index,
                    "time": time_sec,
                    "timestamp": timestamp,
                    "sharpness": 0.0,
                    "motion_energy": offset_motion + 0.08 * joint_motion,
                    "subject_offset_norm": math.hypot(ndx, ndy),
                    "composition_score": composition,
                    "source": "samples",
                    "sample_index": index,
                    "j10_mm": sample.get("j10_mm"),
                    "bbox": sample.get("bbox"),
                }
            )
            prev = sample
        return metrics

    def _merge_metrics(self, video_metrics: list[dict[str, Any]], sample_metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        metrics = sample_metrics or video_metrics
        if not metrics:
            return []
        max_sharp = max(float(item.get("sharpness", 0.0)) for item in metrics) or 1.0
        motion_values = [float(item.get("motion_energy", 0.0)) for item in metrics]
        max_motion = max(motion_values) or 1.0
        for item in metrics:
            sharp = float(item.get("sharpness", 0.0)) / max_sharp if max_sharp else 0.0
            stable = 1.0 - min(1.0, float(item.get("motion_energy", 0.0)) / max_motion)
            composition = float(item.get("composition_score", 0.72 if not sample_metrics else 0.0))
            item["sharpness_score"] = round(sharp, 4)
            item["stability_score"] = round(stable, 4)
            item["composition_score"] = round(composition, 4)
            item["director_score"] = round(0.32 * sharp + 0.38 * stable + 0.30 * composition, 4)
        return metrics

    def _classify_intervals(self, metrics: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        if not metrics:
            return {"jitter": [], "stable": []}
        stable_flags = [float(item.get("stability_score", 0.0)) >= 0.62 for item in metrics]
        jitter_flags = [float(item.get("stability_score", 0.0)) <= 0.32 for item in metrics]
        return {
            "stable": self._flags_to_intervals(metrics, stable_flags, "stable"),
            "jitter": self._flags_to_intervals(metrics, jitter_flags, "jitter"),
        }

    def _flags_to_intervals(self, metrics: list[dict[str, Any]], flags: list[bool], kind: str) -> list[dict[str, Any]]:
        intervals = []
        start = None
        for index, flag in enumerate(flags + [False]):
            if flag and start is None:
                start = index
            if not flag and start is not None:
                end = index - 1
                if end >= start:
                    intervals.append(
                        {
                            "kind": kind,
                            "start_frame": int(metrics[start].get("frame_index", start)),
                            "end_frame": int(metrics[end].get("frame_index", end)),
                            "start_time": round(float(metrics[start].get("time", 0.0)), 3),
                            "end_time": round(float(metrics[end].get("time", 0.0)), 3),
                        }
                    )
                start = None
        return intervals

    def _candidate_keyframes(self, metrics: list[dict[str, Any]], intervals: Mapping[str, Any]) -> list[dict[str, Any]]:
        candidates = []
        stable_intervals = intervals.get("stable") if isinstance(intervals.get("stable"), list) else []
        for interval in stable_intervals[:8]:
            start_time = float(interval.get("start_time", 0.0))
            end_time = float(interval.get("end_time", start_time))
            inside = [item for item in metrics if start_time <= float(item.get("time", 0.0)) <= end_time]
            if inside:
                best = max(inside, key=lambda item: float(item.get("director_score", 0.0)))
                candidates.append(self._metric_brief(best, "稳定区间最佳帧"))
        if not candidates and metrics:
            for item in sorted(metrics, key=lambda row: float(row.get("director_score", 0.0)), reverse=True)[:5]:
                candidates.append(self._metric_brief(item, "综合评分候选帧"))
        return candidates

    def _build_keyframe(self, index: int, metric: Mapping[str, Any], sample: Mapping[str, Any] | None) -> dict[str, Any]:
        ndx = float(metric.get("subject_offset_norm", 0.0))
        joints = sample.get("joints_deg", {}) if isinstance(sample, Mapping) and isinstance(sample.get("joints_deg"), Mapping) else {}
        composition = self._composition_text(metric)
        reason = (
            f"综合评分 {float(metric.get('director_score', 0.0)):.2f}，"
            f"稳定度 {float(metric.get('stability_score', 0.0)):.2f}，"
            f"构图偏移 {ndx:.2f}"
        )
        return {
            "id": f"K{index}",
            "time": round(float(metric.get("time", 0.0)), 3),
            "timestamp": metric.get("timestamp"),
            "frame_index": int(metric.get("frame_index", index - 1)),
            "j10_mm": metric.get("j10_mm"),
            "pose": {"joints_deg": normalize_joint_targets(joints, JOINT_ORDER) if joints else {}},
            "composition": composition,
            "reason": reason,
            "dwell_time": 0.0,
            "executable": bool(joints),
        }

    def _assign_keypoint_durations(self, key_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not key_points:
            return []
        result: list[dict[str, Any]] = []
        for index, point in enumerate(key_points):
            item = dict(point)
            if index == 0:
                item["duration_sec"] = 1.0
            else:
                item["duration_sec"] = self._segment_duration(key_points[index - 1]["targets_deg"], point["targets_deg"], index - 1, len(key_points) - 2)
            item["hold_sec"] = max(0.0, float(point.get("dwell_time", 0.0)))
            item["pass_through"] = index < len(key_points) - 1
            result.append(item)
        return result

    def _segment_duration(self, start: Mapping[str, float], end: Mapping[str, float], segment_index: int, last_segment_index: int) -> float:
        required = float(self.defaults.min_segment_duration_sec)
        for joint in JOINT_ORDER:
            speed = float((self.defaults.max_joint_speed or {}).get(joint, 30.0))
            required = max(required, abs(float(end[joint]) - float(start[joint])) / max(1.0, speed))
        if segment_index in {0, last_segment_index}:
            required *= float(self.defaults.endpoint_duration_scale)
        return max(float(self.defaults.min_segment_duration_sec), min(7.5, required))

    def _analysis_summary(self, metrics: list[dict[str, Any]], intervals: Mapping[str, Any]) -> dict[str, Any]:
        if not metrics:
            return {"message": "没有可分析的数据。"}
        return {
            "frame_count": len(metrics),
            "avg_stability": round(sum(float(item.get("stability_score", 0.0)) for item in metrics) / len(metrics), 3),
            "avg_composition": round(sum(float(item.get("composition_score", 0.0)) for item in metrics) / len(metrics), 3),
            "stable_interval_count": len(intervals.get("stable", [])),
            "jitter_interval_count": len(intervals.get("jitter", [])),
            "message": "试拍已作为运动采样分析，最终轨迹将从关键帧重建而非逐帧复刻。",
        }

    def _normalize_samples(self, samples: Any) -> list[dict[str, Any]]:
        if not isinstance(samples, list):
            return []
        normalized = []
        for index, item in enumerate(samples):
            if not isinstance(item, Mapping):
                continue
            row = dict(item)
            row.setdefault("sample_index", index)
            if "joints_deg" in row and isinstance(row["joints_deg"], Mapping):
                row["joints_deg"] = normalize_joint_targets(row["joints_deg"], JOINT_ORDER)
            normalized.append(row)
        return normalized

    def _nearest_sample(self, samples: list[dict[str, Any]], metric: Mapping[str, Any]) -> dict[str, Any] | None:
        if not samples:
            return None
        if "sample_index" in metric:
            index = int(metric.get("sample_index", 0))
            if 0 <= index < len(samples):
                return samples[index]
        target_time = float(metric.get("timestamp", metric.get("time", 0.0)) or 0.0)
        key = "timestamp" if any("timestamp" in item for item in samples) and metric.get("timestamp") is not None else "time"
        return min(samples, key=lambda item: abs(float(item.get(key, 0.0)) - target_time))

    def _prefer_same_rail_side(self, ranked: list[dict[str, Any]], samples: list[dict[str, Any]], min_count: int) -> list[dict[str, Any]]:
        if not ranked or not samples:
            return ranked
        rail_values = []
        for sample in samples:
            try:
                rail_values.append(float(sample.get("j10_mm", sample.get("joints_deg", {}).get("j10"))))
            except Exception:
                pass
        if len(rail_values) < 2:
            return ranked
        span = max(rail_values) - min(rail_values)
        if span < 35.0:
            return ranked
        try:
            anchor_sample = samples[0] if self.defaults.prefer_start_rail_side else (self._nearest_sample(samples, ranked[0]) or samples[0])
            anchor = float(anchor_sample.get("j10_mm", anchor_sample.get("joints_deg", {}).get("j10")))
        except Exception:
            return ranked
        window = max(float(self.defaults.rail_side_min_window_mm), span * float(self.defaults.rail_side_window_ratio))
        midpoint = (min(rail_values) + max(rail_values)) * 0.5
        anchor_on_lower_side = anchor <= midpoint
        near: list[dict[str, Any]] = []
        same_side: list[dict[str, Any]] = []
        far: list[dict[str, Any]] = []
        for metric in ranked:
            sample = self._nearest_sample(samples, metric)
            try:
                value = float(sample.get("j10_mm", sample.get("joints_deg", {}).get("j10"))) if sample else anchor
            except Exception:
                value = anchor
            if abs(value - anchor) <= window:
                near.append(metric)
            if (value <= midpoint) == anchor_on_lower_side:
                same_side.append(metric)
            else:
                far.append(metric)
        required = max(3, int(min_count))
        if self.defaults.strict_start_rail_side:
            strict = self._dedupe_metrics(near + same_side)
            if strict:
                return strict
        if len(near) >= required:
            return near
        if len(same_side) >= required:
            return same_side
        return self._dedupe_metrics(near + same_side + far)

    @staticmethod
    def _dedupe_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[int, float]] = set()
        result: list[dict[str, Any]] = []
        for metric in metrics:
            key = (int(metric.get("frame_index", -1)), round(float(metric.get("time", 0.0)), 4))
            if key in seen:
                continue
            seen.add(key)
            result.append(metric)
        return result

    def _too_close(self, metric: Mapping[str, Any], chosen: list[dict[str, Any]], gap: float) -> bool:
        time_value = float(metric.get("time", 0.0))
        return any(abs(float(item.get("time", 0.0)) - time_value) < gap for item in chosen)

    def _metric_brief(self, metric: Mapping[str, Any], reason: str) -> dict[str, Any]:
        return {
            "frame_index": int(metric.get("frame_index", 0)),
            "time": round(float(metric.get("time", 0.0)), 3),
            "score": float(metric.get("director_score", 0.0)),
            "reason": reason,
        }

    def _composition_text(self, metric: Mapping[str, Any]) -> str:
        offset = float(metric.get("subject_offset_norm", 0.0))
        if offset <= 0.08:
            return "主体接近视觉中心，适合作为展示点。"
        if offset <= 0.22:
            return "主体略偏离中心，画面有自然运动空间。"
        return "主体偏离中心较明显，可作为运动过渡点而非最终展示点。"

    def _resolve_path(self, value: str | Path) -> Path:
        return resolve_path(value, self.project_root)


def load_project(path: str | Path) -> dict[str, Any]:
    return read_json_object(path)
