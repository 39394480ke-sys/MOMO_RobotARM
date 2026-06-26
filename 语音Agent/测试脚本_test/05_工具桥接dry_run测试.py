"""工具桥接 dry-run 测试：确认走阶段八 API。"""

from __future__ import annotations

import json
import os

from Agent测试路径_test_paths import agent_config_path
from agent.工具桥接_tool_bridge import RobotToolBridge
from agent.配置_config import load_config
from 通用_http import request_json_object


def main() -> None:
    config = load_config(agent_config_path())
    override_url = os.environ.get("ROBOT_API_URL") or os.environ.get("WEB_API_URL")
    if override_url:
        config.setdefault("robot_api", {})["base_url"] = override_url
    base_url = str(config.get("robot_api", {}).get("base_url", "http://127.0.0.1:8010")).rstrip("/")
    connected = request_json_object(
        base_url + "/api/v1/session/connect",
        method="POST",
        payload={"mode": "dry_run"},
        timeout=8,
    )
    assert connected["ok"] is True, connected

    bridge = RobotToolBridge(config)
    print(f"阶段八 API：{config.get('robot_api', {}).get('base_url')}")
    for name, args in [
        ("get_robot_state", {}),
        ("stop_robot", {}),
        ("rotate_joint", {"joint_name": "J1", "delta_deg": 1.0}),
    ]:
        result = bridge.execute(name, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert result["ok"] is True, result


if __name__ == "__main__":
    main()
