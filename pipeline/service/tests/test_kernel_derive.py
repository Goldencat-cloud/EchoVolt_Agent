"""派生层：字段映射唯一来源，且与既有实现同构。"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
import report_source
from research import service
from kernel.context import Budget, KernelContractError, RunContext, Step
from kernel.derive import to_answer_view, to_report_view


def _ctx(steps, *, submissions=None, report_hits=None, tool_errors=0, calls=0):
    ctx = RunContext(budget=Budget(), submissions=list(submissions or []),
                     report_hits=list(report_hits or []),
                     tool_errors=tool_errors, successful_tool_calls=calls)
    for step in steps:
        ctx.record_step(step)
    return ctx


class AnswerViewTests(unittest.TestCase):
    def test_camel_mapping_and_limits(self):
        rows = [{"aspect": "可靠性", "negative_share": 0.4, "negative": 8, "claim_id": f"c-{i}"}
                for i in range(45)]
        ctx = _ctx([Step(kind="method", aspect="可靠性", result={"rows": rows,
                                                                 "warnings": ["样本少", "样本少"]})])
        view = to_answer_view(ctx, "结论", data_version="v1")
        self.assertEqual(len(view["stats"]), 40)
        self.assertEqual(len(view["evidence"]), 20)
        self.assertEqual(view["stats"][0]["negativeShare"], 0.4)
        self.assertEqual(view["stats"][0]["negative_claims"], 8)
        self.assertEqual(view["warnings"], ["样本少"])
        self.assertEqual(view["applied_filters"], {"aspects": ["可靠性"]})

    def test_evidence_steps_only_use_data_field_when_not_live(self):
        step = Step(kind="evidence", aspect="充电",
                    result={"rows": [{"claim_id": "c-1"}], "data": [{"claim_id": "c-2"}]})
        view = to_answer_view(_ctx([step]), "x", data_version="v1")
        self.assertEqual([item["claim_id"] for item in view["evidence"]], ["c-2"])

    def test_live_mode_reads_rows(self):
        step = Step(kind="evidence", aspect="充电",
                    result={"rows": [{"claim_id": "c-1"}], "data": [{"claim_id": "c-2"}]})
        view = to_answer_view(_ctx([step]), "x", data_version="实时数据", live=True)
        self.assertEqual([item["claim_id"] for item in view["evidence"]], ["c-1"])

    def test_claim_ids_are_deduplicated_across_steps(self):
        steps = [Step(kind="evidence", result={"data": [{"claim_id": "c-1"}, {"claim_id": "c-2"}]}),
                 Step(kind="evidence", result={"data": [{"claim_id": "c-2"}]})]
        view = to_answer_view(_ctx(steps), "x", data_version="v1")
        self.assertEqual(len(view["evidence"]), 2)

    def test_non_mapping_result_is_skipped(self):
        view = to_answer_view(_ctx([Step(kind="method", result=None)]), "x", data_version="v1")
        self.assertEqual(view["stats"], [])
        self.assertEqual(view["warnings"], [])

    def test_report_hits_are_capped(self):
        hits = [{"report_id": str(i)} for i in range(12)]
        view = to_answer_view(_ctx([], report_hits=hits), "x", data_version="v1")
        self.assertEqual(len(view["report_hits"]), 8)


class ReportViewTests(unittest.TestCase):
    def test_missing_submission_raises(self):
        with self.assertRaises(KernelContractError):
            to_report_view(_ctx([]), question="q", final_message="", elapsed_ms=1)

    def test_parity_with_report_outcome_on_deterministic_fields(self):
        submission = {"report_id": "r1", "title": "可靠性分析", "report_md": "# 报告",
                      "key_findings": ["a", "b"], "status": "draft", "data_version": "v1"}
        ctx = _ctx([], submissions=[submission], tool_errors=1, calls=3)

        class Message:
            content = "最终消息"

        started = time.perf_counter() - 0.05
        legacy_context = {"submissions": [submission], "verified_steps": [],
                          "evidence_claim_ids": set(), "tool_errors": 1,
                          "successful_tool_calls": 3, "submit_attempts": 0,
                          "code_failures": {}, "plan": {}}
        legacy = agent_engine.report_outcome(legacy_context, {"messages": [Message()]},
                                             "q", started)
        kernel = to_report_view(ctx, question="q", final_message="最终消息",
                                elapsed_ms=legacy["elapsed_ms"], charts=legacy["charts"],
                                evidence_index=legacy["evidence_index"],
                                tool_log=legacy["tool_log"])
        for key in ("ok", "report_id", "title", "report_md", "key_findings",
                    "publication_status", "data_version", "final_message",
                    "tool_errors", "metrics", "elapsed_ms"):
            self.assertEqual(kernel[key], legacy[key], key)


class EquivalenceWithFixturesTests(unittest.TestCase):
    """与录制基线逐字段比对（V1 的一部分，覆盖派生层）。"""

    def test_every_fixture_matches(self):
        from tests import kernel_fixture as kf
        fixtures = kf.load_all()
        self.assertGreaterEqual(len(fixtures), 20)
        for fixture in fixtures:
            with self.subTest(case=fixture["id"]):
                expected = fixture["expected"]
                ctx = _ctx([Step(**{k: v for k, v in step.items()
                                    if k in {"kind", "aspect", "method", "result"}})
                            for step in fixture["steps"]],
                           calls=expected["successful_tool_calls"],
                           tool_errors=expected["tool_errors"])
                view = to_answer_view(
                    ctx, fixture["final_text"],
                    data_version=expected["data_version"],
                    snapshot_hash=expected["snapshot_hash"],
                    sanitizer=agent_engine._strip_unknown_citations,
                    citation_parser=report_source.parse_citations)
                self.assertEqual(view, expected)


if __name__ == "__main__":
    unittest.main()
