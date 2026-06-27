"""项目通用 IO 工具。

集中处理 JSON/YAML 配置读写，避免 GUI、Web、系统集成等模块各自复制一份。
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4


def read_structured(path: str | Path) -> dict[str, Any]:
    """读取 JSON/YAML 对象配置。"""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置最外层必须是对象：{source}")
    return data


def attach_config_metadata(path: str | Path, data: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    """给配置对象附加统一的路径元数据。"""
    source = Path(path).resolve()
    result = dict(data)
    result["_config_path"] = str(source)
    result["_base_dir"] = str(source.parent)
    for key, value in extra.items():
        result[str(key)] = str(value) if isinstance(value, Path) else value
    return result


def read_config(path: str | Path, **extra: Any) -> dict[str, Any]:
    """读取 JSON/YAML 配置并附加统一路径元数据。"""
    source = Path(path).resolve()
    return attach_config_metadata(source, read_structured(source), **extra)


def read_structured_section(path: str | Path, section: str) -> dict[str, Any]:
    """读取 JSON/YAML 配置中的对象 section。"""
    data = read_structured(path)
    value = data.get(section, {})
    return dict(value) if isinstance(value, Mapping) else {}


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并配置对象，返回新对象，不修改输入。"""
    result = deepcopy(dict(base))
    for key, value in dict(override).items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def write_json(path: str | Path, data: Any) -> None:
    """以项目统一格式写入 JSON。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def atomic_write_json(path: str | Path, data: Any) -> None:
    """原子写入 JSON，适合 runtime/state 这类会被其他进程读取的文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.stem}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        write_json(tmp_path, data)
        tmp_path.replace(target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_structured(path: str | Path, data: Mapping[str, Any]) -> None:
    """写入 JSON/YAML 对象配置，格式由文件后缀决定。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in {".yaml", ".yml"}:
        import yaml  # type: ignore

        target.write_text(yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False), encoding="utf-8")
        return
    write_json(target, dict(data))


def update_structured_section(path: str | Path, section: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """更新配置文件中的一个对象 section，并返回完整配置。"""
    target = Path(path)
    data = read_structured(target)
    data[str(section)] = dict(value)
    write_structured(target, data)
    return data


def timestamped_json_path(directory: str | Path, prefix: str, timestamp: str | None = None) -> Path:
    """生成 ``prefix_YYYY-mm-ddTHH-MM-SS.json`` 形式的路径。"""
    base = Path(directory)
    text = str(timestamp or time.strftime("%Y-%m-%dT%H-%M-%S"))
    safe_timestamp = text.replace(":", "-")
    return base / f"{prefix}_{safe_timestamp}.json"


def latest_matching_file(directory: str | Path, pattern: str) -> Path | None:
    """返回目录中匹配 pattern 的最新文件，目录缺失或无匹配时返回 None。"""
    base = Path(directory)
    if not base.exists():
        return None
    matches = [path for path in base.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def list_json_stems(directory: str | Path) -> list[str]:
    """列出目录下所有 JSON 文件名 stem，目录缺失时返回空列表。"""
    base = Path(directory)
    if not base.exists():
        return []
    return sorted(path.stem for path in base.glob("*.json") if path.is_file())


def resolve_named_json_path(base_dir: str | Path, name_or_path: str | Path) -> Path:
    """解析命名 JSON：裸名补 `.json`，相对文件名放在 base_dir 下，绝对路径原样返回。"""
    path = Path(name_or_path)
    if path.is_absolute():
        return path
    if path.suffix == ".json":
        return Path(base_dir) / path
    return Path(base_dir) / f"{path}.json"


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_object(path: str | Path) -> dict[str, Any]:
    """读取 JSON 对象；非对象时抛出带路径的错误。"""
    source = Path(path)
    payload = read_json(source)
    if not isinstance(payload, dict):
        raise ValueError(f"{source} 不是 JSON 对象。")
    return payload


def read_json_object_or_default(path: str | Path, default: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """读取 JSON 对象；文件缺失、解析失败或非对象时返回默认对象副本。"""
    source = Path(path)
    if not source.exists():
        return dict(default or {})
    try:
        return read_json_object(source)
    except Exception:
        return dict(default or {})


def read_text(path: str | Path, errors: str = "strict") -> str:
    """读取 UTF-8 文本。"""
    return Path(path).read_text(encoding="utf-8", errors=errors)


def write_text(path: str | Path, text: str) -> None:
    """写入 UTF-8 文本，并确保父目录存在。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(text), encoding="utf-8")


def read_env_values(paths: Iterable[str | Path]) -> dict[str, str]:
    """读取一组简单 ``KEY=value`` env 文件，先出现的值优先。"""

    values: dict[str, str] = {}
    for value in paths:
        path = Path(value)
        if not path.exists():
            continue
        for line in read_text(path, errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            raw_value = raw_value.strip().strip('"').strip("'")
            if key and key not in values:
                values[key] = raw_value
    return values


def env_value(name: str, default: Any = None, *, env_paths: Iterable[str | Path] = ()) -> Any:
    """读取环境变量，系统环境优先，其次读取 env 文件。"""

    key = str(name)
    direct = os.environ.get(key)
    if direct not in (None, ""):
        return direct
    values = read_env_values(env_paths)
    value = values.get(key)
    return default if value in (None, "") else value


def env_int(name: str, default: int, *, env_paths: Iterable[str | Path] = ()) -> int:
    value = env_value(name, default, env_paths=env_paths)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def env_bool(name: str, default: bool, *, env_paths: Iterable[str | Path] = ()) -> bool:
    value = env_value(name, None, env_paths=env_paths)
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y", "是", "真"}:
        return True
    if text in {"0", "false", "no", "off", "n", "否", "假"}:
        return False
    return bool(default)


def resolve_secret_value(
    value: Any,
    *,
    default_env_names: Iterable[str] = (),
    env_paths: Iterable[str | Path] = (),
) -> str:
    """解析明文、``$VAR``、``${VAR}`` 或默认环境变量中的 secret。"""

    text = str(value or "").strip()
    env_values: dict[str, str] | None = None

    def env_secret(name: str) -> str:
        direct = os.environ.get(name, "").strip()
        if direct:
            return direct
        nonlocal env_values
        if env_values is None:
            env_values = read_env_values(env_paths)
        return str(env_values.get(name, "")).strip()

    if not text:
        for name in default_env_names:
            resolved = env_secret(str(name))
            if resolved:
                return resolved
        return ""
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
    if match:
        return env_secret(match.group(1))
    if text.startswith("$") and re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", text):
        return env_secret(text[1:])
    return text


def tail_lines(path: str | Path, lines: int = 100, *, errors: str = "replace") -> list[str]:
    """读取文本文件最后 N 行，返回已去掉换行符的行。"""
    source = Path(path)
    if lines <= 0 or not source.exists():
        return []
    with source.open("r", encoding="utf-8", errors=errors) as file:
        return [line.rstrip("\n") for line in deque(file, maxlen=int(lines))]


def append_json_line(path: str | Path, data: Mapping[str, Any]) -> None:
    """追加一行 JSONL 日志。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as file:
        file.write(json.dumps(dict(data), ensure_ascii=False) + "\n")


def log_event_json_line(
    path: str | Path,
    event: str,
    *,
    time_style: str = "local_string",
    **fields: Any,
) -> None:
    """追加 ``time + event + fields`` 形状的 JSONL 事件日志。"""
    if time_style == "epoch":
        time_value: Any = time.time()
    elif time_style == "iso":
        time_value = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    else:
        time_value = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = {"time": time_value, "event": str(event)}
    payload.update(fields)
    append_json_line(path, payload)


def log_json_line(
    path: str | Path,
    level: str,
    event: str,
    message: str,
    *,
    time_style: str = "local_string",
    include_ts: bool = False,
    **fields: Any,
) -> None:
    """追加标准 JSONL 日志，保留调用方选择的时间格式。"""
    if time_style == "epoch":
        time_value: Any = time.time()
    elif time_style == "iso":
        time_value = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    else:
        time_value = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "time": time_value,
        "level": str(level),
        "event": str(event),
        "message": str(message),
    }
    if include_ts:
        payload["ts"] = time.time()
    payload.update(fields)
    append_json_line(path, payload)


def parse_json_line(line: str) -> dict[str, Any] | None:
    """解析一行 JSONL。非对象或解析失败时返回 None。"""
    try:
        data = json.loads(line)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def resolve_path(path_value: str | Path, base_dir: str | Path) -> Path:
    from 通用路径 import resolve_under_base

    return resolve_under_base(path_value, base_dir)
