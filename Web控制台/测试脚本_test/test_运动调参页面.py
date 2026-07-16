"""Web 运动调参页面只暴露会实际影响 Web 行为的选项。"""

from pathlib import Path
import unittest


WEB_ROOT = Path(__file__).resolve().parents[1]


class MotionTuningPageTest(unittest.TestCase):
    def test_gui_only_quick_step_fields_are_not_exposed(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        for element_id in ("quickStepDuration", "quickStepFrames"):
            self.assertNotIn(f'id="{element_id}"', index)
            self.assertNotIn(f'$("#{element_id}")', app)

    def test_frontend_asset_version_matches_motion_tuning_update(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn('/static/app.js?v=20260716-', index)
        self.assertNotIn('/static/app.js?v=20260628-kinematics-ui', index)

    def test_reset_button_does_not_reset_gui_only_fields(self) -> None:
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('postJson("/api/v1/motion/tuning/reset"', app)


if __name__ == "__main__":
    unittest.main()
