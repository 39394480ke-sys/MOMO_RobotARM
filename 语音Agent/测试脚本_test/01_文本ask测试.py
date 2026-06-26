"""文本 ask 测试：不需要麦克风。"""

from __future__ import annotations

from Agent测试路径_test_paths import agent_config_path

from agent.对话应用_agent_app import AgentApp
from agent.配置_config import load_config


def main() -> None:
    config = load_config(agent_config_path())
    config.setdefault("tts", {})["enabled"] = False
    app = AgentApp(config)
    app.ask_text("请查询机械臂状态", speak=False)


if __name__ == "__main__":
    main()
