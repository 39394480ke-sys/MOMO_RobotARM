"""Web 快速控制在移动端长按时不触发浏览器选择或菜单。"""

from pathlib import Path
import unittest


WEB_ROOT = Path(__file__).resolve().parents[1]


class MobileJointHoldControlTest(unittest.TestCase):
    def test_joint_buttons_disable_selection_callout_and_touch_gestures(self) -> None:
        styles = (WEB_ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".joint-row button[data-joint]", styles)
        self.assertIn("-webkit-user-select: none;", styles)
        self.assertIn("user-select: none;", styles)
        self.assertIn("-webkit-touch-callout: none;", styles)
        self.assertIn("touch-action: none;", styles)

    def test_context_menu_is_blocked_only_for_joint_buttons(self) -> None:
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertIn('wrap.addEventListener("contextmenu"', app)
        self.assertIn('event.target.closest("button[data-joint]")', app)
        self.assertIn("event.preventDefault();", app)

    def test_stylesheet_cache_version_is_updated(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn('mobile-joint-hold', index)

    def test_script_cache_version_includes_mobile_hold_fix(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn('ai-confirm-mobile-joint-hold', index)


if __name__ == "__main__":
    unittest.main()
