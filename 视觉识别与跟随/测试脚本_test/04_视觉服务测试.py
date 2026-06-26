"""启动视觉服务后，请求 /health、/latest、/status。"""

from __future__ import annotations

import json
import os

import 视觉测试路径_test_paths  # noqa: F401
from 通用_http import request_json_object

BASE_URL = os.environ.get("VISION_API_URL", "http://127.0.0.1:8000").rstrip("/")


def get_json(path: str) -> dict:
    return request_json_object(BASE_URL + path, timeout=2.0)


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
