# Web AI 对话页布局优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 AI 对话页的四个快捷按钮，并让 Agent 配置面板在桌面和移动视口下稳定显示长 URL。

**Architecture:** 保持现有静态 HTML、CSS 和原生 JavaScript 结构，只移除快捷按钮 DOM 及其事件绑定。为 AI 页面增加专用网格类，配置键值表使用固定标签列和可收缩值列，避免影响其他设置页面。

**Tech Stack:** HTML5、CSS Grid、原生 JavaScript、Python `unittest` 静态界面契约测试、Browser 插件视觉验证。

## Global Constraints

- 不改变 AI 对话、语音输入、动作确认或机械臂控制 API。
- 保留“刷新状态”“清空聊天”“重置会话”。
- 桌面端对话区为主栏，Agent 配置区为辅助栏；窄屏改为上下布局。
- API、STT、TTS 等长文本必须换行，页面不得横向溢出。
- 同步修改当前运行的 `/tmp/momo-v2-web-voice` 前端副本。

---

### Task 1: AI 对话页结构与响应式布局

**Files:**
- Create: `Web控制台/测试脚本_test/test_AI对话布局.py`
- Modify: `Web控制台/frontend/index.html`
- Modify: `Web控制台/frontend/styles.css`
- Modify: `Web控制台/frontend/app.js`

**Interfaces:**
- Consumes: 现有 `#pageAgent`、`.agent-chat-panel`、`.agent-config-panel`、`.kv.wide` DOM 结构。
- Produces: `.agent-layout` 专用两栏网格，以及不包含 `.agent-quick-row` / `.agent-quick-btn` 的 AI 页面。

- [ ] **Step 1: 写入失败的静态界面契约测试**

```python
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
```

- [ ] **Step 2: 运行测试并确认因现有快捷按钮和缺少专用布局而失败**

Run:

```bash
cd Web控制台/测试脚本_test
/Users/ke/mamba/envs/momo_rebot/bin/python -m unittest test_AI对话布局
```

Expected: FAIL，报告仍存在 `agent-quick-btn` 或缺少 `agent-layout`。

- [ ] **Step 3: 修改 HTML 与 JavaScript**

在 `index.html` 中：

```html
<div class="settings-grid agent-layout">
```

删除完整的 `<div class="agent-quick-row">...</div>`。在 `app.js` 的事件绑定区删除：

```javascript
$$(".agent-quick-btn").forEach((btn) => btn.addEventListener("click", () => useAgentPrompt(btn.dataset.agentPrompt || "")));
```

- [ ] **Step 4: 添加桌面与移动布局样式**

在 `styles.css` 的 Agent 样式区加入：

```css
.agent-layout {
  grid-template-columns: minmax(420px, 1.35fr) minmax(300px, 0.85fr);
  align-items: stretch;
}

.agent-chat-panel,
.agent-config-panel {
  min-width: 0;
}

.agent-config-panel .kv.wide {
  grid-template-columns: 96px minmax(0, 1fr);
}

.agent-config-panel .kv dd {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
```

删除不再使用的 `.agent-quick-row` 样式。移动断点中令 `.agent-layout` 使用单列，并保留现有 Agent 面板跨 12 列规则。

- [ ] **Step 5: 运行静态测试和 JavaScript 语法检查**

Run:

```bash
cd Web控制台/测试脚本_test
/Users/ke/mamba/envs/momo_rebot/bin/python -m unittest test_AI对话布局 test_AI语音输入界面 test_AI动作确认界面
node --check ../frontend/app.js
```

Expected: 全部 PASS，`node --check` 退出码为 0。

- [ ] **Step 6: 提交源代码改动**

```bash
git add Web控制台/frontend/index.html Web控制台/frontend/styles.css Web控制台/frontend/app.js Web控制台/测试脚本_test/test_AI对话布局.py
git commit -m "fix: polish Web AI chat layout"
```

### Task 2: 当前运行副本同步与浏览器验证

**Files:**
- Modify: `/tmp/momo-v2-web-voice/Web控制台/frontend/index.html`
- Modify: `/tmp/momo-v2-web-voice/Web控制台/frontend/styles.css`
- Modify: `/tmp/momo-v2-web-voice/Web控制台/frontend/app.js`

**Interfaces:**
- Consumes: Task 1 完成后的三个前端源文件。
- Produces: `http://127.0.0.1:8010/` 中立即可见的新 AI 对话布局。

- [ ] **Step 1: 将三个已验证文件同步到当前运行副本**

使用逐文件内容一致性同步，并确认：

```bash
cmp Web控制台/frontend/index.html /tmp/momo-v2-web-voice/Web控制台/frontend/index.html
cmp Web控制台/frontend/styles.css /tmp/momo-v2-web-voice/Web控制台/frontend/styles.css
cmp Web控制台/frontend/app.js /tmp/momo-v2-web-voice/Web控制台/frontend/app.js
```

Expected: 三个 `cmp` 均退出码为 0。

- [ ] **Step 2: 使用 Browser 插件验证桌面布局**

目标流程：

```text
打开 http://127.0.0.1:8010/ -> 点击“AI 对话” -> 快捷按钮消失，配置 URL 正常换行，页面无横向溢出
```

检查页面标题、DOM 非空、无框架错误层、控制台无相关错误，并在约 `1440 × 900` 视口截图。

- [ ] **Step 3: 验证移动布局与一个交互**

将视口改为约 `390 × 844`，确认面板上下排列、输入栏无重叠。点击“刷新状态”，确认“可用/不可用”状态更新且没有控制台错误。

- [ ] **Step 4: 最终回归**

Run:

```bash
cd Web控制台/测试脚本_test
/Users/ke/mamba/envs/momo_rebot/bin/python -m unittest test_AI对话布局 test_AI语音输入界面 test_AI动作确认界面
node --check ../frontend/app.js
git diff --check
```

Expected: 测试全部 PASS，语法检查及 `git diff --check` 均退出码为 0。
