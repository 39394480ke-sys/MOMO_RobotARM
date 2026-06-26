"""Web 控制台测试 HTTP 客户端。"""

from __future__ import annotations

import os
from typing import Any

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()

from 通用_http import HTTPJsonError, request_json_object  # noqa: E402


def web_api_url() -> str:
    return os.environ.get("WEB_API_URL", "http://127.0.0.1:8010").rstrip("/")


def web_ws_url() -> str:
    return os.environ.get("WEB_WS_URL", "ws://127.0.0.1:8010/api/v1/ws/state")


def request_json(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 8) -> dict[str, Any]:
    try:
        return request_json_object(
            web_api_url() + path,
            method=method,
            payload=body,
            timeout=timeout,
        )
    except HTTPJsonError as exc:
        raise AssertionError(
            f"{method} {path} HTTP {exc.status}: {exc.text}"
            if exc.status is not None
            else f"{method} {path}: {exc.text}"
        ) from exc


def get_json(path: str, timeout: int = 5) -> dict[str, Any]:
    return request_json(path, timeout=timeout)


def post_json(path: str, body: dict[str, Any] | None = None, timeout: int = 8) -> dict[str, Any]:
    return request_json(path, "POST", body or {}, timeout=timeout)


def connect_dry_run(timeout: int = 8) -> dict[str, Any]:
    payload = post_json("/api/v1/session/connect", {"mode": "dry_run"}, timeout=timeout)
    assert payload["ok"] is True, payload
    return payload
