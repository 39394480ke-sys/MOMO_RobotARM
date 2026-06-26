"""阶段八 Web API 客户端。"""

from __future__ import annotations

from typing import Any

from .路径工具_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import api_error, api_error_from_payload  # noqa: E402
from 通用_http import HTTPJsonError, request_json_object  # noqa: E402


def request_json_url(method: str, url: str, payload: dict[str, Any] | None = None, timeout_sec: float = 1.0) -> dict[str, Any]:
    method = str(method or "GET").upper()
    try:
        return request_json_object(str(url), method=method, payload=payload, timeout=float(timeout_sec))
    except HTTPJsonError as exc:
        data = exc.payload
        if isinstance(data, dict):
            return api_error_from_payload(data, exc.text, "HTTP_ERROR")
        return api_error("HTTP_ERROR", exc.text)
    except Exception as exc:
        return api_error("HTTP_ERROR", f"HTTP JSON 请求失败：{exc}")


def fetch_json_url(url: str, timeout_sec: float = 1.0) -> dict[str, Any]:
    return request_json_url("GET", url, timeout_sec=timeout_sec)


class RobotAPIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8010", timeout_sec: float = 1.0, confirm_text: str = ""):
        self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self.confirm_text = str(confirm_text or "")

    def get_session_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/session/status")

    def get_robot_state(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/robot/state")

    def joint_step(self, joint_key: str, delta_deg: float, speed_percent: int = 50) -> dict[str, Any]:
        payload = {
            "joint_key": str(joint_key),
            "delta_deg": float(delta_deg),
            "speed_percent": int(speed_percent),
            "confirm_text": self.confirm_text,
        }
        return self._request("POST", "/api/v1/motion/joint-step", payload)

    def stop(self) -> dict[str, Any]:
        return self._request("POST", "/api/v1/motion/stop", {})

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        result = request_json_url(method, url, payload, self.timeout_sec)
        if not result.get("ok", True):
            return api_error_from_payload(result, "阶段八 API 请求失败。", "HTTP_ERROR")
        return result
