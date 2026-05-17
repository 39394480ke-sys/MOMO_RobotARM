"""TTS 播放测试。"""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.配置_config import load_config
from agent.语音播报_tts import speak_text


def main() -> None:
    config = load_config(BASE_DIR / "Agent配置.yaml")
    try:
        speak_text("你好，我是机械臂语音助手。", config)
    except Exception as exc:
        print(f"TTS 不可用：{exc}")


if __name__ == "__main__":
    main()

