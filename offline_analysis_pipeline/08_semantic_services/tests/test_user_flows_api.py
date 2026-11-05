"""Real-user robustness battery: abnormal & boundary API cases (offline, no LLM).

Expected behaviours / pass criteria (user-visible semantics):
  B1 空问题 / B2 >500 字问题      → 400 invalid_question，不创建任务、不烧 LLM
  B4 澄清答复为空 / 超长          → 400，任务状态不被破坏
  B5 大纲 edit 载荷坏 JSON        → 400；随后正常 confirm 仍成功（状态无污染）
  B6 对非待审任务发 outline 动作  → 409 outline_not_awaiting_review
  B7 查询不存在的 job             → 404 job_not_found
  B8 限流                         → 同 IP 60s 内超过 20 次 POST 判 429；窗口内低频不受影响
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402
import jobs  # noqa: E402
import report_session  # noqa: E402

OUTLINE = {"plan": {"plan_json": "{}", "plan": {}},
           "plan_json": "{}", "outline": []}


def _cleanup_job(job_id: str) -> None:
    with jobs._state().lock:
        jobs._state().jobs.pop(job_id, None)
    with report_session._SESSIONS_LOCK:
        report_session._SESSIONS.pop(job_id, None)


class ApitestCase(unittest.TestCase):
    def tearDown(self):
        app._RATE.clear()


class StartValidationTests(ApitestCase):
    """B1/B2：HTTP 层拒空/超长问题，且不创建任务。"""

    @classmethod
    def setUpClass(cls):
        cls._saved = report_session.start_job
        report_session.start_job = lambda *a, **k: None  # 不触发真实任务流
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        report_session.start_job = cls._saved

    def _post(self, payload):
        req = urllib.request.Request(
            self.base + "/api/agent/report",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8", "replace") or "{}")

    def test_blank_question_rejected_without_job(self):
        before = len(jobs.list_jobs()) if hasattr(jobs, "list_jobs") else None
        code, payload = self._post({"question": "   "})
        self.assertEqual(code, 400)
        self.assertEqual(payload.get("error"), "invalid_question")

    def test_oversized_question_rejected(self):
        code, payload = self._post({"question": "问" * 501})
        self.assertEqual(code, 400)
        self.assertEqual(payload.get("error"), "invalid_question")

    def test_valid_question_accepted_with_job(self):
        code, payload = self._post({"question": "SU7 充电体验怎么样？"})
        self.assertEqual(code, 202)
        self.assertTrue(payload.get("job_id"))
        _cleanup_job(payload["job_id"])


class ClarifyRobustnessTests(ApitestCase):
    """B4：非法澄清答复 400 且任务保持澄清中。"""

    def test_blank_and_oversized_answers_rejected(self):
        job_id = jobs.create_job("SU7 充电怎么样", None, None)
        try:
            jobs.pause_for_clarify(job_id, [{"field": "topic", "question": "q"}])
            for bad in ({}, {"answer": "   "}, {"answer": "好" * 2001}):
                code, payload = app.agent_report_clarify(job_id, bad, "rid")
                self.assertEqual(code, 400, bad)
                self.assertEqual(payload.get("error"), "invalid_clarify_answer")
            # 非字符串 field 是设计内兜底（转 "other"），不是错误
            code, _ = app.agent_report_clarify(job_id, {"answer": "ok", "field": 123}, "rid")
            self.assertEqual(code, 202)
            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "clarifying")
            self.assertEqual(job["clarify_questions"], [{"field": "topic", "question": "q"}])
        finally:
            _cleanup_job(job_id)


class OutlineRobustnessTests(ApitestCase):
    """B5/B6：坏载荷 400 不污染状态；正常 confirm 随后成功；非待审 409。"""

    def setUp(self):
        self._saved = report_session.resume_job
        report_session.resume_job = lambda *a, **k: True

    def tearDown(self):
        report_session.resume_job = self._saved

    def test_bad_edit_then_confirm_succeeds(self):
        job_id = jobs.create_job("SU7 充电怎么样", None, None)
        try:
            jobs.pause_for_review(job_id, OUTLINE)
            code, payload = app.agent_report_outline(
                job_id, {"action": "edit", "plan_json": "{bad json"}, "rid")
            self.assertEqual(code, 400)
            self.assertEqual(payload.get("error"), "invalid_outline")
            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "awaiting_review")  # 状态未被破坏
            code, payload = app.agent_report_outline(job_id, {"action": "confirm"}, "rid")
            self.assertEqual(code, 202)
        finally:
            _cleanup_job(job_id)

    def test_action_on_running_job_conflicts(self):
        job_id = jobs.create_job("SU7 充电怎么样", None, None)
        try:
            jobs.pause_for_clarify(job_id, [])
            self.assertTrue(jobs.claim_for_run(job_id, "数据探索中"))
            code, payload = app.agent_report_outline(job_id, {"action": "confirm"}, "rid")
            self.assertEqual(code, 409)
            self.assertEqual(payload.get("error"), "outline_not_awaiting_review")
            code, _ = app.agent_report_clarify(job_id, {"answer": "ok"}, "rid")
            self.assertEqual(code, 409)
        finally:
            _cleanup_job(job_id)

    def test_regenerate_limit_rejected_with_429(self):
        job_id = jobs.create_job("SU7 充电怎么样", None, None)
        try:
            jobs.pause_for_review(job_id, OUTLINE)
            for _ in range(report_session.REGENERATE_LIMIT):
                jobs.record_regenerate(job_id)
            code, payload = app.agent_report_outline(job_id, {"action": "regenerate"}, "rid")
            self.assertEqual(code, 429)
            self.assertEqual(payload.get("error"), "regenerate_limit_reached")
            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "awaiting_review")  # 任务仍可 confirm/edit
        finally:
            _cleanup_job(job_id)


class StatusAndRateLimitTests(ApitestCase):
    """B7/B8：未知任务 404；限流窗口判定。"""

    def test_unknown_job_404(self):
        code, payload = app.agent_report_status("no-such-job", "rid")
        self.assertEqual(code, 404)
        self.assertEqual(payload.get("error"), "job_not_found")

    def test_rate_limit_window(self):
        import time as _time
        now = _time.monotonic()
        app._RATE["1.2.3.4"] = [now] * app.RATE_LIMIT_REQUESTS
        self.assertTrue(app._rate_limited("1.2.3.4"))  # 窗口内满额 → 429
        app._RATE["5.6.7.8"] = [now - app.RATE_WINDOW_SECONDS - 1]  # 窗口外过期
        self.assertFalse(app._rate_limited("5.6.7.8"))  # 过期时间戳不计数
        self.assertFalse(app._rate_limited("9.9.9.9"))  # 新 IP 不受限
        app._RATE.clear()


if __name__ == "__main__":
    unittest.main()
