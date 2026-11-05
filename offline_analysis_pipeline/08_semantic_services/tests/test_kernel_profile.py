"""Profile 契约：C3（工具必须登记）与 C4（预算与递归自洽）。"""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel import registry
from kernel.context import Budget
from kernel.profile import (DELIVERABLE, INTERACTIVE, MIDDLEWARE_PLAN_GATE,
                            PROFILES, Profile, get)


class BuiltinProfileTests(unittest.TestCase):
    def test_two_profiles_are_registered(self):
        self.assertEqual(set(PROFILES), {"interactive", "deliverable"})
        self.assertIs(get("interactive"), INTERACTIVE)
        self.assertIs(get("deliverable"), DELIVERABLE)

    def test_interactive_shape(self):
        self.assertEqual(INTERACTIVE.artifact, "answer")
        self.assertEqual(INTERACTIVE.failure, "retryable")
        self.assertFalse(INTERACTIVE.requires_approval)
        self.assertEqual(INTERACTIVE.skills, ())
        self.assertFalse(INTERACTIVE.allows("python_analyze"))
        self.assertFalse(INTERACTIVE.allows("submit_report"))
        self.assertTrue(INTERACTIVE.allows("run_semantic_aggregate"))

    def test_deliverable_shape(self):
        self.assertEqual(DELIVERABLE.artifact, "report")
        self.assertEqual(DELIVERABLE.failure, "terminal")
        self.assertTrue(DELIVERABLE.requires_approval)
        # auto-042 7.2：阶段技能全部显式声明，注入集合由声明决定。
        self.assertEqual(DELIVERABLE.skills,
                         ("deep-analysis", "plan-drafting", "execute-plan", "report-authoring"))
        self.assertEqual(set(DELIVERABLE.tools), set(registry.TOOLS))

    def test_budgets_are_self_consistent(self):
        for profile in PROFILES.values():
            profile.budget.check_recursion_fits()

    def test_interactive_budget_matches_effective_recursion_limit(self):
        """现状递归 32 节点、每轮 ≥2 节点，实际可达 14 次工具调用。"""
        self.assertEqual(INTERACTIVE.budget.recursion_limit, 32)
        self.assertEqual(INTERACTIVE.budget.tool_calls, 14)


class ValidationTests(unittest.TestCase):
    def test_unknown_tool_in_whitelist_is_rejected(self):
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset({"nope"}), budget=Budget(),
                    artifact="answer", failure="retryable", timeout_s=10)

    def test_inconsistent_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset(), budget=Budget(tool_calls=18, recursion_limit=32),
                    artifact="answer", failure="retryable", timeout_s=10)

    def test_report_profile_requires_gate(self):
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset(), budget=Budget(), artifact="report",
                    failure="terminal", timeout_s=10)

    def test_answer_profile_must_not_require_gate(self):
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset(), budget=Budget(), artifact="answer",
                    failure="retryable", timeout_s=10,
                    middleware=(MIDDLEWARE_PLAN_GATE,))

    def test_invalid_artifact_and_failure_values(self):
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset(), budget=Budget(), artifact="other",
                    failure="retryable", timeout_s=10)
        with self.assertRaises(ValueError):
            Profile(name="x", tools=frozenset(), budget=Budget(), artifact="answer",
                    failure="sometimes", timeout_s=10)

    def test_unknown_profile_name(self):
        with self.assertRaises(ValueError):
            get("nope")

    def test_profile_is_immutable(self):
        with self.assertRaises(Exception):
            INTERACTIVE.name = "hacked"   # type: ignore[misc]

    def test_derived_profile_can_be_constructed(self):
        variant = replace(INTERACTIVE, name="interactive-tight",
                          budget=Budget(tool_calls=8, recursion_limit=24))
        self.assertEqual(variant.name, "interactive-tight")
        self.assertEqual(variant.artifact, "answer")


if __name__ == "__main__":
    unittest.main()
