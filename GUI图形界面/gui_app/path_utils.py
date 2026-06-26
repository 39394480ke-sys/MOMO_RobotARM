"""GUI 路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

GUI_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = GUI_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 通用路径 import ensure_path_on_sys_path  # noqa: E402


def ensure_project_root_on_path() -> Path:
    return ensure_path_on_sys_path(PROJECT_ROOT)
