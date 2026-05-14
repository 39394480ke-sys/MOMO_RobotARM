"""阶段六动作文件管理。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from 动作工具_common import SCHEMA_VERSION, load_config, read_json, resolve_stage6_path, write_json


class ActionLibrary:
    def __init__(self, config: dict[str, Any] | None = None, library_dir: str | Path | None = None):
        self.config = config or load_config()
        self.library_dir = resolve_stage6_path(library_dir or self.config["files"]["action_library_dir"])
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def list_actions(self) -> list[str]:
        return sorted(path.stem for path in self.library_dir.glob("*.json"))

    def action_path(self, name: str) -> Path:
        path = Path(name)
        if path.suffix == ".json" or path.is_absolute():
            return path if path.is_absolute() else self.library_dir / path
        return self.library_dir / f"{name}.json"

    def load_action(self, name: str) -> dict[str, Any]:
        path = self.action_path(name)
        if not path.exists():
            raise FileNotFoundError(f"动作不存在：{name}")
        payload = read_json(path)
        self.validate_action(payload)
        return payload

    def save_action(self, name: str, payload: dict[str, Any]) -> Path:
        self.validate_action(payload)
        path = self.action_path(name)
        write_json(path, payload)
        return path

    def delete_action(self, name: str) -> None:
        path = self.action_path(name)
        if not path.exists():
            raise FileNotFoundError(f"动作不存在：{name}")
        path.unlink()

    def rename_action(self, old_name: str, new_name: str) -> Path:
        old_path = self.action_path(old_name)
        new_path = self.action_path(new_name)
        if not old_path.exists():
            raise FileNotFoundError(f"动作不存在：{old_name}")
        old_path.rename(new_path)
        return new_path

    def copy_action(self, old_name: str, new_name: str) -> Path:
        old_path = self.action_path(old_name)
        new_path = self.action_path(new_name)
        if not old_path.exists():
            raise FileNotFoundError(f"动作不存在：{old_name}")
        shutil.copy2(old_path, new_path)
        return new_path

    def summarize_action(self, name_or_payload: str | dict[str, Any]) -> dict[str, Any]:
        payload = self.load_action(name_or_payload) if isinstance(name_or_payload, str) else name_or_payload
        poses = payload.get("poses", [])
        total = sum(float(pose.get("duration_sec", 0)) + float(pose.get("hold_sec", 0)) for pose in poses)
        tcp_points = [
            pose.get("tcp_pose", {}).get("xyz")
            for pose in poses
            if isinstance(pose.get("tcp_pose"), dict) and pose.get("tcp_pose", {}).get("xyz") is not None
        ]
        return {
            "动作名称": payload.get("name"),
            "pose_count": payload.get("pose_count", len(poses)),
            "创建时间": payload.get("created_at"),
            "总时长": round(total, 3),
            "是否包含 raw": any(pose.get("raw_present_position") for pose in poses),
            "是否包含 tcp_pose": any(pose.get("tcp_pose") for pose in poses),
            "是否包含 gripper": any((pose.get("gripper") or {}).get("available") for pose in poses),
            "是否包含 multi_turn_state": any(pose.get("multi_turn_state") for pose in poses),
            "末端轨迹点数": len(tcp_points),
            "末端轨迹起点": tcp_points[0] if tcp_points else None,
            "末端轨迹终点": tcp_points[-1] if tcp_points else None,
        }

    def validate_action(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            raise ValueError("动作文件最外层必须是对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"动作 schema_version 必须是 {SCHEMA_VERSION}。")
        if not isinstance(payload.get("poses"), list):
            raise ValueError("动作文件必须包含 poses 列表。")
        return True

    def export_action(self, name: str, output_path: str | Path) -> Path:
        source = self.action_path(name)
        if not source.exists():
            raise FileNotFoundError(f"动作不存在：{name}")
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def import_action(self, input_path: str | Path) -> Path:
        source = Path(input_path)
        payload = read_json(source)
        self.validate_action(payload)
        target = self.library_dir / source.name
        shutil.copy2(source, target)
        return target


动作文件管理 = ActionLibrary
