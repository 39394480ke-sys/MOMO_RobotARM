"""真实控制与标定工具共用的配置加载入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from 机器人配置_profile_loader import apply_hardware_profile, load_robot_profile
from 通用_io import deep_merge, env_bool, env_value, read_structured, write_structured


PROJECT_ROOT = Path(__file__).resolve().parent
REAL_CONTROL_DIR = PROJECT_ROOT / "真实舵机控制"
DEFAULT_CALIBRATION_PATH = "标定/current.local.json"


def local_config_path(config_path: str | Path) -> Path:
    """返回基线配置对应的同目录 local 覆盖路径。"""

    source = Path(config_path)
    if source.stem.endswith(".local"):
        return source
    return source.with_name(f"{source.stem}.local{source.suffix}")


def load_real_config(config_path: str | Path) -> dict[str, Any]:
    """按基线、可选 local、profile、环境 transport 的顺序加载真实配置。"""

    source = Path(config_path).resolve()
    base_config = read_structured(source)
    config = base_config
    override_path = local_config_path(source)
    runtime_mode_locked = bool(config.get("transport", {}).get("runtime_mode_locked", False))
    if not runtime_mode_locked and override_path != source and override_path.is_file():
        config = deep_merge(config, read_structured(override_path))

    variant = config.get("robot", {}).get("variant")
    config = apply_hardware_profile(
        config,
        load_robot_profile(variant),
        base_config=base_config,
    )

    env_paths = (
        PROJECT_ROOT / ".env",
        REAL_CONTROL_DIR / "环境变量.env",
        PROJECT_ROOT / "系统集成" / "环境变量.env",
    )
    transport = config.setdefault("transport", {})
    port = str(env_value("ARM_ROBOT_PORT", "", env_paths=env_paths) or "").strip()
    if port:
        transport["port"] = port
    backend = str(env_value("ARM_SERVO_BACKEND", "", env_paths=env_paths) or "").strip()
    if backend:
        transport["driver_backend"] = backend
    if not bool(transport.get("runtime_mode_locked", False)):
        transport["dry_run"] = env_bool(
            "ARM_REAL_DRY_RUN",
            bool(transport.get("dry_run", True)),
            env_paths=env_paths,
        )
    return config


def persist_real_config_override(config_path: str | Path, override: Mapping[str, Any]) -> Path:
    """只把指定运行覆盖合并写入 local 文件，不回写 tracked 基线。"""

    target = local_config_path(Path(config_path).resolve())
    current = read_structured(target) if target.is_file() else {}
    write_structured(target, deep_merge(current, override))
    return target
