"""AI 对话语音转写接口测试。"""

from __future__ import annotations

import io
import asyncio
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()
agent_root = Path(__file__).resolve().parents[2] / "语音Agent"
if str(agent_root) not in sys.path:
    sys.path.insert(0, str(agent_root))

from backend.errors import WebAPIError
from backend.service import WebControlService
import backend.app as app_module


def make_wav(
    *,
    duration_sec: float = 0.25,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
    sample_value: int = 1200,
) -> bytes:
    frame_count = int(duration_sec * sample_rate)
    if sample_width == 2:
        sample = int(sample_value).to_bytes(2, "little", signed=True)
    else:
        sample = bytes([128])
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(sample * channels * frame_count)
    return output.getvalue()


class AgentTranscribeTest(unittest.TestCase):
    def make_service(self) -> WebControlService:
        service = WebControlService.__new__(WebControlService)
        service._load_agent_config = lambda: {
            "audio": {"max_record_sec": 20},
            "stt": {"provider": "http", "url": "https://example.invalid/transcriptions"},
        }
        service.logger = type("Logger", (), {"log": lambda *args, **kwargs: None})()
        return service

    def assert_error(self, expected_code: str, audio: bytes) -> None:
        with self.assertRaises(WebAPIError) as caught:
            self.make_service().agent_transcribe(audio)
        self.assertEqual(caught.exception.code, expected_code)

    def test_valid_wav_is_transcribed_without_logging_text(self) -> None:
        service = self.make_service()
        events = []
        service.logger = type("Logger", (), {"log": lambda _self, *args, **kwargs: events.append((args, kwargs))})()
        with patch("agent.语音转文字_stt.transcribe_audio", return_value="机械臂向左转") as transcribe:
            result = service.agent_transcribe(make_wav())

        self.assertEqual(result, {"text": "机械臂向左转"})
        transcribe.assert_called_once()
        self.assertNotIn("机械臂向左转", repr(events))

    def test_rejects_empty_or_oversized_body(self) -> None:
        self.assert_error("AUDIO_EMPTY", b"")
        self.assert_error("AUDIO_TOO_LARGE", b"x" * (1024 * 1024 + 1))

    def test_rejects_invalid_or_unsupported_wav(self) -> None:
        self.assert_error("AUDIO_INVALID", b"not a wav")
        self.assert_error("AUDIO_FORMAT_UNSUPPORTED", make_wav(sample_rate=48000))
        self.assert_error("AUDIO_FORMAT_UNSUPPORTED", make_wav(channels=2))
        self.assert_error("AUDIO_FORMAT_UNSUPPORTED", make_wav(sample_width=1))

    def test_rejects_too_long_or_silent_audio(self) -> None:
        self.assert_error("AUDIO_TOO_LONG", make_wav(duration_sec=20.01))
        self.assert_error("AUDIO_SILENT", make_wav(sample_value=0))

    def test_maps_empty_transcript_and_cloud_failures(self) -> None:
        service = self.make_service()
        with patch("agent.语音转文字_stt.transcribe_audio", return_value=""):
            with self.assertRaises(WebAPIError) as empty:
                service.agent_transcribe(make_wav())
        self.assertEqual(empty.exception.code, "STT_NO_SPEECH")

        with patch("agent.语音转文字_stt.transcribe_audio", side_effect=RuntimeError("STT 服务请求超时。")):
            with self.assertRaises(WebAPIError) as timeout:
                service.agent_transcribe(make_wav())
        self.assertEqual(timeout.exception.code, "STT_TIMEOUT")

        with patch("agent.语音转文字_stt.transcribe_audio", side_effect=RuntimeError("STT 服务不可用。")):
            with self.assertRaises(WebAPIError) as unavailable:
                service.agent_transcribe(make_wav())
        self.assertEqual(unavailable.exception.code, "STT_UNAVAILABLE")


class FakeRequest:
    def __init__(self, body: bytes, content_type: str = "audio/wav") -> None:
        self._body = body
        self.headers = {"content-type": content_type, "content-length": str(len(body))}

    async def body(self) -> bytes:
        return self._body

    async def stream(self):
        yield self._body


class AgentTranscribeRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_service = app_module.service
        self.received = []
        self.fake_service = type(
            "FakeService",
            (),
            {"agent_transcribe": lambda _service, body: self.received.append(body) or {"text": "转写结果"}},
        )()
        app_module.service = self.fake_service

    def tearDown(self) -> None:
        app_module.service = self.original_service

    def test_route_accepts_raw_wav_and_uses_standard_envelope(self) -> None:
        result = asyncio.run(app_module.agent_transcribe(FakeRequest(b"wav bytes")))

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"text": "转写结果"})
        self.assertEqual(self.received, [b"wav bytes"])

    def test_route_rejects_non_wav_content_type(self) -> None:
        with self.assertRaises(WebAPIError) as caught:
            asyncio.run(app_module.agent_transcribe(FakeRequest(b"data", "audio/webm")))
        self.assertEqual(caught.exception.code, "AUDIO_CONTENT_TYPE")
        self.assertEqual(self.received, [])

    def test_route_stops_reading_body_after_size_limit(self) -> None:
        with self.assertRaises(WebAPIError) as caught:
            asyncio.run(app_module.agent_transcribe(FakeRequest(b"x" * (1024 * 1024 + 1))))
        self.assertEqual(caught.exception.code, "AUDIO_TOO_LARGE")
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main()
