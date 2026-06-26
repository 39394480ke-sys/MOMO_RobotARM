"""GUI result 字典展示辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def result_data(result: Mapping[str, Any] | None) -> dict[str, Any]:
    data = result.get("data", {}) if isinstance(result, Mapping) else {}
    return dict(data) if isinstance(data, Mapping) else {}


def result_message(result: Any, default: str | None = None) -> str:
    if isinstance(result, Mapping):
        message = result.get("message")
        if message not in (None, ""):
            return str(message)
        error = result.get("error")
        if isinstance(error, Mapping):
            error_message = error.get("message") or error.get("code")
            if error_message not in (None, ""):
                return str(error_message)
        if error not in (None, ""):
            return str(error)
    if default is not None:
        return str(default)
    return str(result)
