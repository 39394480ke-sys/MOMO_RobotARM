"""真实舵机控制路径工具。"""

from __future__ import annotations

import sys
from pathlib import Path

REAL_CONTROL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REAL_CONTROL_DIR.parent
SIM_ROOT = PROJECT_ROOT / "仿真控制系统"
KINEMATICS_ROOT = PROJECT_ROOT / "URDF运动学仿真"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 通用路径 import ensure_path_on_sys_path, ensure_paths_on_sys_path, resolve_under_base  # noqa: E402


def resolve_real_path(value: str | Path, base_dir: str | Path | None = None) -> Path:
    return resolve_under_base(value, base_dir or REAL_CONTROL_DIR)


def ensure_project_root_on_path() -> Path:
    return ensure_path_on_sys_path(PROJECT_ROOT)


def ensure_paths_on_path(paths: tuple[Path, ...] | list[Path]) -> None:
    ensure_paths_on_sys_path(paths)


def ensure_real_stage_paths() -> tuple[Path, Path]:
    ensure_paths_on_path([SIM_ROOT, KINEMATICS_ROOT])
    return SIM_ROOT, KINEMATICS_ROOT


def real_config_path() -> Path:
    return REAL_CONTROL_DIR / "真实配置.yaml"
