"""文本 ask 测试：不需要麦克风。"""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.对话应用_agent_app import AgentApp
from agent.配置_config import load_config


def main() -> None:
    config = load_config(BASE_DIR / "Agent配置.yaml")
    config.setdefault("tts", {})["enabled"] = False
    app = AgentApp(config)
    app.ask_text("请查询机械臂状态", speak=False)


if __name__ == "__main__":
    main()

