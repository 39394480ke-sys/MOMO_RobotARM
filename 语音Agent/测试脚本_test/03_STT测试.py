"""读取 last_record.wav 并调用 STT。"""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.配置_config import config_base_dir, load_config, resolve_path
from agent.语音转文字_stt import transcribe_audio


def main() -> None:
    config = load_config(BASE_DIR / "Agent配置.yaml")
    path = resolve_path(config.get("audio", {}).get("last_wav_path", "runtime/audio/last_record.wav"), config_base_dir(config))
    if not path.exists():
        print(f"未找到录音文件：{path}，请先运行 02_录音测试.py")
        return
    text = transcribe_audio(path.read_bytes(), config)
    print(f"STT 结果：{text}")


if __name__ == "__main__":
    main()

