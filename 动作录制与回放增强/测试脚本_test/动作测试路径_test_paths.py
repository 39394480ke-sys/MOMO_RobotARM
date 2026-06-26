"""动作录制与回放测试路径初始化。"""

from __future__ import annotations

import sys
from pathlib import Path

ACTION_TEST_ROOT = Path(__file__).resolve().parent
_ACTION_ROOT = ACTION_TEST_ROOT.parent
if str(_ACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(_ACTION_ROOT))

from 动作路径工具_motion_path_utils import ACTION_ROOT, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402


def ensure_action_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((ACTION_TEST_ROOT, ACTION_ROOT))
    return ACTION_ROOT


ensure_action_test_paths()
