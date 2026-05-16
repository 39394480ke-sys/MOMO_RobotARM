"""启动视觉服务后，请求 /health、/latest、/status。"""

from __future__ import annotations

import json
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    for path in ["/health", "/latest", "/status"]:
        try:
            data = get_json(path)
            print(path)
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        except Exception as exc:
            print(f"{path} 请求失败：{exc}")


if __name__ == "__main__":
    main()
