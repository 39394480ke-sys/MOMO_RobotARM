"""项目通用路径工具。

各子系统保留自己的 ``*_ROOT`` 常量和对外函数名，这里只集中放低层路径动作。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


def ensure_path_on_sys_path(path: str | Path) -> Path:
    """把路径放到 ``sys.path`` 最前面，并返回 resolve 后路径。"""
    resolved = Path(path).resolve()
    path_text = str(resolved)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
    return resolved


def ensure_paths_on_sys_path(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    """按传入顺序把多个路径放到 ``sys.path`` 前部。"""
    resolved_paths = tuple(Path(path).resolve() for path in paths)
    for path in reversed(resolved_paths):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
    return resolved_paths


def resolve_under_base(value: str | Path, base_dir: str | Path = ".", *, expand_user: bool = False) -> Path:
    """解析绝对路径或相对 ``base_dir`` 的路径。"""
    path = Path(value)
    if expand_user:
        path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path(base_dir).resolve() / path).resolve()


def ensure_parent_dirs(*paths: str | Path) -> None:
    """确保一组文件路径的父目录存在。"""
    for value in paths:
        Path(value).parent.mkdir(parents=True, exist_ok=True)
