"""动作列表 / dry-run 播放 / 停止测试。"""

from __future__ import annotations

import time

from Web测试客户端_test_client import connect_dry_run, get_json, post_json


def main() -> None:
    connect_dry_run()
    actions = get_json("/api/v1/actions", timeout=10)
    assert actions["ok"] is True, actions
    items = actions["data"].get("actions", [])
    print(f"动作数量：{len(items)}")
    if not items:
        print("动作库为空，跳过播放。")
        return

    name = items[0]["name"]
    started = post_json("/api/v1/actions/play", {"name": name, "speed": 2.0, "loop": False}, timeout=12)
    assert started["ok"] is True, started
    print(f"dry-run action play started: {name}")
    time.sleep(0.5)
    stopped = post_json("/api/v1/actions/stop")
    assert stopped["ok"] is True, stopped
    print("action stop ok")


if __name__ == "__main__":
    main()
