"""生活周报测试路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

_LIFE_REPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_LIFE_REPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_LIFE_REPORT_ROOT))

from 生活周报路径工具_life_report_path_utils import LIFE_REPORT_ROOT, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402


def ensure_life_report_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((LIFE_REPORT_ROOT,))
    return LIFE_REPORT_ROOT


def generator_script_path() -> Path:
    return LIFE_REPORT_ROOT / "生成生活周报.py"


ensure_life_report_test_paths()
