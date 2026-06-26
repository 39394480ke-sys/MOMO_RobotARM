"""录音并保存 runtime/audio/last_record.wav。"""

from __future__ import annotations

from Agent测试路径_test_paths import agent_config_path

from agent.配置_config import config_base_dir, load_config, resolve_path
from agent.语音输入_audio_input import record_until_enter


def main() -> None:
    config = load_config(agent_config_path())
    wav_bytes = record_until_enter(config)
    path = resolve_path(config.get("audio", {}).get("last_wav_path", "runtime/audio/last_record.wav"), config_base_dir(config))
    print(f"录音已保存：{path}，大小 {len(wav_bytes)} bytes")


if __name__ == "__main__":
    main()
