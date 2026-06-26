"""URDF / 运动学测试路径初始化。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_KINEMATICS_ROOT = Path(__file__).resolve().parents[1]
if str(_KINEMATICS_ROOT) not in sys.path:
    sys.path.insert(0, str(_KINEMATICS_ROOT))

from 运动学路径工具_kinematics_path_utils import KINEMATICS_ROOT, PROJECT_ROOT, ensure_project_root_on_path  # noqa: E402
from 通用路径 import ensure_paths_on_sys_path  # noqa: E402

REAL_CONTROL_ROOT = PROJECT_ROOT / "真实舵机控制"


def ensure_kinematics_test_paths() -> Path:
    ensure_project_root_on_path()
    ensure_paths_on_sys_path((REAL_CONTROL_ROOT, KINEMATICS_ROOT))
    return KINEMATICS_ROOT


ensure_kinematics_test_paths()

from 通用_io import read_structured, write_json  # noqa: E402


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def create_temp_real_config(*, dry_run: bool, prefix: str) -> Path:
    config = read_structured(REAL_CONTROL_ROOT / "真实配置.yaml")
    config.setdefault("transport", {})["dry_run"] = bool(dry_run)
    temp_dir = Path(tempfile.mkdtemp(prefix=str(prefix)))
    temp_path = temp_dir / ("真实配置_临时dryrun.json" if dry_run else "真实配置_临时真实模式.json")
    write_json(temp_path, config)
    return temp_path
