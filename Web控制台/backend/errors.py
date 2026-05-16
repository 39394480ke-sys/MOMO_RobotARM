"""Web API 统一错误和响应格式。

阶段八要求所有 REST 接口都返回：
成功：{"ok": true, "data": ..., "error": null}
失败：{"ok": false, "data": null, "error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

from typing import Any


class WebAPIError(Exception):
    """业务层可预期错误，统一转成 JSON。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)


def api_success(data: Any | None = None) -> dict[str, Any]:
    """生成统一成功响应。"""

    return {"ok": True, "data": data if data is not None else {}, "error": None}


def api_error(code: str, message: str) -> dict[str, Any]:
    """生成统一失败响应。"""

    return {
        "ok": False,
        "data": None,
        "error": {"code": str(code), "message": str(message)},
    }
