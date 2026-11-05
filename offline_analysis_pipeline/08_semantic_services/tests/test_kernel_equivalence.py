"""V1 端到端等价：同一 fixture 驱动新内核，逐字段比对旧实现录制的响应。

覆盖链路：RunContext 装配 → 工具白名单 → agent 调用 → 账本 → 派生 → Outcome。
模型调用由 fixture 的账本条目替代，不触网、不依赖冻结快照数据。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
import report_source
from research import service
from kernel.context import Budget, RunContext, Step
from kernel.derive import to_answer_view
from kernel.profile import INTERACTIVE
from kernel.runner import STATUS_DONE, KernelRunner, TurnRequest
from tests import kernel_fixture as kf


class _ReplayAgent:
    """把 fixture 的账本条目写回同一个 RunContext，返回固定最终文本。"""

    def __init__(self, ctx, steps, final_text):
        self._ctx = ctx
        self._steps = steps
        self._final_text = final_text
        self.calls = 0

    def invoke(self, payload, config):
        self.calls += 1
        for step in self._steps:
            self._ctx.record_step(Step(**{k: v for k, v in step.items()
                                          if k in {"kind", "aspect", "method", "result"}}))
            self._ctx.successful_tool_calls += 1
        return {"final_text": self._final_text}


class EquivalenceTests(unittest.TestCase):
    maxDiff = None

    def test_fixtures_exist_and_cover_both_shapes(self):
        fixtures = kf.load_all()
        self.assertGreaterEqual(len(fixtures), 20)
        with_steps = [f for f in fixtures if f["steps"]]
        without = [f for f in fixtures if not f["steps"]]
        self.assertTrue(with_steps and without,
                        "fixture 必须同时覆盖有工具与无工具两类输入")

    def test_full_response_matches_legacy(self):
        for fixture in kf.load_all():
            with self.subTest(case=fixture["id"]):
                ctx = RunContext(budget=INTERACTIVE.budget)
                agent = _ReplayAgent(ctx, fixture["steps"], fixture["final_text"])
                expected = fixture["expected"]

                def view_factory(state):
                    return to_answer_view(
                        ctx, state["final_text"],
                        data_version=expected["data_version"],
                        snapshot_hash=expected["snapshot_hash"],
                        sanitizer=agent_engine._strip_unknown_citations,
                        citation_parser=report_source.parse_citations)

                runner = KernelRunner(INTERACTIVE, ctx, agent=agent,
                                      view_factory=view_factory)
                outcome = runner.run(TurnRequest(messages=[{"role": "user",
                                                           "content": fixture["input"]["question"]}]))
                self.assertEqual(outcome.status, STATUS_DONE)
                self.assertEqual(outcome.view, expected,
                                 f"{fixture['id']} 视图与旧实现不一致")
                self.assertEqual(outcome.metrics["successful_tool_calls"],
                                 expected["successful_tool_calls"])

    def test_tool_whitelist_matches_legacy_exclusion(self):
        """白名单结果必须与旧的排除名单等价（7 个工具）。"""
        import agent_tools
        legacy = {tool.name for tool in agent_tools.build_tools({})}
        legacy_expanded = legacy - set(kf.LEGACY_CONVERSATION_EXCLUDED_TOOLS)
        self.assertEqual(set(INTERACTIVE.tools), legacy_expanded)

    def test_fixture_metadata_is_honest(self):
        """fixture 必须标注来源，避免把构造数据当成真实录制。"""
        for fixture in kf.load_all():
            self.assertIn(fixture["source"], {"synthetic", "live"})
            if fixture["source"] == "synthetic":
                self.assertTrue(fixture["note"], fixture["id"])


if __name__ == "__main__":
    unittest.main()
