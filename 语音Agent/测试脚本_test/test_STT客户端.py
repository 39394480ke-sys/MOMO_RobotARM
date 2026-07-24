"""云端 STT 客户端配置和错误分类测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import requests
import yaml

from Agent测试路径_test_paths import agent_config_path, ensure_agent_test_paths

ensure_agent_test_paths()

from agent.语音转文字_stt import transcribe_audio


class SpeechToTextClientTest(unittest.TestCase):
    def test_timeout_is_reported_separately_from_unavailable_service(self) -> None:
        config = {"stt": {"provider": "http", "url": "https://example.invalid", "timeout_sec": 1}}

        with patch("agent.语音转文字_stt.requests.post", side_effect=requests.Timeout):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                transcribe_audio(b"wav", config)

        with patch("agent.语音转文字_stt.requests.post", side_effect=requests.ConnectionError):
            with self.assertRaisesRegex(RuntimeError, "不可用"):
                transcribe_audio(b"wav", config)

    def test_repository_template_uses_siliconflow_sensevoice(self) -> None:
        payload = yaml.safe_load(agent_config_path().read_text(encoding="utf-8"))

        self.assertEqual(payload["stt"]["url"], "https://api.siliconflow.cn/v1/audio/transcriptions")
        self.assertEqual(payload["stt"]["model"], "FunAudioLLM/SenseVoiceSmall")
        self.assertEqual(payload["stt"]["api_key"], "${SILICONFLOW_API_KEY}")


if __name__ == "__main__":
    unittest.main()
