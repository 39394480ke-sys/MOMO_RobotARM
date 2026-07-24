"""AI 对话语音输入的静态界面契约测试。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import WEB_ROOT


class AgentVoiceInputUITest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.styles = (WEB_ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_input_has_record_stop_cancel_and_live_status_controls(self) -> None:
        self.assertIn('id="agentVoiceBtn"', self.index)
        self.assertIn('id="cancelAgentVoiceBtn"', self.index)
        self.assertIn('id="agentVoiceStatus"', self.index)
        self.assertIn('aria-live="polite"', self.index)
        self.assertIn("audio-recorder.js", self.index)

    def test_app_records_transcribes_and_only_fills_the_input(self) -> None:
        self.assertIn("async function toggleAgentVoiceRecording", self.app)
        self.assertIn("async function cancelAgentVoiceRecording", self.app)
        self.assertIn("async function transcribeAgentAudio", self.app)
        self.assertIn('"/api/v1/agent/transcribe"', self.app)
        self.assertIn("MomoAudio.insertTranscript", self.app)
        transcribe_body = self.app.split("async function transcribeAgentAudio", 1)[1].split("\n}", 1)[0]
        self.assertNotIn("sendAgentMessage(", transcribe_body)

    def test_voice_controls_have_stable_mobile_dimensions_and_states(self) -> None:
        self.assertIn(".agent-voice-btn", self.styles)
        self.assertIn(".agent-voice-btn.recording", self.styles)
        self.assertIn(".agent-voice-status", self.styles)
        self.assertIn("min-width: 44px;", self.styles)
        self.assertIn("min-height: 44px;", self.styles)


if __name__ == "__main__":
    unittest.main()
