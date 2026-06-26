"""语音 Agent 测试路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from agent.path_utils import AGENT_ROOT, PROJECT_ROOT, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402


def ensure_agent_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((AGENT_ROOT,))
    return AGENT_ROOT


def agent_config_path() -> Path:
    return AGENT_ROOT / "Agent配置.yaml"


ensure_agent_test_paths()
