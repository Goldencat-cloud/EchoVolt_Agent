"""接线断言（auto-040）：交互链路用的是同一个内核状态、白名单与派生入口。

这些断言只覆盖"接线是否等价"，不覆盖统计正确性：模型调用与工具产物由替身替换，
不触网、不依赖冻结快照数据。
"""
import dataclasses
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
import agent_tools
from research import service
from kernel.context import EXTRA_KEYS, Budget, RunContext
from kernel.profile import INTERACTIVE
from tests import kernel_fixture as kf

#: 接线前 `_run_agent_conversation` 内联的上下文键（auto-040 之前的 dict 字面量）。
#: 工具侧只能看到这些键，少一个就是静默降级。
LEGACY_CONTEXT_KEYS = frozenset({
    "submissions", "code_failures", "interactive", "verified_steps",
    "evidence_claim_ids", "submit_attempts", "accepted_submission",
    "tool_errors", "successful_tool_calls", "report_hits", "live_context",
})


class _Message:
    """最小消息替身：`report_outcome` 只读 `.content`。"""

    def __init__(self, content: str) -> None:
        self.content = content


class ContextBridgeTests(unittest.TestCase):
    """1.1：`ToolContext` 必须覆盖旧 dict 的全部键。"""

    def test_bridge_covers_every_legacy_key(self):
        keys = set(RunContext(budget=Budget()).tool_context())
        self.assertEqual(LEGACY_CONTEXT_KEYS - keys, set())

    def test_bridge_exposes_report_gate_keys(self):
        """auto-041：交付链路的工具会读写这三个键，未登记就是 KeyError。"""
        bridge = RunContext(budget=Budget()).tool_context()
        for key in ("gate_rejections", "outline_approved", "outline_decision"):
            self.assertIn(key, bridge)
        bridge["gate_rejections"] = bridge["gate_rejections"] + 1
        self.assertEqual(bridge["gate_rejections"], 1)

    def test_bridge_exposes_no_undeclared_key(self):
        """键集合只能来自 RunContext 字段、两个历史别名与 extras 白名单。"""
        declared = {field.name for field in dataclasses.fields(RunContext)}
        declared |= {"verified_steps", "evidence_claim_ids"}
        keys = set(RunContext(budget=Budget()).tool_context())
        self.assertEqual(keys - declared - set(EXTRA_KEYS), set())


class ToolWhitelistTests(unittest.TestCase):
    """1.2：白名单过滤结果必须与旧排除名单的补集完全相等。"""

    def test_wired_filter_equals_legacy_exclusion(self):
        built = [tool.name for tool in agent_tools.build_tools({})]
        legacy = set(built) - set(kf.LEGACY_CONVERSATION_EXCLUDED_TOOLS)
        wired = {name for name in built if INTERACTIVE.allows(name)}
        self.assertEqual(wired, legacy)

    def test_conversation_excludes_compute_and_submit(self):
        wired = {tool.name for tool in agent_tools.build_tools({})
                 if INTERACTIVE.allows(tool.name)}
        self.assertNotIn("python_analyze", wired)
        self.assertNotIn("submit_report", wired)


class LiveSwitchTests(unittest.TestCase):
    """1.3：实时/快照两条分支传入派生层的参数必须与旧返回逐键一致。"""

    def test_snapshot_mode_has_no_source_mode(self):
        with kf.old_implementation([], "结论") as view:
            self.assertNotIn("source_mode", view)
            self.assertEqual(view["data_version"], service.snapshot_version())
            self.assertEqual(view["snapshot_hash"], service.snapshot_hash())

    # auto-042：实时管道退役后，live 模式的派生断言随实现一并移除；
    # 快照模式仍由 test_snapshot_mode_has_no_source_mode 覆盖。


class AppliedFilterTests(unittest.TestCase):
    """历史会话里的旧筛选只供模型参考，不得被渲染成"当前筛选"。"""

    SESSION = {"filters": {"aspect": "口碑"},
               "last_result": {"answer": "上次看的是口碑"}}
    HISTORY = [{"role": "user", "content": "看看口碑"},
               {"role": "assistant", "content": "已按口碑筛选"}]

    def test_history_filter_does_not_leak(self):
        steps = [{"kind": "method", "aspect": "价格", "result": {"rows": []}}]
        with kf.old_implementation(steps, "结论", history=self.HISTORY,
                                   session=self.SESSION) as view:
            self.assertEqual(view["applied_filters"], {"aspects": ["价格"]})

    def test_no_method_step_means_no_filter(self):
        steps = [{"kind": "overview", "aspect": "口碑", "result": {"rows": []}}]
        with kf.old_implementation(steps, "结论", history=self.HISTORY,
                                   session=self.SESSION) as view:
            self.assertEqual(view["applied_filters"], {"aspects": []})

    def test_repeated_aspect_is_deduplicated(self):
        steps = [{"kind": "method", "aspect": "价格", "result": {"rows": []}},
                 {"kind": "method", "aspect": "价格", "result": {"rows": []}}]
        with kf.old_implementation(steps, "结论") as view:
            self.assertEqual(view["applied_filters"], {"aspects": ["价格"]})


class ReportOutcomeWiringTests(unittest.TestCase):
    """auto-041：报告组装的入参兼容、错误语义与视图同源。"""

    SUBMISSION = {"report_id": "r1", "title": "可靠性分析", "report_md": "# 报告",
                  "key_findings": ["a"], "status": "draft", "data_version": "v1"}

    def _state(self):
        return {"messages": [_Message("最终消息")]}

    def test_mapping_and_context_produce_same_view(self):
        """旧的 dict 入参必须与新状态对象产出同一视图（D4 的兼容承诺）。"""
        from kernel.context import RunContext
        from kernel.profile import DELIVERABLE

        ctx = RunContext(budget=DELIVERABLE.budget,
                         submissions=[dict(self.SUBMISSION)])
        legacy = {"submissions": [dict(self.SUBMISSION)]}
        started = time.perf_counter()
        from_ctx = agent_engine.report_outcome(ctx, self._state(), "问题", started)
        from_mapping = agent_engine.report_outcome(legacy, self._state(), "问题", started)
        for key in ("ok", "report_id", "title", "report_md", "key_findings",
                    "publication_status", "data_version", "final_message",
                    "tool_errors", "metrics", "charts", "evidence_index", "tool_log"):
            self.assertEqual(from_ctx[key], from_mapping[key], key)

    def test_missing_submission_keeps_tool_log_in_message(self):
        """缺提交时的错误信息仍要带最近工具调用，否则排查没有线索（D5）。"""
        message = type("ToolMessage", (), {})()
        message.name = "run_analysis_method"
        message.content = "结果"
        with self.assertRaises(RuntimeError) as caught:
            agent_engine.report_outcome({}, {"messages": [message]}, "问题", 0.0)
        self.assertIn("最近工具调用", str(caught.exception))
        self.assertIn("run_analysis_method", str(caught.exception))

    def test_to_report_view_error_is_runtime_error(self):
        """内核错误必须是 RuntimeError 子类，否则既有 except 分支会漏掉。"""
        from kernel.context import RunContext
        from kernel.derive import to_report_view
        from kernel.profile import DELIVERABLE

        with self.assertRaises(RuntimeError):
            to_report_view(RunContext(budget=DELIVERABLE.budget), question="q",
                           final_message="", elapsed_ms=1)


class ReportSessionGateStateTests(unittest.TestCase):
    """auto-041：审批结果只落在 RunContext 上，清除用置空而非删键。"""

    def _session(self):
        from kernel.context import RunContext
        from kernel.profile import DELIVERABLE
        from report_session import ReportSession

        session = ReportSession("问题")
        session._context = RunContext(budget=DELIVERABLE.budget)
        return session

    def test_approve_records_decision(self):
        session = self._session()
        session._record_outline_decision([{"type": "approve"}])
        self.assertTrue(session._context.outline_approved)
        decision = session._context.tool_context().get("outline_decision")
        self.assertEqual(decision["types"], ["approve"])

    def test_edit_counts_as_approval(self):
        session = self._session()
        session._record_outline_decision([{"type": "edit"}])
        self.assertTrue(session._context.outline_approved)

    def test_reject_clears_decision_to_none(self):
        session = self._session()
        session._record_outline_decision([{"type": "approve"}])
        session._record_outline_decision([{"type": "reject"}])
        self.assertFalse(session._context.outline_approved)
        # 置 None 与旧实现的删键，在工具侧的 .get() 上等价
        self.assertIsNone(session._context.tool_context().get("outline_decision"))


class BuildRunnerInjectionTests(unittest.TestCase):
    """auto-042 8.1：`build_runner` 必须透传交付链的三个注入点。

    真实冒烟暴露过：`ReportSession` 传 `config_factory` 而 builder 未声明该参数，
    构造期直接 `TypeError`；替身测试因绕过 `_ensure_runner` 未发现。
    """

    def setUp(self):
        from kernel import builder
        from kernel.context import RunContext
        from kernel.profile import DELIVERABLE

        self.builder = builder
        self.ctx = RunContext(budget=DELIVERABLE.budget)
        self.profile = DELIVERABLE

    def test_injection_points_reach_kernel_runner(self):
        runner = self.builder.build_runner(
            self.profile, self.ctx, agent=object(), view_factory=lambda state: {},
            config_factory=lambda: {"configurable": {"thread_id": "t1"}},
            resume_builder=lambda decision: ("resume", decision),
            interrupt_reader=lambda state: {"plan": 1})
        config = runner._config()
        self.assertEqual(config["configurable"], {"thread_id": "t1"})
        self.assertEqual(config["recursion_limit"], self.profile.budget.recursion_limit)
        self.assertEqual(runner._resume_builder("d"), ("resume", "d"))
        self.assertEqual(runner._interrupt_reader({}), {"plan": 1})

    def test_defaults_keep_interactive_chain_simple(self):
        runner = self.builder.build_runner(self.profile, self.ctx, agent=object())
        self.assertIsNone(runner._config_factory)
        self.assertIsNone(runner._resume_builder)
        self.assertIsNone(runner._interrupt_reader)
        self.assertEqual(runner._config(),
                         {"recursion_limit": self.profile.budget.recursion_limit})


if __name__ == "__main__":
    unittest.main()
