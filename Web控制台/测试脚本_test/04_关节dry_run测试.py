"""dry-run 关节微调测试。不会真实写舵机。"""

from __future__ import annotations

import json

from Web测试客户端_test_client import connect_dry_run, post_json


def main() -> None:
    connect_dry_run()
    payload = post_json(
        "/api/v1/motion/joint-step",
        {"joint_key": "j11", "delta_deg": 1.0, "speed_percent": 50},
    )
    assert payload["ok"] is True, payload
    print("dry-run joint-step ok，不会真实写舵机")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
