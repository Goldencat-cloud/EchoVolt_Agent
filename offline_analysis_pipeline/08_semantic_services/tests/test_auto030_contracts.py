"""auto-030 light-backend contracts.

Covers: conversation toolset shrink (no interpreter / no report submit),
behavior-level report-production guard, /api/ask report_ref validation and
citations.refs, and the markdown section parser used for "mine" reports.
All tests are deterministic (no LLM configured unless explicitly stubbed).
"""
import json
import os
import sys
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

AI_ENV = ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_DATA_APPROVED")


class ConversationToolsetTests(unittest.TestCase):
    """2.1: the chat agent must not see the interpreter or report submission."""

    def test_conversation_tools_exclude_interpreter_and_submit(self):
        import agent_engine
        import agent_tools
        deep_names = {tool.name for tool in agent_tools.build_tools({})}
        self.assertIn("python_analyze", deep_names)   # 深度流程保留完整工具集
        self.assertIn("submit_report", deep_names)
        from tests import kernel_fixture as kf
        conversation = deep_names - kf.LEGACY_CONVERSATION_EXCLUDED_TOOLS
        self.assertNotIn("python_analyze", conversation)
        self.assertNotIn("submit_report", conversation)
        for keep in ("semantic_overview", "run_semantic_aggregate",
                     "get_negative_evidence", "search_published_report"):
            self.assertIn(keep, conversation)

    def test_unknown_citation_anchors_are_stripped(self):
        import agent_engine
        with patch.object(app.report_source, "load_sections",
                          return_value=[{"id": "F1", "title": "发现", "text": "text"}]):
            cleaned = agent_engine._strip_unknown_citations(
                "负面占比 12.3% [F1]，另有虚构引用 [XX99]。")
        self.assertNotIn("[XX99]", cleaned)
        self.assertIn("[F1]", cleaned)


class SectionParserTests(unittest.TestCase):
    """3.1/3.2 support: markdown → citable sections with synthetic ids."""

    def test_headings_map_to_agent_n_in_order(self):
        import report_source
        md = "# 标题A\n正文A\n## 标题B\n正文B\n### 标题C\n正文C\n"
        sections = report_source.sections_from_markdown(md)
        self.assertEqual([s["id"] for s in sections], ["agent-1", "agent-2", "agent-3"])
        self.assertEqual(sections[0]["title"], "标题A")
        self.assertEqual(sections[1]["text"].strip(), "正文B")

    def test_heading_less_markdown_yields_no_sections(self):
        import report_source
        self.assertEqual(report_source.sections_from_markdown("只有正文，没有标题。"), [])
        self.assertEqual(report_source.sections_from_markdown(""), [])


class AskReportRefAPITests(unittest.TestCase):
    """3.1/3.2: /api/ask report_ref validation is deterministic (pre-LLM)."""

    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.pop(k, None) for k in AI_ENV}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        import threading
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server_thread.join(timeout=5)
        cls.server.server_close()
        for k, v in cls._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def setUp(self):
        app._RATE.clear()

    def post(self, path: str, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_mine_report_requires_content(self):
        status, payload = self.post("/api/ask", {
            "question": "负面反馈集中在哪？", "report_ref": {"kind": "mine"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_report_ref")

    def test_mine_report_over_budget_rejected(self):
        # 用小阈值 patch，避免真实 60K 内容撞上 HTTP 层的 MAX_BODY（413）
        with patch.object(app, "MAX_REPORT_CONTEXT_CHARS", 100):
            status, payload = self.post("/api/ask", {
                "question": "总结一下",
                "report_ref": {"kind": "mine", "report_id": "r1",
                               "content": "# 标题\n" + "字" * 200}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_report_ref")
        self.assertIn("上下文预算", payload["message"])

    def test_invalid_kind_rejected(self):
        status, payload = self.post("/api/ask", {
            "question": "总结一下", "report_ref": {"kind": "weird"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_report_ref")

    def test_mine_content_without_headings_rejected(self):
        status, payload = self.post("/api/ask", {
            "question": "总结一下",
            "report_ref": {"kind": "mine", "report_id": "r1", "content": "没有标题的正文。"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_report_content")

    def test_official_ref_preserves_unconfigured_behavior(self):
        status, payload = self.post("/api/ask", {
            "question": "负面反馈集中在哪？", "report_ref": {"kind": "official"}})
        # 无模型配置时官方路径仍为 503（auto-024 行为保持不变）
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "model_unconfigured")


class ConversationGuardAPITests(unittest.TestCase):
    """2.2: a report-production attempt in the conversation must be guided."""

    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.pop(k, None) for k in AI_ENV}
        os.environ.update({k: "stub" for k in AI_ENV})
        os.environ["AI_DATA_APPROVED"] = "1"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        import threading
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server_thread.join(timeout=5)
        cls.server.server_close()
        for k, v in cls._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def setUp(self):
        app._RATE.clear()
        app.SESSIONS.clear()

    def post(self, path: str, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_report_production_attempt_returns_guidance(self):
        stub = types.ModuleType("agent_engine")
        stub.run_agent_conversation = lambda *a, **k: {
            "answer": "报告已生成", "report_md": "# 报告", "citations": None}
        with patch.dict(sys.modules, {"agent_engine": stub}):
            status, payload = self.post("/api/question", {
                "question": "帮我写一份用户口碑分析报告", "session_id": "s-guard"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["warnings"], ["deep_analysis_guided"])
        self.assertIn("深度分析", payload["answer"])
        self.assertNotIn("报告已生成", payload["answer"])

    def test_conversation_citations_carry_refs(self):
        stub = types.ModuleType("agent_engine")
        citations = {"cited": ["F1"], "valid": ["F1"], "unknown": [],
                     "sections": [{"id": "F1", "title": "发现"}]}
        stub.run_agent_conversation = lambda *a, **k: {
            "answer": "负面占比 12.3% [F1]", "stats": [], "evidence": [],
            "applied_filters": {}, "data_version": "v", "warnings": [],
            "citations": citations}
        with patch.dict(sys.modules, {"agent_engine": stub}):
            status, payload = self.post("/api/question", {
                "question": "口碑怎么样", "session_id": "s-refs"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["citations"]["refs"],
                         [{"anchor": "F1", "report_id": "official",
                           "report_kind": "official"}])


class AskSuccessPathTests(unittest.TestCase):
    """3.1/3.3: /api/ask success paths with a stubbed QA model call."""

    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.pop(k, None) for k in AI_ENV}
        os.environ.update({k: "stub" for k in AI_ENV})
        os.environ["AI_DATA_APPROVED"] = "1"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        import threading
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server_thread.join(timeout=5)
        cls.server.server_close()
        for k, v in cls._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def setUp(self):
        app._RATE.clear()

    def post(self, path: str, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    @staticmethod
    def _qa_result(answer: str):
        return answer, {"cited": ["agent-1"], "valid": ["agent-1"], "unknown": [],
                        "sections": [{"id": "agent-1", "title": "标题"}]}

    def test_mine_report_success_returns_refs(self):
        with patch.object(app, "_call_report_qa",
                          return_value=self._qa_result("结论 [agent-1]")):
            status, payload = self.post("/api/ask", {
                "question": "总结一下",
                "report_ref": {"kind": "mine", "report_id": "r9",
                               "content": "# 标题\n正文"}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["citations"]["refs"],
                         [{"anchor": "agent-1", "report_id": "r9",
                           "report_kind": "mine"}])

    def test_official_success_returns_refs(self):
        import report_source
        sections = report_source.load_sections()
        if not sections:   # 本机无报告工件时跳过（official 内容依赖工作区文件）
            self.skipTest("official report unavailable")
        anchor = sections[0]["id"]
        with patch.object(app, "_call_report_qa",
                          return_value=(f"结论 [{anchor}]",
                                        {"cited": [anchor], "valid": [anchor],
                                         "unknown": [],
                                         "sections": [{"id": anchor, "title": ""}]})):
            status, payload = self.post("/api/ask", {
                "question": "总结一下", "report_ref": {"kind": "official"}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["citations"]["refs"][0]["report_kind"], "official")

    def test_unknown_anchor_rejects_answer(self):
        with patch.object(app, "_call_report_qa",
                          return_value=("结论 [XX99]",
                                        {"cited": ["XX99"], "valid": [],
                                         "unknown": ["XX99"], "sections": []})):
            status, payload = self.post("/api/ask", {
                "question": "总结一下",
                "report_ref": {"kind": "mine", "report_id": "r9",
                               "content": "# 标题\n正文"}})
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "citation_invalid")

class ReportHitSnippetTests(unittest.TestCase):
    """search_published_report: report_hits carry snippet + matched_terms."""

    def test_hit_snippet_centers_on_first_match(self):
        import agent_tools
        text = "开头铺垫。" + "填充" * 60 + "关键证据是续航衰减明显。" + "尾部" * 30
        snippet = agent_tools._hit_snippet(text, ["续航衰减"])
        self.assertIn("续航衰减", snippet)
        self.assertLessEqual(len(snippet), 160)
        self.assertTrue(snippet.startswith("…"))   # 命中点在正文中部，片段前带省略号

    def test_hit_snippet_without_match_returns_head(self):
        import agent_tools
        self.assertEqual(agent_tools._hit_snippet("普通正文。", []), "普通正文。")
        self.assertEqual(agent_tools._hit_snippet("", ["词"]), "")

    def test_search_tool_enriches_report_hits_and_dedupes(self):
        import agent_tools
        sections = [{"id": "F1", "title": "续航", "text": "用户反馈续航衰减明显。"},
                    {"id": "F2", "title": "充电", "text": "充电排队时间长。"}]
        context = {"report_hits": []}
        tools = {tool.name: tool for tool in
                 agent_tools.build_tools(context)}
        search = tools["search_published_report"]
        with patch.object(agent_tools.report_source, "load_sections",
                          return_value=sections):
            search.invoke({"query": "续航衰减", "limit": 3})
            search.invoke({"query": "续航衰减", "limit": 3})   # 重复检索不应重复计数
        self.assertEqual(len(context["report_hits"]), 1)
        hit = context["report_hits"][0]
        self.assertEqual(hit["id"], "F1")
        self.assertIn("续航衰减", hit["snippet"])
        self.assertIn("续航", hit["matched_terms"])


if __name__ == "__main__":
    unittest.main()
