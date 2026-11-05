"""auto-030 8.6/4.3: clarification sufficiency engine + /clarify endpoint.

Judge paths are scripted (no LLM): skip / ask-all / re-assess after reply /
failure fallback. The real LLM judge is exercised only in configured manual
acceptance.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import clarify
import config
import jobs
import report_session
import task_brief

AI_ENV = ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_DATA_APPROVED")


#: 多品牌覆盖样例：语义库只把分析对象品牌列入 brands，品牌缺口场景需显式构造。
MULTI_BRAND_COVERAGE = {
    "version": "test", "temporary": True, "snapshot_hash": "h", "built_at": "",
    "brands": [("奔驰", "EQ", 12), ("小米", "SU7", 30)],
    "date_min": "2024-01-01", "date_max": "2025-01-01",
    "scope_status": {"in_scope": 2},
}


class ClarifyAssessTests(unittest.TestCase):
    """D10 四路径：跳过 / 问全 / 答复后重评估 / 失败跳过。"""

    def test_judge_sufficient_skips(self):
        out = clarify.assess("SU7 充电排队问题的具体表现", judge=lambda **k: {"questions": []})
        self.assertFalse(out["needed"])
        self.assertEqual(out["reason"], "sufficient")

    def test_judge_gaps_asked_all_at_once(self):
        judge = lambda **k: {"questions": [  # noqa: E731
            {"field": "topic", "question": "想分析哪个方面？"},
            {"field": "compare", "question": "是否需要对比？"}]}
        out = clarify.assess("分析一下车", judge=judge)
        self.assertTrue(out["needed"])
        self.assertEqual([q["field"] for q in out["questions"]], ["topic", "compare"])

    def test_answers_forwarded_for_reassessment(self):
        seen = {}

        def judge(**kwargs):
            seen["answers"] = kwargs.get("answers")
            return {"questions": [] if kwargs["answers"] else
                    [{"field": "topic", "question": "具体哪方面？"}]}

        first = clarify.assess("分析一下车", judge=judge)
        self.assertTrue(first["needed"])
        second = clarify.assess("分析一下车", answers=[{"field": "topic",
                                                       "answer": "充电排队"}], judge=judge)
        self.assertFalse(second["needed"])
        self.assertEqual(seen["answers"], [{"field": "topic", "answer": "充电排队"}])

    def test_judge_failure_skips_when_no_deterministic_gap(self):
        def broken(**kwargs):
            raise RuntimeError("llm down")

        out = clarify.assess("SU7 充电问题", judge=broken)
        self.assertFalse(out["needed"])
        self.assertEqual(out["reason"], "clarify_judge_failed_skip")

    def test_judge_failure_still_asks_deterministic_gaps(self):
        def broken(**kwargs):
            raise RuntimeError("llm down")

        with patch.object(task_brief, "snapshot_coverage",
                          return_value=MULTI_BRAND_COVERAGE), \
                patch.object(task_brief.config, "BRAND_MULTI_ENABLED", True):
            out = clarify.assess("分析一下车", judge=broken)
        self.assertTrue(out["needed"])
        self.assertEqual(out["questions"][0]["field"], "brand")
        self.assertEqual(out["reason"], "judge_unavailable_deterministic_only")

    def test_deterministic_brand_gap_merged_with_semantic(self):
        judge = lambda **k: {"questions": [{"field": "topic", "question": "具体哪方面？"}]}  # noqa: E731
        with patch.object(task_brief, "snapshot_coverage",
                          return_value=MULTI_BRAND_COVERAGE), \
                patch.object(task_brief.config, "BRAND_MULTI_ENABLED", True):
            out = clarify.assess("分析一下车", judge=judge)
        self.assertTrue(out["needed"])
        self.assertEqual([q["field"] for q in out["questions"]], ["brand", "topic"])


class FakeGateSession:
    """Same scripted session as test_outline_gate, local copy for isolation."""

    instances: list["FakeGateSession"] = []

    def __init__(self, question, aspect=None, brief=None, progress=None):
        self.question = question
        self.brief = brief
        self.progress = progress
        self.decisions: list[dict] = []
        self.delivery_spec: dict | None = None
        FakeGateSession.instances.append(self)

    def set_delivery_spec(self, spec: dict) -> None:
        self.delivery_spec = spec

    def new_thread_id(self) -> str:
        return "thread-fake"

    def run(self, thread_id: str) -> dict:
        self.progress("数据探索中")
        return {"status": "awaiting_review",
                "plan": {"plan_json": "{}", "plan": {"workstreams": []}}}

    def resume(self, decision: dict) -> dict:
        self.decisions.append(decision)
        if decision.get("type") == "approve":
            return {"status": "done", "result": {"ok": True, "report_md": "# R"}}
        return {"status": "awaiting_review",
                "plan": {"plan_json": "{}", "plan": {"workstreams": []}}}


def _ask_once_judge(**kwargs):
    """First assessment asks one question; after any reply it is satisfied."""
    if kwargs.get("answers"):
        return {"questions": []}
    return {"questions": [{"field": "topic", "question": "具体想分析 SU7 的哪方面？"}]}


class ClarifyFlowAPITests(unittest.TestCase):
    """4.3: start → 澄清中 → /clarify → 数据探索中 → 待大纲审查."""

    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.get(k) for k in AI_ENV}
        os.environ.update({"AI_BASE_URL": "http://fake", "AI_API_KEY": "k",
                           "AI_MODEL": "m", "AI_DATA_APPROVED": "1"})
        cls._patches = [
            patch.object(report_session, "ReportSession", FakeGateSession),
            patch.object(app, "_rate_limited", lambda ip: False),
            patch.object(clarify, "_llm_judge", _ask_once_judge),
        ]
        for item in cls._patches:
            item.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        for item in cls._patches:
            item.stop()
        cls.server.shutdown()
        for key, value in cls._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def setUp(self):
        FakeGateSession.instances = []
        with jobs._state().lock:
            jobs._state().jobs.clear()

    def tearDown(self):
        with jobs._state().lock:
            jobs._state().jobs.clear()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _wait(self, job_id: str, status: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = jobs.get_job(job_id)
            if job and job.get("status") == status:
                return job
            time.sleep(0.05)
        self.fail(f"job did not reach {status}: {jobs.get_job(job_id)}")

    def test_full_clarify_round_then_outline_gate(self):
        status, payload = self._post("/api/agent/report",
                                     {"question": "分析 SU7 充电"})
        self.assertEqual(status, 202)
        job_id = payload["job_id"]
        job = self._wait(job_id, "clarifying")
        self.assertEqual(job["phase"], "澄清中")
        self.assertEqual(job["clarify_questions"][0]["field"], "topic")
        # 非法答复 → 400
        status, payload = self._post(f"/api/agent/report/{job_id}/clarify",
                                     {"answer": ""})
        self.assertEqual(status, 400)
        # 合法答复 → 后台重评估 → 数据探索 → 大纲门禁待审
        status, payload = self._post(f"/api/agent/report/{job_id}/clarify",
                                     {"answer": "充电排队与补能体验", "field": "topic"})
        self.assertEqual(status, 202)
        job = self._wait(job_id, "awaiting_review")
        phases = [e["phase"] for e in job["events"]]
        self.assertIn("澄清中", phases)
        self.assertIn("数据探索中", phases)
        self.assertLess(phases.index("澄清中"), phases.index("数据探索中"))
        self.assertEqual(job["clarifications"][0]["answer"], "充电排队与补能体验")
        self.assertEqual(job["clarify_questions"], [])
        # confirm → done
        status, _ = self._post(f"/api/agent/report/{job_id}/outline",
                               {"action": "confirm"})
        self.assertEqual(status, 202)
        self._wait(job_id, "done")

    def test_clarify_rejected_when_not_awaiting(self):
        status, payload = self._post("/api/agent/report", {"question": "分析 SU7 充电"})
        job_id = payload["job_id"]
        self._wait(job_id, "clarifying")
        # 答复后进入数据探索，再 /clarify → 409
        self._post(f"/api/agent/report/{job_id}/clarify", {"answer": "充电排队"})
        self._wait(job_id, "awaiting_review")
        status, payload = self._post(f"/api/agent/report/{job_id}/clarify",
                                     {"answer": "再来一次"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "clarify_not_awaiting")
