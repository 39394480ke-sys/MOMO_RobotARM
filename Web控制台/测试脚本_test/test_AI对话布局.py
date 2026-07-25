"""AI 对话页精简与响应式布局的静态契约测试。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import WEB_ROOT


class AgentChatLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.css = (WEB_ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.js = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    def test_removes_demo_shortcut_buttons_and_binding(self) -> None:
        for label in ("环绕运镜", "生成海报", "查状态", "安全说明"):
            self.assertNotIn(f">{label}</button>", self.html)
        self.assertNotIn("agent-quick-btn", self.html)
        self.assertNotIn('$$(".agent-quick-btn")', self.js)

    def test_uses_agent_specific_responsive_grid(self) -> None:
        self.assertIn('class="settings-grid agent-layout"', self.html)
        self.assertIn(".agent-layout", self.css)
        self.assertIn("minmax(0, 1fr)", self.css)

    def test_config_values_can_shrink_and_wrap(self) -> None:
        self.assertIn(".agent-config-panel .kv.wide", self.css)
        self.assertIn(".agent-config-panel .kv dd", self.css)
        self.assertIn("overflow-wrap: anywhere;", self.css)


if __name__ == "__main__":
    unittest.main()
