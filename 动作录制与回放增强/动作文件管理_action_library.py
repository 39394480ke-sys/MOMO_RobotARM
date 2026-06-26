"""阶段六动作文件管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from 动作工具_common import SCHEMA_VERSION, load_config, refresh_sequence_pose_count, resolve_stage6_path, summarize_sequence_payload
from 通用_io import atomic_write_json, list_json_stems, read_json_object, resolve_named_json_path


class ActionLibrary:
    def __init__(self, config: dict[str, Any] | None = None, library_dir: str | Path | None = None):
        self.config = config or load_config()
        self.library_dir = resolve_stage6_path(library_dir or self.config["files"]["action_library_dir"])
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def list_actions(self) -> list[str]:
        return list_json_stems(self.library_dir)

    def action_path(self, name: str) -> Path:
        return resolve_named_json_path(self.library_dir, name)

    def load_action(self, name: str) -> dict[str, Any]:
        path = self.action_path(name)
        if not path.exists():
            raise FileNotFoundError(f"动作不存在：{name}")
        payload = read_json_object(path)
        return self._prepare_action_payload(payload)

    def save_action(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.action_path(name)
        return self._write_action_payload(path, payload)

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
        new_path = self.action_path(new_name)
        payload = self.load_action(old_name)
        return self._write_action_payload(new_path, payload)

    def summarize_action(self, name_or_payload: str | dict[str, Any]) -> dict[str, Any]:
        payload = self.load_action(name_or_payload) if isinstance(name_or_payload, str) else name_or_payload
        return summarize_sequence_payload(payload)

    def validate_action(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            raise ValueError("动作文件最外层必须是对象。")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"动作 schema_version 必须是 {SCHEMA_VERSION}。")
        if not isinstance(payload.get("poses"), list):
            raise ValueError("动作文件必须包含 poses 列表。")
        return True

    def export_action(self, name: str, output_path: str | Path) -> Path:
        payload = self.load_action(name)
        return self._write_action_payload(Path(output_path), payload)

    def import_action(self, input_path: str | Path) -> Path:
        source = Path(input_path)
        payload = read_json_object(source)
        target = self.library_dir / source.name
        return self._write_action_payload(target, payload)

    def _prepare_action_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        refresh_sequence_pose_count(payload)
        self.validate_action(payload)
        return payload

    def _write_action_payload(self, path: Path, payload: dict[str, Any]) -> Path:
        prepared = self._prepare_action_payload(payload)
        atomic_write_json(path, prepared)
        return path


动作文件管理 = ActionLibrary
