"""GUI 测试路径初始化。"""

from __future__ import annotations

import sys
from pathlib import Path

_GUI_ROOT = Path(__file__).resolve().parents[1]
if str(_GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(_GUI_ROOT))

from gui_app.path_utils import GUI_ROOT, ensure_project_root_on_path  # noqa: E402


def ensure_gui_test_paths() -> Path:
    ensure_project_root_on_path()
    return GUI_ROOT


ensure_gui_test_paths()
