"""GET /api/v1/health 测试。"""

from __future__ import annotations

import json
import os
import urllib.request


BASE_URL = os.environ.get("WEB_API_URL", "http://127.0.0.1:8010")


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    payload = get_json("/api/v1/health")
    assert payload["ok"] is True, payload
    print("health ok")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
