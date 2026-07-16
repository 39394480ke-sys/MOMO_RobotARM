"""Web 动作录制统一使用普通录制。"""

from pathlib import Path
import unittest

import Web测试路径_test_paths  # noqa: F401
from backend.schemas import ActionRecordingStartRequest


WEB_ROOT = Path(__file__).resolve().parents[1]


class RemoveTeachRecordingTest(unittest.TestCase):
    def test_teach_recording_is_not_exposed_by_web_ui(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("recordingSourceSelect", index)
        self.assertNotIn("示教录制", index)
        self.assertNotIn("recordingSourceSelect", app)
        self.assertNotIn("web_teach_mode", app)

    def test_legacy_source_field_is_ignored(self) -> None:
        request = ActionRecordingStartRequest(name="测试动作", source="web_teach_mode")
        payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()

        self.assertNotIn("source", payload)

    def test_frontend_asset_version_is_updated(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn('/static/app.js?v=20260716-remove-teach-recording', index)


if __name__ == "__main__":
    unittest.main()
