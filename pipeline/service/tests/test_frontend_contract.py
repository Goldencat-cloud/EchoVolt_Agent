"""前端资产契约测试（8.3）：守护 HTML/JS/CSS 与后端之间的隐式约定。

这些断言源自 2026-10 前端审计与修复，防止后续改动静默破坏：
- 深度分析轮询必须处理 clarifying / awaiting_review 两个等待节点（P0-1）；
- 读屏播报区存在，对话流本身不再挂 aria-live（5.1）；
- combobox / separator 语义（5.5/5.6）；
- 对比度 token 保持在 AA 修正值（5.2）；
- 报告标题编号契约：showReport 按 h3/h4/h5 顺序编号 agent-N，
  与 report_source.sections_from_markdown 的 ``#{1,3}`` 规则一一对应（8.3）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import report_source

WEB = Path(__file__).resolve().parents[1] / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class IndexHtmlContract(unittest.TestCase):
    def setUp(self) -> None:
        self.html = read("index.html")

    def test_chat_log_is_not_a_live_region(self):
        # 5.1：对话流整体不得再是 live region（读屏会反复重读全部消息）
        self.assertNotRegex(self.html, r'id="chat-log"[^>]*aria-live')

    def test_dedicated_live_region_exists(self):
        self.assertRegex(self.html, r'id="live-status"[^>]*role="status"')

    def test_combobox_semantics(self):
        # 5.5：输入框与补全浮层的 combobox 关联
        self.assertRegex(self.html, r'id="question"[^>]*role="combobox"')
        self.assertRegex(self.html, r'id="question"[^>]*aria-controls="composer-suggest"')
        self.assertRegex(self.html, r'id="composer-suggest"[^>]*role="listbox"')

    def test_divider_is_keyboard_operable_separator(self):
        # 5.6：分隔条可聚焦且不再是 aria-hidden
        divider = re.search(r'<div id="result-divider"[^>]*>', self.html)
        self.assertIsNotNone(divider)
        tag = divider.group(0)
        self.assertIn('role="separator"', tag)
        self.assertIn("tabindex", tag)
        self.assertNotIn("aria-hidden", tag)

    def test_static_assets_are_versioned(self):
        for asset in ("app.js", "styles.css", "tokens.css"):
            self.assertRegex(self.html, rf'{asset}\?v='), asset


class AppJsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.js = read("app.js")

    def test_poll_handles_both_wait_states(self):
        # P0-1：轮询必须显式处理两个等待用户输入的状态，否则 UI 无限等待
        for status in ("clarifying", "awaiting_review", "done", "failed"):
            self.assertIn(f"j.status==='{status}'", self.js)

    def test_deep_action_endpoints(self):
        for action in ("clarify", "outline"):
            self.assertIn(f"postDeepAction('{action}'", self.js)

    def test_progress_card_updates_in_place(self):
        # 7.1：轮询只更新阶段文本，不整体重建进度卡
        self.assertIn("data-progress-phase", self.js)

    def test_announce_wired(self):
        self.assertIn("function announce(", self.js)

    def test_click_dispatch_is_table_driven(self):
        # 3.1：分发为映射表，新增交互不再追加 if 链分支
        self.assertIn("CLICK_ACTIONS=[", self.js)
        self.assertIn("of CLICK_ACTIONS)", self.js)

    def test_suggest_guard_against_empty_dropdown(self):
        # 9.1：补全无命中时不得渲染空白浮层
        self.assertIn("if(!items.length){hideSuggest();return}", self.js)

    def test_report_heading_numbering_matches_backend(self):
        # 8.3：前端给 h3/h4/h5 顺序编号 agent-N；renderMarkdown 把 markdown
        # #{1,3} 渲染为 h3/h4/h5（min(level+2,6)），与后端 sections_from_markdown
        # 的 #{1,3} 计数一一对应。两侧任一规则改动都必须同步。
        self.assertIn("querySelectorAll('.report-body :is(h3,h4,h5)')", self.js)
        self.assertIn("Math.min(m[1].length+2,6)", self.js)
        sample = "# 标题\n\n导语\n\n## 章节 A\n\n正文\n\n### 小节 A1\n\n正文\n"
        sections = report_source.sections_from_markdown(sample)
        self.assertEqual([s["id"] for s in sections], ["agent-1", "agent-2", "agent-3"])


class CssContract(unittest.TestCase):
    def setUp(self) -> None:
        self.css = read("styles.css")
        self.tokens = read("tokens.css")

    def test_dvh_fallback(self):
        # 2.2：dvh 必须有 100vh 回退且在前
        self.assertIn("height: 100vh; height: 100dvh;", self.css)

    def test_mobile_input_font_size_16(self):
        # 2.1：≤600px 输入控件 16px，避免 iOS 聚焦缩放
        self.assertIn(".qf-input, .qi-edit { font-size: 16px; }", self.css)

    def test_backdrop_filter_prefix(self):
        self.assertIn("-webkit-backdrop-filter", self.css)

    def test_dead_tokens_removed(self):
        for token in ("--brand-gradient", "--user-gradient", "--chat-w",
                      "--chat-min", "--chat-max"):
            self.assertNotIn(token, self.tokens)

    def test_contrast_tokens(self):
        # 5.2：AA 修正后的色值；改回旧值必须先重做对比度评估
        self.assertIn("--muted: #5f646a;", self.tokens)
        self.assertIn("--gold: #96611b;", self.tokens)


if __name__ == "__main__":
    unittest.main()
