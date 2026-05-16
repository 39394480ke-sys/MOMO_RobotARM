"""配置加载工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = BASE_DIR / "Agent配置.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = resolve_path(path or DEFAULT_CONFIG_PATH)
    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Agent配置.yaml 最外层必须是对象。")
    data["_base_dir"] = str(config_path.parent.resolve())
    data["_config_path"] = str(config_path.resolve())
    return data


def resolve_path(path: str | Path, base_dir: str | Path | None = None) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return Path(base_dir or BASE_DIR).resolve() / value


def config_base_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("_base_dir") or BASE_DIR).resolve()

