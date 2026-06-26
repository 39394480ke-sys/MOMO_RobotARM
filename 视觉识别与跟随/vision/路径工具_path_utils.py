"""视觉模块路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

VISION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = VISION_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 通用路径 import ensure_parent_dirs, ensure_path_on_sys_path, resolve_under_base  # noqa: E402


def resolve_vision_path(value: str | Path, base_dir: str | Path | None = None) -> Path:
    return resolve_under_base(value, base_dir or VISION_ROOT)


def ensure_project_root_on_path() -> Path:
    return ensure_path_on_sys_path(PROJECT_ROOT)
