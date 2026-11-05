"""任务状态容器的契约：注入的 store 相互隔离，状态推进只有一条路径。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jobs


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = jobs.JobStore()
        jobs.configure(self.store)

    def tearDown(self):
        jobs.configure(jobs.JobStore())

    def test_created_job_lives_in_the_injected_store(self):
        job_id = jobs.create_job("问题")
        self.assertIn(job_id, self.store.jobs)
        self.assertEqual(jobs.get_job(job_id)["status"], "running")

    def test_replacing_the_store_isolates_state(self):
        job_id = jobs.create_job("问题")
        jobs.configure(jobs.JobStore())
        self.assertIsNone(jobs.get_job(job_id))

    def test_phase_transitions_record_one_event_each(self):
        job_id = jobs.create_job("问题")
        jobs.pause_for_clarify(job_id, [{"question": "?"}])
        self.assertTrue(jobs.claim_for_run(job_id))
        phases = [event["phase"] for event in jobs.get_job(job_id)["events"]]
        self.assertEqual(phases, ["澄清中", "澄清中", "数据探索中"])

    def test_claim_is_rejected_in_the_wrong_state(self):
        job_id = jobs.create_job("问题")
        self.assertFalse(jobs.claim_for_resume(job_id))

    def test_snapshot_hides_question_and_timestamps(self):
        snapshot = jobs.get_job(jobs.create_job("敏感问题"))
        self.assertNotIn("question", snapshot)
        self.assertNotIn("created_at", snapshot)

    def test_missing_job_is_tolerated(self):
        self.assertIsNone(jobs.get_job("no-such-job"))
        self.assertEqual(jobs.record_regenerate("no-such-job"), 0)
        self.assertFalse(jobs.claim_for_run("no-such-job"))


if __name__ == "__main__":
    unittest.main()
