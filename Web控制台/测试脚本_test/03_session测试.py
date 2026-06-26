"""session status / dry-run connect / disconnect 测试。"""

from __future__ import annotations

import json

from Web测试客户端_test_client import connect_dry_run, get_json, post_json


def main() -> None:
    status = get_json("/api/v1/session/status")
    assert status["ok"] is True, status
    print("初始 session:", json.dumps(status["data"], ensure_ascii=False, indent=2))

    connected = connect_dry_run()
    assert connected["data"]["session"]["connected"] is True, connected
    print("dry-run connect ok")

    disconnected = post_json("/api/v1/session/disconnect")
    assert disconnected["ok"] is True, disconnected
    print("disconnect ok")


if __name__ == "__main__":
    main()
