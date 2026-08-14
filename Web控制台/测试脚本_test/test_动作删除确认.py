"""动作删除使用简单的是/否确认，不要求重新输入动作名。"""

from pathlib import Path
import unittest


WEB_ROOT = Path(__file__).resolve().parents[1]


class ActionDeleteConfirmationTest(unittest.TestCase):
    def test_delete_uses_boolean_confirmation(self) -> None:
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("window.prompt(", app)
        self.assertIn("window.confirm(", app)
        self.assertIn("是否确认删除动作", app)

    def test_frontend_asset_version_is_updated(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn('20260814-library-item-rename', index)
        self.assertNotIn('/static/app.js?v=20260628-kinematics-ui', index)


if __name__ == "__main__":
    unittest.main()
