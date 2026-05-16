"""统一配置加载。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


INTEGRATION_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = INTEGRATION_DIR.parent
DEFAULT_CONFIG_PATH = INTEGRATION_DIR / "总配置.yaml"


class ConfigLoader:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
        self.base_dir = self.config_path.parent

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在：{self.config_path}")
        text = self.config_path.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text) or {}
        except Exception:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("总配置.yaml 最外层必须是对象。")
        data["_config_path"] = str(self.config_path)
        data["_base_dir"] = str(self.base_dir)
        data["_project_root"] = str(PROJECT_ROOT)
        ensure_runtime_dirs(data)
        return data


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    return ConfigLoader(config_path).load()


def resolve_path(path_value: str | Path, base_dir: str | Path | None = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (Path(base_dir or INTEGRATION_DIR).resolve() / path).resolve()


def ensure_runtime_dirs(config: dict[str, Any] | None = None) -> None:
    base_dir = Path((config or {}).get("_base_dir", INTEGRATION_DIR)).resolve()
    for rel in ["runtime", "runtime/pids", "runtime/logs", "runtime/state"]:
        (base_dir / rel).mkdir(parents=True, exist_ok=True)
