"""录音 -> STT -> ask -> TTS。可用 MOMO_MOCK_STT_TEXT 跳过真实 STT 服务。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.对话应用_agent_app import AgentApp
from agent.配置_config import load_config


def main() -> None:
    config = load_config(BASE_DIR / "Agent配置.yaml")
    app = AgentApp(config)
    if os.environ.get("MOMO_MOCK_STT_TEXT"):
        app.ask_text(os.environ["MOMO_MOCK_STT_TEXT"], speak=bool(config.get("tts", {}).get("enabled", True)))
        return
    app.run_voice_turn(speak=bool(config.get("tts", {}).get("enabled", True)))


if __name__ == "__main__":
    main()
