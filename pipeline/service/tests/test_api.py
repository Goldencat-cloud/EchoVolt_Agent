"""HTTP API tests for the AutoInsight MVP service (no LLM configured)."""
import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import routes  # noqa: E402  协议层常量（MAX_BODY）在此定义，patch 定义处才对 Handler 生效
import orchestrator  # noqa: E402  编排层函数（model_configured/question_core）在此定义

AI_ENV = ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_DATA_APPROVED")


class APITests(unittest.TestCase):
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
        cls.server_thread.join(timeout=5)   # let the loop exit before closing sockets
        cls.server.server_close()
        for k, v in cls._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def setUp(self):
        app._RATE.clear()
        app.SESSIONS.clear()

    # helpers -------------------------------------------------------------
    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = raw
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8")), dict(e.headers)

    def post(self, path: str, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # tests ---------------------------------------------------------------
    def test_health_ok_without_model(self):
        status, payload, _ = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["data_version"])

    def test_stats_and_claims_return_versioned_envelope(self):
        status, stats, _ = self.get("/api/stats?aspect=" + urllib.request.quote("空间与舒适性"))
        self.assertEqual(status, 200)
        self.assertIn("data_version", stats)
        status, claims, _ = self.get("/api/claims?aspect=" + urllib.request.quote("空间与舒适性") + "&limit=3")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(claims["data"]), 3)

    def test_public_caliber_avoids_internal_terms(self):
        # auto-042：旧问答链移除后，"对外文案不泄露内部术语"由统计信封与报告门禁共同承担。
        status, stats, _ = self.get("/api/stats?aspect=" + urllib.request.quote("空间与舒适性"))
        self.assertEqual(status, 200)
        public_text = json.dumps(stats, ensure_ascii=False)
        for internal in ("声明级", "工具返回", "确定性查询结果", "工作项"):
            self.assertNotIn(internal, public_text)
        self.assertTrue(stats.get("caliber"))
        self.assertIn("观点", public_text)

    def test_invalid_filter_returns_400(self):
        status, payload, _ = self.get("/api/stats?aspect=" + urllib.request.quote("不存在议题"))
        self.assertEqual(status, 400)
        self.assertIn("request_id", payload)

    def test_question_rejects_bad_question(self):
        status, _ = self.post("/api/question", {"question": "   "})
        self.assertEqual(status, 400)
        status, _ = self.post("/api/question", {"question": "x" * 501})
        self.assertEqual(status, 400)
        status, _ = self.post("/api/question", {"question": "汽车怎么样", "session_id": "s" * 65})
        self.assertEqual(status, 400)

    def test_question_rejects_oversized_body(self):
        # auto-030 将 MAX_BODY 提升至 512KB 以承载整份报告上传；用小阈值 patch 验证 413 路径
        with patch.object(routes, "MAX_BODY", 4096):
            status, _ = self.post("/api/question", {"question": "问" * 4000})
        self.assertEqual(status, 413)

    def test_analyze_endpoint_is_gone(self):
        """auto-042：/api/analyze 已移除，必须返回 404 且不返回任何统计结果。"""
        status, payload = self.post("/api/analyze", {"question": "空间与舒适性有哪些负向体验？"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not_found")
        self.assertNotIn("stats", payload)
        self.assertNotIn("answer", payload)

    def test_unknown_path_returns_404(self):
        """auto-042：端点集合是封闭的，未列出的路径不得落入任何处理器。"""
        status, payload, _ = self.get("/api/does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not_found")
        status, payload = self.post("/api/does-not-exist", {"question": "空间与舒适性"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not_found")

    def test_rate_limit_returns_429(self):
        statuses = []
        for _ in range(app.RATE_LIMIT_REQUESTS + 1):
            status, _ = self.post("/api/question", {"question": "空间与舒适性有哪些负向体验？"})
            statuses.append(status)
        self.assertEqual(statuses[-1], 429)

    def test_greeting_uses_agent_without_route_classifier(self):
        with patch.object(orchestrator, "model_configured", return_value=True), \
                patch("agent_engine.run_agent_conversation", return_value={
                    "answer": "你好，今天想先聊哪类用车体验？", "stats": [], "evidence": []
                }) as run_agent:
            status, payload = self.post("/api/question", {"question": "你好"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["answer"], "你好，今天想先聊哪类用车体验？")
        self.assertEqual(payload["response_type"], "conversation")
        self.assertNotIn("intent", payload)
        run_agent.assert_called_once()

    def test_provenance_followup_keeps_previous_result_in_session(self):
        responses = [
            {"answer": "空间舒适性负面观点占比是 43.4%。", "stats": [{"aspect": "空间与舒适性", "negativeShare": .434}], "evidence": []},
            {"answer": "按负面观点条数除以该议题全部观点条数计算。", "stats": [], "evidence": []},
        ]
        received = []
        def respond(question, history=None, session=None):
            received.append((question, list(history or []), dict(session or {})))
            return responses.pop(0)
        with patch.object(orchestrator, "model_configured", return_value=True), \
                patch("agent_engine.run_agent_conversation", side_effect=respond):
            self.post("/api/question", {"question": "空间与舒适性负面反馈占比是多少？", "session_id": "followup"})
            status, payload = self.post("/api/question", {"question": "你怎么得到这个结果的？", "session_id": "followup"})
        self.assertEqual(status, 200)
        self.assertIn("观点条数", payload["answer"])
        self.assertEqual(received[1][0], "你怎么得到这个结果的？")
        self.assertEqual(received[1][2]["last_result"]["stats"][0]["aspect"], "空间与舒适性")
        self.assertEqual(len(received[1][1]), 2)

    def test_all_turns_use_contextual_agent_and_agent_error_is_explicit(self):
        with patch.object(orchestrator, "model_configured", return_value=True), \
                patch("agent_engine.run_agent_conversation", side_effect=TimeoutError):
            status, payload = self.post("/api/question", {"question": "明天天气怎么样？"})
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "agent_unavailable")
        self.assertIn("对话模型", payload["message"])
        self.assertNotIn("answer", payload)

    def test_question_unavailable_without_model_does_not_return_scripted_reply(self):
        status, payload = self.post("/api/question", {"question": "你好"})
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "model_unconfigured")
        self.assertNotIn("answer", payload)

    def test_agent_report_unconfigured_returns_503(self):
        status, payload = self.post("/api/agent/report", {"question": "可靠性怎么样？"})
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "model_unconfigured")

    def test_ask_unavailable_without_published_report_or_model(self):
        status, payload = self.post("/api/ask", {"question": "报告里舒适性占比是多少"})
        self.assertEqual(status, 503)
        self.assertIn("error", payload)
        self.assertIn("request_id", payload)

    def test_unknown_path_404_and_ask_get_405(self):
        status, _, _ = self.get("/api/nope")
        self.assertEqual(status, 404)
        status, _, _ = self.get("/api/ask")
        self.assertEqual(status, 405)

    def test_internal_error_returns_500_with_request_id(self):
        original = app.service.query_stats

        def boom(*a, **k):
            raise RuntimeError("snapshot backend exploded")

        app.service.query_stats = boom
        try:
            status, payload, _ = self.get("/api/stats?aspect=" + urllib.request.quote("空间与舒适性"))
        finally:
            app.service.query_stats = original
        self.assertEqual(status, 500)
        self.assertNotIn("exploded", json.dumps(payload))
        self.assertIn("request_id", payload)

    def test_session_stores_turn_history_without_intent_route(self):
        with patch.object(orchestrator, "model_configured", return_value=True), \
                patch("agent_engine.run_agent_conversation", return_value={
                    "answer": "我先查看空间反馈。", "stats": [], "evidence": []
                }):
            self.post("/api/question", {"question": "空间与舒适性如何？", "session_id": "chat-history"})
        record = app.SESSIONS["chat-history"]
        self.assertEqual(record["history"][0], {"role": "user", "content": "空间与舒适性如何？"})
        self.assertNotIn("last_intent", record)

    def test_design_tokens_served(self):
        status, body, headers = self.get("/static/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertIn("--accent-500", body)

    def test_suggestions_are_derived_from_report_and_snapshot(self):
        status, payload, _ = self.get("/api/suggestions")
        self.assertEqual(status, 200)
        items = payload["suggestions"]
        self.assertTrue(items)
        kinds = {item["kind"] for item in items}
        self.assertIn("data", kinds)
        for item in items:
            self.assertTrue(item["text"].strip())

    def test_legacy_report_served(self):
        status, body, headers = self.get("/report/full")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("用户声音分析报告", body)
        self.assertIn("/static/report-skin.css", body)
        self.assertIn("AutoInsight · 新能源洞察工作台", body)

    def test_published_report_receives_same_brand_skin(self):
        from unittest.mock import patch
        with patch.object(app.report_publisher, "render_published_html",
                          return_value="<html><head></head><body>published</body></html>"):
            status, body, _ = self.get("/report/full")
        self.assertEqual(status, 200)
        self.assertIn("/static/report-skin.css", body)
        self.assertIn("研究报告 · 已审核发布", body)

    def test_static_index_served(self):
        status, body, headers = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        # Auto-029：侧栏三分区（官方报告 / 我的报告 / 短线分割 / 对话历史），入口不嵌报告列表
        self.assertIn('id="sidebar"', body)
        self.assertIn('data-nav="official"', body)
        self.assertIn('data-nav="library"', body)
        self.assertIn('nav-divider', body)
        self.assertIn('id="session-list"', body)
        self.assertIn("对话历史", body)
        self.assertIn("官方报告", body)
        self.assertIn("我的报告", body)
        self.assertNotIn('id="splitter"', body)
        self.assertNotIn('class="pane-switch"', body)
        self.assertNotIn('class="doc-tabs"', body)
        self.assertNotIn('role="tablist"', body)
        self.assertIn("研究报告", body)


if __name__ == "__main__":
    unittest.main()
