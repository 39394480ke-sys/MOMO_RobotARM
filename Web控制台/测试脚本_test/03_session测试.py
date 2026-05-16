"""session status / dry-run connect / disconnect 测试。"""

from __future__ import annotations

import json
import os
import urllib.request


BASE_URL = os.environ.get("WEB_API_URL", "http://127.0.0.1:8010")


def request_json(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    status = request_json("/api/v1/session/status")
    assert status["ok"] is True, status
    print("初始 session:", json.dumps(status["data"], ensure_ascii=False, indent=2))

    connected = request_json("/api/v1/session/connect", "POST", {"mode": "dry_run"})
    assert connected["ok"] is True, connected
    assert connected["data"]["session"]["connected"] is True, connected
    print("dry-run connect ok")

    disconnected = request_json("/api/v1/session/disconnect", "POST", {})
    assert disconnected["ok"] is True, disconnected
    print("disconnect ok")


if __name__ == "__main__":
    main()
