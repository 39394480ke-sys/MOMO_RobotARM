"""dry-run 关节微调测试。不会真实写舵机。"""

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
    request_json("/api/v1/session/connect", "POST", {"mode": "dry_run"})
    payload = request_json(
        "/api/v1/motion/joint-step",
        "POST",
        {"joint_key": "shoulder_pan", "delta_deg": 1.0, "speed_percent": 50},
    )
    assert payload["ok"] is True, payload
    print("dry-run joint-step ok，不会真实写舵机")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
