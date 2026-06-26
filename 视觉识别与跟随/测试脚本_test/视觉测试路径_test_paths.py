"""视觉识别与跟随测试路径初始化。"""

from __future__ import annotations

import sys
from pathlib import Path

_VISION_ROOT = Path(__file__).resolve().parents[1]
if str(_VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(_VISION_ROOT))

from vision.路径工具_path_utils import PROJECT_ROOT, VISION_ROOT, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402


def ensure_vision_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((VISION_ROOT,))
    return VISION_ROOT


ensure_vision_test_paths()
