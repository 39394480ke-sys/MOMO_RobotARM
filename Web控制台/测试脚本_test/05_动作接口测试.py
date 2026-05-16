"""动作列表 / dry-run 播放 / 停止测试。"""

from __future__ import annotations

import json
import os
import time
import urllib.request


BASE_URL = os.environ.get("WEB_API_URL", "http://127.0.0.1:8010")


def request_json(path: str, method: str = "GET", body: dict | None = None, timeout: int = 10) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    request_json("/api/v1/session/connect", "POST", {"mode": "dry_run"})
    actions = request_json("/api/v1/actions")
    assert actions["ok"] is True, actions
    items = actions["data"].get("actions", [])
    print(f"动作数量：{len(items)}")
    if not items:
        print("动作库为空，跳过播放。")
        return

    name = items[0]["name"]
    started = request_json("/api/v1/actions/play", "POST", {"name": name, "speed": 2.0, "loop": False}, timeout=12)
    assert started["ok"] is True, started
    print(f"dry-run action play started: {name}")
    time.sleep(0.5)
    stopped = request_json("/api/v1/actions/stop", "POST", {})
    assert stopped["ok"] is True, stopped
    print("action stop ok")


if __name__ == "__main__":
    main()
