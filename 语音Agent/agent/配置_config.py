"""配置加载工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .path_utils import AGENT_ROOT, ensure_project_root_on_path

BASE_DIR = AGENT_ROOT
DEFAULT_CONFIG_PATH = BASE_DIR / "Agent配置.yaml"

ensure_project_root_on_path()

from 通用_io import env_bool, env_value, read_config, resolve_path as resolve_common_path  # noqa: E402


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = resolve_path(path or DEFAULT_CONFIG_PATH)
    config = read_config(config_path)
    env_paths = secret_env_paths(config)
    agent = config.setdefault("agent", {})
    openai_compatible = config.setdefault("openai_compatible", {})
    robot_api = config.setdefault("robot_api", {})
    stt = config.setdefault("stt", {})
    tts = config.setdefault("tts", {})

    agent["backend"] = env_value("ARM_AGENT_BACKEND", agent.get("backend", "openai_compatible"), env_paths=env_paths)
    openai_compatible["api_base"] = env_value("ARM_AGENT_API_BASE", openai_compatible.get("api_base", ""), env_paths=env_paths)
    openai_compatible["api_key"] = env_value("ARM_AGENT_API_KEY", openai_compatible.get("api_key", ""), env_paths=env_paths)
    openai_compatible["model"] = env_value("ARM_AGENT_MODEL", openai_compatible.get("model", ""), env_paths=env_paths)
    robot_api["base_url"] = env_value("ARM_ROBOT_API_BASE", robot_api.get("base_url", "http://127.0.0.1:8010"), env_paths=env_paths)
    stt["url"] = env_value("ARM_STT_URL", stt.get("url", ""), env_paths=env_paths)
    stt["api_key"] = env_value("ARM_STT_API_KEY", stt.get("api_key", ""), env_paths=env_paths)
    tts["enabled"] = env_bool("ARM_TTS_ENABLED", bool(tts.get("enabled", True)), env_paths=env_paths)
    tts["url"] = env_value("ARM_TTS_URL", tts.get("url", ""), env_paths=env_paths)
    tts["api_key"] = env_value("ARM_TTS_API_KEY", tts.get("api_key", ""), env_paths=env_paths)
    return config


def resolve_path(path: str | Path, base_dir: str | Path | None = None) -> Path:
    return resolve_common_path(path, base_dir or BASE_DIR)


def config_base_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("_base_dir") or BASE_DIR).resolve()


def secret_env_paths(config: dict[str, Any]) -> tuple[Path, Path]:
    base_dir = config_base_dir(config)
    project_root = BASE_DIR.parent
    return (base_dir / "环境变量.env", project_root / ".env")
