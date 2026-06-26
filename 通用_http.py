"""项目通用 HTTP 工具。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class HTTPJsonError(Exception):
    """HTTP JSON 请求失败，保留响应体方便调用方转换业务错误。"""

    method: str
    url: str
    status: int | None
    text: str
    payload: Any | None = None

    def __str__(self) -> str:
        status_text = f" HTTP {self.status}" if self.status is not None else ""
        return f"{self.method} {self.url}{status_text}: {self.text}"


@dataclass
class HTTPBytesResponse:
    """二进制 HTTP 响应。"""

    content: bytes
    headers: dict[str, str]
    status: int | None = None

    @property
    def content_type(self) -> str:
        for key, value in self.headers.items():
            if str(key).lower() == "content-type":
                return value
        return ""


def _parse_json_text(text: str, url: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{url} 返回值不是合法 JSON：{exc}") from exc


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    timeout: float = 8.0,
    headers: Mapping[str, str] | None = None,
    trust_env: bool = True,
) -> Any:
    """发起 JSON HTTP 请求并返回解析后的 JSON 值。"""
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update({str(key): str(value) for key, value in headers.items()})
    response = request_bytes(
        url,
        method=method,
        payload=payload,
        timeout=timeout,
        headers=request_headers,
        trust_env=trust_env,
    )
    text = response.content.decode("utf-8")
    return _parse_json_text(text, str(url))


def request_json_object(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    timeout: float = 8.0,
    headers: Mapping[str, str] | None = None,
    trust_env: bool = True,
) -> dict[str, Any]:
    """发起 JSON HTTP 请求，并要求返回值为对象。"""
    data = request_json(url, method=method, payload=payload, timeout=timeout, headers=headers, trust_env=trust_env)
    if not isinstance(data, dict):
        raise ValueError(f"{url} 返回值不是 JSON 对象。")
    return data


def fetch_bytes(
    url: str,
    *,
    timeout: float = 8.0,
    headers: Mapping[str, str] | None = None,
    trust_env: bool = True,
) -> bytes:
    return request_bytes(url, timeout=timeout, headers=headers, trust_env=trust_env).content


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    timeout: float = 8.0,
    headers: Mapping[str, str] | None = None,
    trust_env: bool = True,
) -> HTTPBytesResponse:
    """发起 HTTP 请求并返回二进制响应，适合音频/图片等非 JSON body。"""

    method_text = str(method or "GET").upper()
    request_headers = dict(headers or {})
    body = None
    if method_text != "GET":
        body = json.dumps(dict(payload or {}), ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(str(url), data=body, method=method_text, headers=request_headers)
    try:
        opener = None if trust_env else urllib.request.build_opener(urllib.request.ProxyHandler({}))
        open_func = urllib.request.urlopen if opener is None else opener.open
        with open_func(request, timeout=float(timeout)) as response:
            return HTTPBytesResponse(
                content=response.read(),
                headers={str(key): str(value) for key, value in response.headers.items()},
                status=getattr(response, "status", None),
            )
    except urllib.error.HTTPError as exc:
        content = exc.read()
        text = content.decode("utf-8", errors="replace")
        parsed: Any | None
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        raise HTTPJsonError(method_text, str(url), int(exc.code), text, parsed) from exc
    except Exception as exc:
        raise HTTPJsonError(method_text, str(url), None, str(exc), None) from exc
