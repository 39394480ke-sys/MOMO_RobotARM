"""TTS 播放测试。"""

from __future__ import annotations

from Agent测试路径_test_paths import agent_config_path

from agent.配置_config import load_config
from agent.语音播报_tts import speak_text


def main() -> None:
    config = load_config(agent_config_path())
    try:
        speak_text("你好，我是机械臂语音助手。", config)
    except Exception as exc:
        print(f"TTS 不可用：{exc}")


if __name__ == "__main__":
    main()
