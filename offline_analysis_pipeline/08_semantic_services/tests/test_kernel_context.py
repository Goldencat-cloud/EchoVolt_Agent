"""RunContext 契约：C2（未知字段报错）与 C5（账本唯一写入口）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel.context import (Budget, BudgetExhausted, KernelContractError,
                            RunContext, Step)


class ContextSchemaTests(unittest.TestCase):
    def test_unknown_field_is_rejected_at_construction(self):
        with self.assertRaises(TypeError):
            RunContext(budget=Budget(), unknown_key=1)

    def test_required_budget_argument(self):
        with self.assertRaises(TypeError):
            RunContext()

    def test_defaults_cover_both_legacy_contexts(self):
        ctx = RunContext(budget=Budget())
        for key in ("submissions", "evidence_ids", "report_hits", "code_failures",
                    "plan", "progress", "live_context", "interactive",
                    "accepted_submission", "submit_attempts", "tool_errors",
                    "successful_tool_calls", "extras", "ledger"):
            self.assertTrue(hasattr(ctx, key), key)


class BudgetTests(unittest.TestCase):
    def test_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            Budget(tool_calls=0)

    def test_rejects_inconsistent_recursion(self):
        with self.assertRaises(ValueError):
            Budget(tool_calls=18, recursion_limit=32).check_recursion_fits()

    def test_accepts_consistent_recursion(self):
        Budget(tool_calls=14, recursion_limit=32).check_recursion_fits()

    def test_tool_call_budget_raises_when_exhausted(self):
        ctx = RunContext(budget=Budget(tool_calls=1, recursion_limit=8))
        ctx.spend_tool_call()
        with self.assertRaises(BudgetExhausted) as caught:
            ctx.spend_tool_call()
        self.assertEqual(caught.exception.kind, "tool_calls")

    def test_error_and_submit_budgets(self):
        ctx = RunContext(budget=Budget(errors=1, submits=1, recursion_limit=8))
        ctx.spend_error()
        with self.assertRaises(BudgetExhausted):
            ctx.spend_error()
        ctx.spend_submit()
        with self.assertRaises(BudgetExhausted):
            ctx.spend_submit()

    def test_code_failure_budget_counts_per_reason(self):
        ctx = RunContext(budget=Budget(code_failures=1, recursion_limit=8))
        ctx.spend_code_failure("timeout")
        with self.assertRaises(BudgetExhausted):
            ctx.spend_code_failure("timeout")
        ctx.spend_code_failure("syntax")


class LedgerTests(unittest.TestCase):
    def test_record_step_is_the_only_writer(self):
        ctx = RunContext(budget=Budget())
        ctx.record_step(Step(kind="method", aspect="可靠性", result={"rows": []}))
        self.assertEqual(len(ctx.ledger), 1)
        self.assertEqual(ctx.verified_steps[0]["kind"], "method")

    def test_verified_steps_view_is_a_copy(self):
        ctx = RunContext(budget=Budget())
        ctx.record_step(Step(kind="method", result={}))
        view = ctx.verified_steps
        view.append({"kind": "injected"})
        self.assertEqual(len(ctx.ledger), 1)

    def test_record_rejects_step_without_kind(self):
        ctx = RunContext(budget=Budget())
        with self.assertRaises(KernelContractError):
            ctx.record_step({"result": {}})


class ToolBridgeTests(unittest.TestCase):
    """迁移期字典桥：旧工具读写必须落回同一个 RunContext。"""

    def test_scalar_writes_flow_back(self):
        ctx = RunContext(budget=Budget())
        bridge = ctx.tool_context()
        bridge["successful_tool_calls"] = 3
        bridge["tool_errors"] = 1
        self.assertEqual(ctx.successful_tool_calls, 3)
        self.assertEqual(ctx.tool_errors, 1)

    def test_step_append_flows_back_to_ledger(self):
        ctx = RunContext(budget=Budget())
        bridge = ctx.tool_context()
        bridge.setdefault("verified_steps", []).append({"kind": "method", "result": {}})
        self.assertEqual(len(ctx.ledger), 1)

    def test_evidence_ids_are_shared(self):
        ctx = RunContext(budget=Budget())
        ctx.tool_context().setdefault("evidence_claim_ids", set()).update({"c-1"})
        self.assertIn("c-1", ctx.evidence_ids)

    def test_unknown_key_is_rejected(self):
        ctx = RunContext(budget=Budget())
        with self.assertRaises(KeyError):
            ctx.tool_context()["不存在的键"]

    def test_extra_keys_are_whitelisted(self):
        ctx = RunContext(budget=Budget())
        bridge = ctx.tool_context()
        bridge.setdefault("live_evidence", {})["x"] = 1
        self.assertEqual(ctx.extras["live_evidence"], {"x": 1})


class ReportGateStateTests(unittest.TestCase):
    """auto-041：交付链路的闸门状态必须是声明字段，不能靠 extras 兜底。"""

    def test_fields_default_to_empty(self):
        ctx = RunContext(budget=Budget())
        self.assertEqual(ctx.gate_rejections, 0)
        self.assertFalse(ctx.outline_approved)
        self.assertIsNone(ctx.outline_decision)

    def test_metrics_reports_real_gate_rejections(self):
        ctx = RunContext(budget=Budget())
        ctx.gate_rejections = 2
        self.assertEqual(ctx.metrics()["gate_rejections"], 2)

    def test_bridge_round_trips_gate_state(self):
        bridge = RunContext(budget=Budget()).tool_context()
        bridge["gate_rejections"] = 3
        bridge["outline_approved"] = True
        bridge["outline_decision"] = {"types": ["approve"]}
        self.assertEqual(bridge["gate_rejections"], 3)
        self.assertTrue(bridge["outline_approved"])
        self.assertEqual(bridge["outline_decision"], {"types": ["approve"]})

    def test_bridge_length_matches_iteration(self):
        """键集合与长度必须自洽，否则 dict(bridge) 与 len() 会给出不同答案。"""
        bridge = RunContext(budget=Budget()).tool_context()
        self.assertEqual(len(bridge), len(list(bridge)))


if __name__ == "__main__":
    unittest.main()
