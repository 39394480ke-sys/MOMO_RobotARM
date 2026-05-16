"""阶段八 Web API 客户端。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class RobotAPIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8010", timeout_sec: float = 1.0, confirm_text: str = ""):
        self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self.confirm_text = str(confirm_text or "")
        try:
            import requests  # type: ignore

            self._requests = requests
        except Exception:
            self._requests = None

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
        if self._requests is not None:
            try:
                if method == "GET":
                    response = self._requests.get(url, timeout=self.timeout_sec)
                else:
                    response = self._requests.post(url, json=payload or {}, timeout=self.timeout_sec)
                data = response.json()
                if response.status_code >= 400:
                    return {"ok": False, "error": data.get("error") or {"message": response.text}, "data": data.get("data")}
                return data
            except Exception as exc:
                return {"ok": False, "data": None, "error": {"code": "HTTP_ERROR", "message": f"阶段八 API 请求失败：{exc}"}}

        try:
            body = None
            headers = {}
            if method != "GET":
                body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                text = response.read().decode("utf-8")
            return json.loads(text)
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8"))
            except Exception:
                data = {"error": {"code": "HTTP_ERROR", "message": str(exc)}}
            return {"ok": False, "data": data.get("data"), "error": data.get("error") or {"code": "HTTP_ERROR", "message": str(exc)}}
        except Exception as exc:
            return {"ok": False, "data": None, "error": {"code": "HTTP_ERROR", "message": f"阶段八 API 请求失败：{exc}"}}
