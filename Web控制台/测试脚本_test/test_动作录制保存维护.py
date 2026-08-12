"""动作录制的未命名规则与最少帧数门禁。"""

from pathlib import Path
import unittest
from unittest.mock import Mock

import Web测试路径_test_paths  # noqa: F401
from backend.controller_bridge import ControllerBridge
from backend.schemas import ActionRecordingStartRequest


WEB_ROOT = Path(__file__).resolve().parents[1]


class ActionRecordingSaveMaintenanceTest(unittest.TestCase):
    def test_empty_recording_name_is_accepted_by_api_schema(self) -> None:
        request = ActionRecordingStartRequest()
        self.assertEqual(request.name, "")

    def test_untitled_name_uses_first_available_sequence_number(self) -> None:
        bridge = object.__new__(ControllerBridge)
        bridge._get_action_library = Mock()
        bridge._get_action_library.return_value.list_actions.return_value = ["挥手", "未命名1", "未命名2", "未命名4"]

        self.assertEqual(bridge._next_untitled_action_name(), "未命名3")

    def test_single_frame_is_rejected_without_clearing_recording(self) -> None:
        bridge = object.__new__(ControllerBridge)
        bridge.recording_sequence = {"poses": [{"name": "pose_1"}]}
        bridge.recording_name = "未命名1"
        bridge.recording_source = "web_record"
        bridge.recording_auto_named = True

        result = bridge.save_recording_action()

        self.assertFalse(result["ok"])
        self.assertIn("至少需要两帧", result["message"])
        self.assertEqual(len(bridge.recording_sequence["poses"]), 1)
        self.assertEqual(bridge.recording_name, "未命名1")

    def test_frontend_warns_and_returns_before_single_frame_save_request(self) -> None:
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        guard = 'if (Number(recording.pose_count || 0) < 2)'
        warning = "showRecordingFrameWarning();"
        request = 'postJsonLogged("/api/v1/actions/recording/save", {})'

        self.assertIn(guard, app)
        self.assertIn(warning, app)
        self.assertLess(app.index(guard), app.index(request))
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="recordingFrameWarningDialog"', index)
        self.assertIn("当前录制只有一帧", index)
        self.assertIn('recording-unnamed-two-frame-guard', index)


if __name__ == "__main__":
    unittest.main()
