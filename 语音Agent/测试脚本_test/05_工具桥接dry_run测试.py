"""工具桥接 dry-run 测试：确认走阶段八 API。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.工具桥接_tool_bridge import RobotToolBridge
from agent.配置_config import load_config


def main() -> None:
    config = load_config(BASE_DIR / "Agent配置.yaml")
    bridge = RobotToolBridge(config)
    print(f"阶段八 API：{config.get('robot_api', {}).get('base_url')}")
    for name, args in [
        ("get_robot_state", {}),
        ("stop_robot", {}),
        ("rotate_joint", {"joint_name": "J1", "delta_deg": 1.0}),
    ]:
        result = bridge.execute(name, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

