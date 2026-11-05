"""auto-030 8.5/4.4: outline gate wiring — jobs lifecycle + /outline endpoint.

The endpoint tests run against a scripted FakeSession (no LLM): the real
interrupt/resume mechanics are locked by test_interrupt_gate_spike.py.
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
import jobs
import report_session

AI_ENV = ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_DATA_APPROVED")

PLAN_DRAFT = json.dumps({"coverage": "c", "use_python": False,
                         "workstreams": [{"id": "w1", "question": "q"}]},
                        ensure_ascii=False)


class FakeSession:
    """Scripted stand-in for ReportSession: pause → record decision → act."""

    instances: list["FakeSession"] = []

    def __init__(self, question, aspect=None, brief=None, progress=None):
        self.question = question
        self.brief = brief
        self.progress = progress
        self.decisions: list[dict] = []
        self.runs = 0
        self.delivery_spec: dict | None = None
        FakeSession.instances.append(self)

    def set_delivery_spec(self, spec: dict) -> None:
        self.delivery_spec = spec

    def new_thread_id(self) -> str:
        return "thread-fake"

    def run(self, thread_id: str) -> dict:
        self.runs += 1
        self.progress("数据探索中")
        return {"status": "awaiting_review",
                "plan": {"plan_json": PLAN_DRAFT,
                         "plan": json.loads(PLAN_DRAFT)}}

    def resume(self, decision: dict) -> dict:
        self.decisions.append(decision)
        kind = decision.get("type")
        if kind == "approve":
            return {"status": "done", "result": {"ok": True, "report_md": "# R"}}
        if kind == "edit":
            plan_json = decision["edited_action"]["args"]["plan_json"]
            return {"status": "done",
                    "result": {"ok": True, "report_md": "# R", "plan_json": plan_json}}
        if kind == "reject":
            n = len(self.decisions)
            return {"status": "awaiting_review",
                    "plan": {"plan_json": f"draft-{n}", "plan": {}}}
        raise ValueError(f"unexpected decision {kind}")


class OutlineGateJobTests(unittest.TestCase):
    """jobs-level lifecycle: awaiting state, atomic claim, regenerate count."""

    def test_awaiting_job_does_not_occupy_active_budget(self):
        first = jobs.create_job("q1")
        second = jobs.create_job("q2")
        try:
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertIsNone(jobs.create_job("q3"))  # MAX_ACTIVE_JOBS=2 running
            jobs.pause_for_review(first, {"plan": {}})
            self.assertIsNotNone(jobs.create_job("q3"))  # awaiting frees a slot
            jobs.finish_ok("q3", {})
        finally:
            for job_id in (first, second, "q3"):
                if job_id:
                    with jobs._state().lock:
                        jobs._state().jobs.pop(job_id, None)

    def test_pause_claim_regenerate_lifecycle(self):
        job_id = jobs.create_job("q")
        try:
            jobs.pause_for_review(job_id, {"plan": {"k": 1}})
            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "awaiting_review")
            self.assertEqual(job["phase"], "待大纲审查")
            self.assertEqual(job["outline"]["plan"], {"k": 1})
            self.assertEqual(job["outline_history"], [{"plan": {"k": 1}}])
            self.assertIn("待大纲审查", [e["phase"] for e in job["events"]])
            self.assertTrue(jobs.claim_for_resume(job_id))
            self.assertFalse(jobs.claim_for_resume(job_id))  # double claim blocked
            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "running")
            self.assertEqual(jobs.record_regenerate(job_id), 1)
            self.assertEqual(jobs.record_regenerate(job_id), 2)
        finally:
            with jobs._state().lock:
                jobs._state().jobs.pop(job_id, None)

    def test_session_pending_limit_one_waiting_job(self):
        first = jobs.create_job("q1", None, "sess-1")
        try:
            self.assertIsNotNone(first)
            jobs.pause_for_clarify(first, [])
            # 同会话第二个待审 job 被拒；其他会话不受影响
            self.assertIsNone(jobs.create_job("q2", None, "sess-1"))
            second = jobs.create_job("q2", None, "sess-2")
            self.assertIsNotNone(second)
            with jobs._state().lock:
                jobs._state().jobs.pop(second, None)
        finally:
            with jobs._state().lock:
                jobs._state().jobs.clear()

    def test_global_pending_cap(self):
        created = []
        try:
            for index in range(jobs.MAX_PENDING_JOBS):
                job_id = jobs.create_job(f"q{index}", None, f"s-{index}")
                self.assertIsNotNone(job_id)
                jobs.pause_for_clarify(job_id, [])
                created.append(job_id)
            self.assertIsNone(jobs.create_job("overflow", None, "s-x"))
        finally:
            with jobs._state().lock:
                jobs._state().jobs.clear()

    def test_cleanup_ttl_layers(self):
        now = time.time()
        job_id = jobs.create_job("等待中")
        jobs.pause_for_clarify(job_id, [])  # 进入 pending 状态（等用户）
        done_id = jobs.create_job("已完成")
        jobs.finish_ok(done_id, {})
        try:
            with jobs._state().lock:
                jobs._state().jobs[done_id]["created_at"] = now - jobs.JOB_TTL_SECONDS - 1
                jobs._state().jobs[job_id]["created_at"] = now - jobs.JOB_TTL_SECONDS - 1
            jobs.cleanup()
            # 终态 job 过 JOB_TTL 回收；待审 job 用更长的 PENDING_TTL，仍保留
            self.assertIsNone(jobs.get_job(done_id))
            self.assertIsNotNone(jobs.get_job(job_id))
            with jobs._state().lock:
                jobs._state().jobs[job_id]["created_at"] = now - jobs.PENDING_TTL_SECONDS - 1
            jobs.cleanup()
            self.assertIsNone(jobs.get_job(job_id))
        finally:
            with jobs._state().lock:
                jobs._state().jobs.clear()


class OutlineGateAPITests(unittest.TestCase):
    """4.4: /api/agent/report/{id}/outline confirm|edit|regenerate paths."""

    @classmethod
    def setUpClass(cls):
        cls._saved_env = {k: os.environ.get(k) for k in AI_ENV}
        os.environ.update({"AI_BASE_URL": "http://fake", "AI_API_KEY": "k",
                           "AI_MODEL": "m", "AI_DATA_APPROVED": "1"})
        cls._patcher = patch.object(report_session, "ReportSession", FakeSession)
        cls._patcher.start()
        # 接口测试在单 IP 上快速连发，绕过演示限流器
        cls._rate_patcher = patch.object(app, "_rate_limited", lambda ip: False)
        cls._rate_patcher.start()
        # 本类专注大纲门禁：澄清判定固定为"充分"，直接进入数据探索
        cls._judge_patcher = patch.object(clarify, "_llm_judge",
                                          lambda **k: {"questions": []})
        cls._judge_patcher.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        cls._judge_patcher.stop()
        cls._rate_patcher.stop()
        cls.server.shutdown()
        for key, value in cls._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def setUp(self):
        FakeSession.instances = []
        with jobs._state().lock:
            jobs._state().jobs.clear()

    def tearDown(self):
        with jobs._state().lock:
            jobs._state().jobs.clear()

    # ---------- helpers ----------

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _start(self) -> str:
        status, payload = self._post("/api/agent/report", {"question": "分析 SU7 充电"})
        self.assertEqual(status, 202)
        return payload["job_id"]

    def _wait(self, job_id: str, status: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = jobs.get_job(job_id)
            if job and job.get("status") == status:
                return job
            time.sleep(0.05)
        self.fail(f"job {job_id} did not reach {status}: "
                  f"{jobs.get_job(job_id)}")

    # ---------- tests ----------

    def test_start_pauses_at_gate_with_outline_and_no_execution(self):
        job_id = self._start()
        job = self._wait(job_id, "awaiting_review")
        self.assertEqual(job["phase"], "待大纲审查")
        self.assertEqual(job["outline"]["plan_json"], PLAN_DRAFT)
        self.assertIn("workstreams", job["outline"]["plan"]["plan"])
        phases = [e["phase"] for e in job["events"]]
        self.assertIn("待大纲审查", phases)
        # 门禁未通过：不得出现任何执行阶段事件
        self.assertNotIn("编写分析代码中", phases)
        self.assertNotIn("沙箱执行中", phases)

    def test_confirm_approves_and_completes(self):
        job_id = self._start()
        self._wait(job_id, "awaiting_review")
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "confirm"})
        self.assertEqual(status, 202)
        job = self._wait(job_id, "done")
        self.assertTrue(job["result"]["ok"])
        session = FakeSession.instances[0]
        self.assertEqual(session.decisions, [{"type": "approve"}])
        # 完成后再审查 → 409
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "confirm"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "outline_not_awaiting_review")

    def test_edit_submits_new_plan_and_completes(self):
        job_id = self._start()
        self._wait(job_id, "awaiting_review")
        edited = json.dumps({"coverage": "edited", "use_python": False, "workstreams": [
            {"id": "w1", "question": "编辑后的子问题", "dimension": "aspect",
             "aspect": "充电与补能", "method": "top_negative_claims",
             "requires_evidence": False}]}, ensure_ascii=False)
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "edit", "plan_json": edited})
        self.assertEqual(status, 202)
        job = self._wait(job_id, "done")
        self.assertEqual(job["result"]["plan_json"], edited)
        session = FakeSession.instances[0]
        self.assertEqual(session.decisions[0]["type"], "edit")
        self.assertEqual(session.decisions[0]["edited_action"]["name"],
                         "submit_analysis_plan")

    def test_edit_rejects_invalid_plan_json(self):
        job_id = self._start()
        self._wait(job_id, "awaiting_review")
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "edit", "plan_json": ""})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_outline")

    def test_confirm_carries_delivery_spec_into_execution_context(self):
        # 8.10/D12：重点/受众随 confirm 进入执行上下文并持久化到 job
        job_id = self._start()
        self._wait(job_id, "awaiting_review")
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "confirm",
                                      "focus": "充电排队与补能",
                                      "audience": "售后负责人"})
        self.assertEqual(status, 202)
        job = self._wait(job_id, "done")
        self.assertEqual(job["delivery_spec"],
                         {"focus": "充电排队与补能", "audience": "售后负责人"})
        self.assertEqual(FakeSession.instances[0].delivery_spec,
                         {"focus": "充电排队与补能", "audience": "售后负责人"})

    def test_regenerate_up_to_limit_then_rejected(self):
        job_id = self._start()
        for round_no in range(report_session.REGENERATE_LIMIT):
            self._wait(job_id, "awaiting_review")
            status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                         {"action": "regenerate",
                                          "feedback": f"第{round_no + 1}次反馈"})
            self.assertEqual(status, 202)
        # 上限内最后一次 regenerate 回到待审（新草案）
        job = self._wait(job_id, "awaiting_review")
        self.assertEqual(job["regenerates"], report_session.REGENERATE_LIMIT)
        self.assertEqual(
            [d["type"] for d in FakeSession.instances[0].decisions],
            ["reject"] * report_session.REGENERATE_LIMIT)
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "regenerate"})
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "regenerate_limit_reached")

    def test_invalid_action_rejected(self):
        job_id = self._start()
        self._wait(job_id, "awaiting_review")
        status, payload = self._post(f"/api/agent/report/{job_id}/outline",
                                     {"action": "delete"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_outline_action")

    def test_unknown_job_404(self):
        status, payload = self._post("/api/agent/report/no-such-job/outline",
                                     {"action": "confirm"})
        self.assertEqual(status, 404)

    # ---------- 4.1: brief validation at the start endpoint ----------

    def test_start_rejects_brief_without_topic(self):
        status, payload = self._post("/api/agent/report",
                                     {"question": "分析 SU7 充电", "brief": {"brand": "小米"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_brief")

    def test_start_rejects_out_of_range_time_window(self):
        status, payload = self._post("/api/agent/report", {
            "question": "分析 SU7 充电",
            "brief": {"topic": "充电", "time_window": "1999-01-01 ~ 1999-12-31"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "time_window_out_of_range")
        self.assertIn("allowed_time_window", payload)

    def test_start_accepts_valid_brief(self):
        import task_brief
        coverage = task_brief.snapshot_coverage()
        window = f"{coverage['date_min'][:10]} ~ {coverage['date_max'][:10]}"
        status, payload = self._post("/api/agent/report", {
            "question": "分析 SU7 充电",
            "brief": {"topic": "充电体验", "brand": "小米/SU7", "time_window": window}})
        self.assertEqual(status, 202)
        job = self._wait(payload["job_id"], "awaiting_review")
        self.assertTrue(job["outline"]["plan"])


if __name__ == "__main__":
    unittest.main()

