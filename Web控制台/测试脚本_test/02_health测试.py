"""GET /api/v1/health 测试。"""

from __future__ import annotations

import json

from Web测试客户端_test_client import get_json


def main() -> None:
    payload = get_json("/api/v1/health")
    assert payload["ok"] is True, payload
    print("health ok")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
