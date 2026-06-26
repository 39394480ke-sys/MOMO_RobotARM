"""GUI 侧视觉配置读取工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gui_app.path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import read_config, read_structured_section  # noqa: E402


def load_vision_config(vision_root: str | Path) -> dict[str, Any]:
    """读取视觉配置，失败时返回空对象。"""
    try:
        return read_config(Path(vision_root) / "视觉配置.yaml")
    except Exception:
        return {}


def load_vision_section(vision_root: str | Path, section: str) -> dict[str, Any]:
    """读取视觉配置中的对象 section；缺失或非对象时返回空对象。"""
    try:
        return read_structured_section(Path(vision_root) / "视觉配置.yaml", section)
    except Exception:
        return {}
