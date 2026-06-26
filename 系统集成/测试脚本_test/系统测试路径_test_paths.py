"""系统集成测试路径初始化。"""

from __future__ import annotations

import sys
from pathlib import Path

_INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
if str(_INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_ROOT))

from integration.path_utils import INTEGRATION_DIR, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402

INTEGRATION_ROOT = INTEGRATION_DIR


def ensure_integration_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((INTEGRATION_ROOT,))
    return INTEGRATION_ROOT


ensure_integration_test_paths()
