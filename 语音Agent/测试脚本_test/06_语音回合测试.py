"""录音 -> STT -> ask -> TTS。可用 ARM_MOCK_STT_TEXT 跳过真实 STT 服务。"""

from __future__ import annotations

import os

from Agent测试路径_test_paths import agent_config_path
from agent.对话应用_agent_app import AgentApp
from agent.配置_config import load_config


def main() -> None:
    config = load_config(agent_config_path())
    app = AgentApp(config)
    if os.environ.get("ARM_MOCK_STT_TEXT"):
        app.ask_text(os.environ["ARM_MOCK_STT_TEXT"], speak=bool(config.get("tts", {}).get("enabled", True)))
        return
    app.run_voice_turn(speak=bool(config.get("tts", {}).get("enabled", True)))


if __name__ == "__main__":
    main()
