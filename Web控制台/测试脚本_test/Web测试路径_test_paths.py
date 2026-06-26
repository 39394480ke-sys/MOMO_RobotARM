"""Web 控制台测试路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

_WEB_ROOT = Path(__file__).resolve().parents[1]
if str(_WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(_WEB_ROOT))

from backend.path_utils import PROJECT_ROOT, WEB_DIR, ensure_project_root_on_path  # noqa: E402

WEB_ROOT = WEB_DIR


def ensure_web_test_paths() -> Path:
    ensure_project_root_on_path()
    return WEB_ROOT


ensure_web_test_paths()
