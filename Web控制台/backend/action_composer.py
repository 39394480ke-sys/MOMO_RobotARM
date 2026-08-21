"""本地动作关键帧编排、轨迹采样与 PyBullet 预览。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
import uuid
from typing import Any, Mapping

from .path_utils import PROJECT_ROOT, ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import JOINT_ORDER, install_stage_paths, normalize_joint_targets, targets_to_kinematics_q  # noqa: E402

install_stage_paths(PROJECT_ROOT)

from 动作工具_common import active_robot_variant, build_empty_sequence, refresh_sequence_pose_count  # noqa: E402
from 动作轨迹采样_trajectory_sampling import (  # noqa: E402
    effective_segment_duration,
    sample_bounded_cinematic,
)


class ActionComposerError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)


@dataclass
class PreviewSession:
    preview_id: str
    created_at: float
    sequence: dict[str, Any]
    targets: list[dict[str, float]]
    segments: list[dict[str, float]]
    total_duration_sec: float


class ActionComposer:
    """只读地解析本地素材，并把编排结果保存为新动作。"""

    def __init__(self, bridge: Any, *, preview_ttl_sec: float = 600.0):
        self.bridge = bridge
        self.preview_ttl_sec = max(30.0, float(preview_ttl_sec))
        self._sessions: dict[str, PreviewSession] = {}
        self._lock = threading.RLock()
        self._preview_model: Any | None = None
        self._preview_error = ""

    def close(self) -> None:
        with self._lock:
            model, self._preview_model = self._preview_model, None
            self._sessions.clear()
        if model is not None and hasattr(model, "close"):
            model.close()

    def sources(self) -> dict[str, Any]:
        library = self.bridge._get_action_library()
        variant = active_robot_variant(library.config)
        actions: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for name in library.list_actions():
            try:
                sequence = library.load_action(name)
                report = sequence.get("_robot_variant_preview", {})
                if not bool(report.get("匹配")):
                    continue
                frames = [self._source_frame_summary(pose, index) for index, pose in enumerate(sequence.get("poses", []))]
                if frames:
                    actions.append({"name": name, "frame_count": len(frames), "frames": frames})
            except Exception as exc:
                skipped.append({"name": name, "message": str(exc)})

        poses: list[dict[str, Any]] = []
        manager = self.bridge._get_pose_manager()
        for name in manager.列出姿态():
            try:
                pose = manager.获取姿态(name)
                if not isinstance(pose, Mapping):
                    continue
                pose_variant = str(pose.get("robot_variant") or "").strip()
                if pose_variant and pose_variant != variant:
                    continue
                targets = self._strict_targets(pose.get("关节角度"), f"姿态“{name}”")
                poses.append(
                    {
                        "name": name,
                        "description": str(pose.get("说明") or ""),
                        "robot_variant": pose_variant or variant,
                        "legacy_variant_assumed": not bool(pose_variant),
                        "joints_deg": targets,
                        "gripper": self._normalize_gripper(pose.get("夹爪")),
                    }
                )
            except Exception as exc:
                skipped.append({"name": name, "message": str(exc)})
        return {"robot_variant": variant, "actions": actions, "poses": poses, "skipped": skipped}

    def create_preview(self, request: Any) -> dict[str, Any]:
        sequence = self._build_sequence(request, save_name=None)
        targets, segments, total = self._timeline(sequence)
        self._ensure_preview_model()
        preview_id = uuid.uuid4().hex
        session = PreviewSession(preview_id, time.time(), sequence, targets, segments, total)
        with self._lock:
            self._purge_expired_locked()
            self._sessions[preview_id] = session
            while len(self._sessions) > 8:
                oldest = min(self._sessions.values(), key=lambda item: item.created_at)
                self._sessions.pop(oldest.preview_id, None)
        return {
            "preview_id": preview_id,
            "robot_variant": sequence["robot_variant"],
            "frame_count": len(targets),
            "total_duration_sec": round(total, 3),
            "entry_duration_sec": float(sequence["playback"]["entry_duration_sec"]),
            "segments": segments,
        }

    def render_preview(self, preview_id: str, elapsed_sec: float, width: int, height: int) -> tuple[bytes, str]:
        with self._lock:
            self._purge_expired_locked()
            session = self._sessions.get(str(preview_id))
            if session is None:
                raise ActionComposerError("ACTION_COMPOSER_PREVIEW_EXPIRED", "仿真预览已过期，请重新生成。", 404)
            targets = self._sample_session(session, float(elapsed_sec))
            model = self._ensure_preview_model()
            return self._render_model(model, targets, width, height), "image/jpeg"

    def delete_preview(self, preview_id: str) -> dict[str, Any]:
        with self._lock:
            removed = self._sessions.pop(str(preview_id), None)
        return {"deleted": removed is not None, "preview_id": str(preview_id)}

    def save(self, request: Any) -> dict[str, Any]:
        name = self._normalize_action_name(request.name)
        library = self.bridge._get_action_library()
        if library.action_path(name).exists():
            raise ActionComposerError("ACTION_NAME_CONFLICT", f"动作库中已存在“{name}”，请换一个名称。", 409)
        sequence = self._build_sequence(request, save_name=name)
        path = library.save_action(name, sequence)
        _, segments, total = self._timeline(sequence)
        return {
            "message": f"已保存新动作：{name}",
            "name": name,
            "path": str(path),
            "pose_count": len(sequence["poses"]),
            "total_duration_sec": round(total, 3),
            "segments": segments,
        }

    def _build_sequence(self, request: Any, save_name: str | None) -> dict[str, Any]:
        refs = list(request.frames)
        if len(refs) < 2:
            raise ActionComposerError("ACTION_COMPOSER_TOO_SHORT", "轨迹编排至少需要两个关键帧。")
        library = self.bridge._get_action_library()
        config = library.config
        variant = active_robot_variant(config)
        action_cache: dict[str, dict[str, Any]] = {}
        pose_manager = self.bridge._get_pose_manager()
        resolved: list[dict[str, Any]] = []

        for output_index, ref in enumerate(refs, 1):
            kind = str(ref.source_kind)
            source_name = str(ref.source_name).strip()
            if kind == "action":
                if source_name not in action_cache:
                    try:
                        source_action = library.load_action(source_name)
                    except FileNotFoundError as exc:
                        raise ActionComposerError("ACTION_COMPOSER_SOURCE_MISSING", f"来源动作不存在：{source_name}", 404) from exc
                    report = source_action.get("_robot_variant_preview", {})
                    if not bool(report.get("匹配")):
                        raise ActionComposerError("ACTION_COMPOSER_VARIANT_MISMATCH", str(report.get("问题") or "动作型号不匹配。"))
                    action_cache[source_name] = source_action
                source_action = action_cache[source_name]
                source_frames = source_action.get("poses", [])
                frame_index = ref.source_frame_index
                if frame_index is None or frame_index < 0 or frame_index >= len(source_frames):
                    raise ActionComposerError("ACTION_COMPOSER_FRAME_MISSING", f"动作“{source_name}”的关键帧已不存在。", 404)
                source_pose = source_frames[frame_index]
                targets = self._strict_targets(
                    source_pose.get("joint_targets_deg") or source_pose.get("replay_joint_targets_deg"),
                    f"动作“{source_name}”第 {frame_index + 1} 帧",
                )
                gripper = self._normalize_gripper(source_pose.get("gripper"))
                default_label = str(source_pose.get("name") or f"{source_name} #{frame_index + 1}")
                source_ref = {"kind": "action", "name": source_name, "frame_index": int(frame_index)}
            else:
                source_pose = pose_manager.获取姿态(source_name)
                if not isinstance(source_pose, Mapping):
                    raise ActionComposerError("ACTION_COMPOSER_SOURCE_MISSING", f"来源姿态不存在：{source_name}", 404)
                source_variant = str(source_pose.get("robot_variant") or "").strip()
                if source_variant and source_variant != variant:
                    raise ActionComposerError(
                        "ACTION_COMPOSER_VARIANT_MISMATCH",
                        f"姿态“{source_name}”属于 {source_variant}，当前配置为 {variant}。",
                    )
                targets = self._strict_targets(source_pose.get("关节角度"), f"姿态“{source_name}”")
                gripper = self._normalize_gripper(source_pose.get("夹爪"))
                default_label = source_name
                source_ref = {"kind": "pose", "name": source_name, "legacy_variant_assumed": not bool(source_variant)}

            tcp_pose = self._tcp_pose(targets)
            pose: dict[str, Any] = {
                "index": output_index,
                "name": str(ref.label or default_label).strip()[:64] or f"frame_{output_index:02d}",
                "duration_sec": 0.0 if output_index == 1 else float(ref.duration_sec),
                "hold_sec": float(ref.hold_sec),
                "joint_targets_deg": targets,
                "source_ref": source_ref,
            }
            if gripper is not None:
                pose["gripper"] = gripper
            if tcp_pose is not None:
                pose["tcp_pose"] = tcp_pose
            resolved.append(pose)

        name = save_name or "未保存轨迹"
        sequence = build_empty_sequence(name, str(request.description or "").strip(), "web_composer", config)
        sequence["robot_variant"] = variant
        sequence["poses"] = resolved
        sequence["playback"].update(
            {
                "position_before_replay": True,
                "entry_duration_sec": float(request.entry_duration_sec),
            }
        )
        sequence["cinematic"] = {"pass_through": True, "honor_keyframe_holds": True}
        sequence["source_refs"] = [dict(pose["source_ref"]) for pose in resolved]
        refresh_sequence_pose_count(sequence)
        return sequence

    def _timeline(self, sequence: Mapping[str, Any]) -> tuple[list[dict[str, float]], list[dict[str, float]], float]:
        poses = list(sequence.get("poses", []))
        targets = [self._strict_targets(pose.get("joint_targets_deg"), f"关键帧 {index + 1}") for index, pose in enumerate(poses)]
        playback = self.bridge._get_action_library().config.get("playback", {})
        segments: list[dict[str, float]] = []
        cursor = max(0.0, float(poses[0].get("hold_sec", 0.0)))
        for index in range(1, len(poses)):
            requested = float(poses[index].get("duration_sec", 0.0))
            effective = effective_segment_duration(
                poses[index],
                playback,
                targets[index - 1],
                targets[index],
                enforce_real_minimum=True,
            )
            segment = {
                "index": index - 1,
                "start_sec": cursor,
                "duration_sec": effective,
                "requested_duration_sec": requested,
                "hold_sec": max(0.0, float(poses[index].get("hold_sec", 0.0))),
            }
            cursor += effective
            segment["arrival_sec"] = cursor
            cursor += segment["hold_sec"]
            segments.append(segment)
        return targets, segments, cursor

    @staticmethod
    def _sample_session(session: PreviewSession, elapsed_sec: float) -> dict[str, float]:
        if not session.targets:
            return {}
        t = max(0.0, min(float(elapsed_sec), session.total_duration_sec))
        first_hold = max(0.0, float(session.sequence["poses"][0].get("hold_sec", 0.0)))
        if t <= first_hold or not session.segments:
            return dict(session.targets[0])
        for segment in session.segments:
            start = float(segment["start_sec"])
            arrival = float(segment["arrival_sec"])
            index = int(segment["index"])
            if t < arrival:
                ratio = (t - start) / max(1e-6, float(segment["duration_sec"]))
                return sample_bounded_cinematic(session.targets, index, ratio)
            if t <= arrival + float(segment["hold_sec"]):
                return dict(session.targets[index + 1])
        return dict(session.targets[-1])

    def _source_frame_summary(self, pose: Any, index: int) -> dict[str, Any]:
        if not isinstance(pose, Mapping):
            raise ValueError(f"第 {index + 1} 帧不是对象。")
        targets = self._strict_targets(
            pose.get("joint_targets_deg") or pose.get("replay_joint_targets_deg"),
            f"第 {index + 1} 帧",
        )
        return {
            "frame_index": index,
            "display_index": index + 1,
            "name": str(pose.get("name") or f"pose_{index + 1}"),
            "duration_sec": float(pose.get("duration_sec", 0.0) or 0.0),
            "hold_sec": float(pose.get("hold_sec", 0.0) or 0.0),
            "joints_deg": targets,
            "gripper": self._normalize_gripper(pose.get("gripper")),
        }

    @staticmethod
    def _strict_targets(value: Any, source_label: str) -> dict[str, float]:
        if isinstance(value, Mapping):
            normalized = normalize_joint_targets(value, JOINT_ORDER, fill_missing=False)
        elif isinstance(value, (list, tuple)) and len(value) == len(JOINT_ORDER):
            normalized = normalize_joint_targets(value, JOINT_ORDER, fill_missing=False)
        else:
            raise ActionComposerError("ACTION_COMPOSER_INVALID_FRAME", f"{source_label}必须包含 J10-J15 六关节目标。")
        if set(normalized) != set(JOINT_ORDER):
            missing = [joint.upper() for joint in JOINT_ORDER if joint not in normalized]
            raise ActionComposerError("ACTION_COMPOSER_INVALID_FRAME", f"{source_label}缺少关节：{', '.join(missing)}。")
        if not all(math.isfinite(float(value)) for value in normalized.values()):
            raise ActionComposerError("ACTION_COMPOSER_INVALID_FRAME", f"{source_label}包含非法关节数值。")
        return {joint: float(normalized[joint]) for joint in JOINT_ORDER}

    @staticmethod
    def _normalize_gripper(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            if value.get("available") is False:
                return {"available": False}
            raw = value.get("open_percent")
            if raw is None and value.get("open_ratio") is not None:
                raw = float(value["open_ratio"]) * 100.0
            if raw is None:
                return None
        else:
            raw = value
        number = max(0.0, min(100.0, float(raw)))
        return {"available": True, "open_percent": number, "open_ratio": number / 100.0}

    def _tcp_pose(self, targets: Mapping[str, float]) -> dict[str, Any] | None:
        try:
            model = self._ensure_preview_model()
            pose = model.forward(targets_to_kinematics_q(targets))
            return {"xyz": list(pose.get("xyz", [])), "rpy": list(pose.get("rpy", [])), "source": "composer_fk"}
        except Exception:
            return None

    def _ensure_preview_model(self) -> Any:
        with self._lock:
            if self._preview_model is not None:
                return self._preview_model
            model, error = self.bridge.create_preview_kinematics_model()
            if model is None:
                self._preview_error = str(error or "运动学模型不可用。")
                raise ActionComposerError("ACTION_COMPOSER_PREVIEW_UNAVAILABLE", f"仿真预览不可用：{self._preview_error}", 503)
            self._preview_model = model
            self._preview_error = ""
            return model

    @staticmethod
    def _render_model(model: Any, targets: Mapping[str, float], width: int, height: int) -> bytes:
        try:
            import cv2
            import numpy as np
            import pybullet as pb
        except Exception as exc:
            raise ActionComposerError("ACTION_COMPOSER_PREVIEW_UNAVAILABLE", f"仿真渲染依赖不可用：{exc}", 503) from exc

        width = max(320, min(960, int(width or 640)))
        height = max(240, min(720, int(height or 420)))
        model.forward(targets_to_kinematics_q(targets))
        yaw = math.radians(-55.0)
        pitch = math.radians(28.0)
        distance = 0.62
        target = [0.0, 0.0, 0.16]
        horizontal = distance * math.cos(pitch)
        eye = [
            target[0] + horizontal * math.cos(yaw),
            target[1] + horizontal * math.sin(yaw),
            target[2] + distance * math.sin(pitch),
        ]
        view = pb.computeViewMatrix(eye, target, [0.0, 0.0, 1.0])
        projection = pb.computeProjectionMatrixFOV(45.0, float(width) / float(height), 0.01, 4.0)
        try:
            _, _, rgba, _, _ = pb.getCameraImage(
                width,
                height,
                viewMatrix=view,
                projectionMatrix=projection,
                renderer=pb.ER_BULLET_HARDWARE_OPENGL,
                physicsClientId=model._client_id,
            )
        except Exception:
            _, _, rgba, _, _ = pb.getCameraImage(
                width,
                height,
                viewMatrix=view,
                projectionMatrix=projection,
                renderer=pb.ER_TINY_RENDERER,
                physicsClientId=model._client_id,
            )
        rgb = np.asarray(rgba, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]
        ok, buffer = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 84])
        if not ok:
            raise ActionComposerError("ACTION_COMPOSER_PREVIEW_FAILED", "仿真画面编码失败。", 500)
        return bytes(buffer)

    @staticmethod
    def _normalize_action_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ActionComposerError("ACTION_COMPOSER_NAME_REQUIRED", "请输入新动作名称。")
        if len(name) > 64:
            raise ActionComposerError("ACTION_COMPOSER_NAME_INVALID", "动作名称不能超过 64 个字符。")
        if name.lower().endswith(".json") or name in {".", ".."} or any(char in name for char in ("/", "\\", "\x00")):
            raise ActionComposerError("ACTION_COMPOSER_NAME_INVALID", "动作名称不能包含路径字符或 .json 后缀。")
        return name

    def _purge_expired_locked(self) -> None:
        cutoff = time.time() - self.preview_ttl_sec
        for preview_id, session in list(self._sessions.items()):
            if session.created_at < cutoff:
                self._sessions.pop(preview_id, None)
