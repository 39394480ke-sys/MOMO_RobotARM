"""AI 动作确认卡的静态界面契约测试。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import WEB_ROOT


class AgentPendingActionUITest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.styles = (WEB_ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_frontend_calls_confirm_and_cancel_endpoints(self) -> None:
        self.assertIn("function renderAgentPendingAction", self.app)
        self.assertIn("async function confirmAgentPendingAction", self.app)
        self.assertIn("async function cancelAgentPendingAction", self.app)
        self.assertIn('"/api/v1/agent/pending/confirm"', self.app)
        self.assertIn('"/api/v1/agent/pending/cancel"', self.app)

    def test_action_card_has_explicit_buttons_and_states(self) -> None:
        self.assertIn("确认执行", self.app)
        self.assertIn("取消", self.app)
        for state in ("pending", "executing", "executed", "cancelled", "expired", "invalidated"):
            self.assertIn(state, self.app)
        self.assertIn("agent-pending-card", self.styles)

    def test_joint_summary_formats_j10_as_mm_and_rotary_as_degrees(self) -> None:
        self.assertIn('summary.unit === "mm" ? "mm" : "°"', self.app)

    def test_agent_ask_attaches_server_pending_action(self) -> None:
        self.assertIn("data.pending_action", self.app)
        self.assertIn("pendingAction", self.app)

    def test_asset_version_preserves_j10_unit_suffix(self) -> None:
        self.assertIn("continuous-follow-j10-mm-ai-confirm", self.index)


if __name__ == "__main__":
    unittest.main()
