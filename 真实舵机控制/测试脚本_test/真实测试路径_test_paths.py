"""真实舵机控制测试路径初始化。"""

from __future__ import annotations

import sys
from pathlib import Path

_REAL_ROOT = Path(__file__).resolve().parents[1]
if str(_REAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_REAL_ROOT))

from 真实路径工具_real_path_utils import REAL_CONTROL_DIR, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402

REAL_ROOT = REAL_CONTROL_DIR


def ensure_real_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((REAL_ROOT,))
    return REAL_ROOT


ensure_real_test_paths()
