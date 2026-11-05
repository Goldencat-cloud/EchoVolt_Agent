"""Unit tests for the async job store (progress events + failure surfacing)."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jobs


class JobsTests(unittest.TestCase):
    def test_lifecycle_phases_and_result(self):
        job_id = jobs.create_job("测试问题")
        jobs.set_phase(job_id, "沙箱执行中")
        jobs.finish_ok(job_id, {"report_md": "# 报告"})
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["phase"], "已完成")
        phases = [e["phase"] for e in job["events"]]
        self.assertEqual(phases, ["澄清中", "沙箱执行中", "已完成"])
        self.assertEqual(job["result"]["report_md"], "# 报告")

    def test_failure_is_surfaced_not_swallowed(self):
        job_id = jobs.create_job("会失败的问题")
        jobs.finish_error(job_id, {"error": "ValueError: boom"})
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("boom", job["error"]["error"])

    def test_run_async_records_outcome(self):
        job_id = jobs.create_job("异步问题")

        def work(set_phase):
            set_phase("撰写报告中")
            return {"report_md": "# ok"}

        jobs.run_async(job_id, work)
        deadline = time.time() + 5
        while time.time() < deadline:
            job = jobs.get_job(job_id)
            if job["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(jobs.get_job(job_id)["status"], "done")

    def test_run_async_captures_failure(self):
        job_id = jobs.create_job("异步失败")

        def work(set_phase):
            raise RuntimeError("agent died")

        jobs.run_async(job_id, work)
        deadline = time.time() + 5
        while time.time() < deadline:
            job = jobs.get_job(job_id)
            if job["status"] == "failed":
                break
            time.sleep(0.05)
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("agent died", job["error"]["error"])

    def test_unknown_job_returns_none(self):
        self.assertIsNone(jobs.get_job("nope"))


if __name__ == "__main__":
    unittest.main()
