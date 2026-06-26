"""统一配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .path_utils import INTEGRATION_DIR, PROJECT_ROOT, ensure_project_root_on_path

DEFAULT_CONFIG_PATH = INTEGRATION_DIR / "总配置.yaml"


class ConfigLoader:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
        self.base_dir = self.config_path.parent

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在：{self.config_path}")
        ensure_project_root_on_path()
        from 通用_io import env_int, env_value, read_config

        data = read_config(self.config_path, _project_root=PROJECT_ROOT)
        env_paths = (PROJECT_ROOT / ".env", INTEGRATION_DIR / "环境变量.env")

        web_host = str(env_value("ARM_WEB_HOST", "", env_paths=env_paths) or "").strip()
        web_port = env_int("ARM_WEB_PORT", 8010, env_paths=env_paths)
        if web_host:
            web = data.setdefault("services", {}).setdefault("web_api", {})
            web["command"] = f"python 启动Web服务.py --host {web_host} --port {web_port}"
            shown_host = "127.0.0.1" if web_host == "0.0.0.0" else web_host
            web["health_url"] = f"http://{shown_host}:{web_port}/api/v1/health"

        vision_host = str(env_value("ARM_VISION_HOST", "", env_paths=env_paths) or "").strip()
        vision_port = env_int("ARM_VISION_PORT", 8000, env_paths=env_paths)
        if vision_host:
            vision = data.setdefault("services", {}).setdefault("vision", {})
            vision["command"] = f"python 视觉主程序_main.py service --host {vision_host} --port {vision_port}"
            shown_host = "127.0.0.1" if vision_host == "0.0.0.0" else vision_host
            vision["health_url"] = f"http://{shown_host}:{vision_port}/health"

        mode = str(env_value("ARM_DEFAULT_MODE", "", env_paths=env_paths) or "").strip()
        if mode:
            data.setdefault("project", {})["default_mode"] = mode
        ensure_runtime_dirs(data)
        return data


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    return ConfigLoader(config_path).load()


def resolve_path(path_value: str | Path, base_dir: str | Path | None = None) -> Path:
    ensure_project_root_on_path()
    from 通用_io import resolve_path as resolve_common_path

    return resolve_common_path(path_value, base_dir or INTEGRATION_DIR)


def ensure_runtime_dirs(config: dict[str, Any] | None = None) -> None:
    base_dir = Path((config or {}).get("_base_dir", INTEGRATION_DIR)).resolve()
    for rel in ["runtime", "runtime/pids", "runtime/logs", "runtime/state"]:
        (base_dir / rel).mkdir(parents=True, exist_ok=True)
