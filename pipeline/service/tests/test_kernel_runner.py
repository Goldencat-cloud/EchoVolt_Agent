"""状态机契约：五条路径 + 失败语义不降级（C6）+ 装配入口唯一（C1）。"""
import sys
import unittest
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
from kernel.context import Budget, KernelContractError, RunContext
from kernel.profile import DELIVERABLE, INTERACTIVE
from kernel.runner import (STATUS_AWAITING, STATUS_DONE, STATUS_FAILED,
                           Decision, KernelRunner, TurnRequest)


class _Agent:
    def __init__(self, result=None, error=None):
        self.result = result or {}
        self.error = error
        self.calls = []

    def invoke(self, payload, config):
        self.calls.append((payload, config))
        if self.error is not None:
            raise self.error
        return self.result


def _runner(profile, agent, view=None):
    ctx = RunContext(budget=profile.budget)
    factory = (lambda state: view if view is not None else {"answer": "ok"})
    return KernelRunner(profile, ctx, agent=agent, view_factory=factory), ctx


class DonePathTests(unittest.TestCase):
    def test_done_returns_view_and_metrics(self):
        runner, ctx = _runner(INTERACTIVE, _Agent({"messages": []}))
        outcome = runner.run(TurnRequest(messages=[{"role": "user", "content": "hi"}]))
        self.assertEqual(outcome.status, STATUS_DONE)
        self.assertEqual(outcome.view, {"answer": "ok"})
        self.assertEqual(outcome.metrics["successful_tool_calls"], 0)

    def test_recursion_limit_comes_from_profile(self):
        agent = _Agent({})
        runner, _ = _runner(INTERACTIVE, agent)
        runner.run(TurnRequest(messages=[]))
        self.assertEqual(agent.calls[0][1]["recursion_limit"],
                         INTERACTIVE.budget.recursion_limit)


class AwaitingPathTests(unittest.TestCase):
    def test_deliverable_pauses_at_gate(self):
        agent = _Agent({"status": "awaiting_review", "plan": {"coverage": "五议题"}})
        runner, _ = _runner(DELIVERABLE, agent)
        outcome = runner.run(TurnRequest(messages=[]))
        self.assertEqual(outcome.status, STATUS_AWAITING)
        self.assertEqual(outcome.pending, {"coverage": "五议题"})
        self.assertIsNone(outcome.view)

    def test_interactive_must_not_pause(self):
        agent = _Agent({"status": "awaiting_review", "plan": {}})
        runner, _ = _runner(INTERACTIVE, agent)
        outcome = runner.run(TurnRequest(messages=[]))
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertIn("契约违背", outcome.error)


class ResumeTests(unittest.TestCase):
    def test_approve_resumes_to_done(self):
        agent = _Agent({"status": "awaiting_review", "plan": {}})
        runner, _ = _runner(DELIVERABLE, agent)
        runner.run(TurnRequest(messages=[]))
        agent.result = {"messages": []}
        outcome = runner.resume(Decision(type="approve"))
        self.assertEqual(outcome.status, STATUS_DONE)
        self.assertEqual(agent.calls[-1][0]["resume"]["type"], "approve")

    def test_reject_fails_without_invoking_agent(self):
        agent = _Agent({"status": "awaiting_review", "plan": {}})
        runner, _ = _runner(DELIVERABLE, agent)
        runner.run(TurnRequest(messages=[]))
        before = len(agent.calls)
        outcome = runner.resume(Decision(type="reject"))
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertEqual(len(agent.calls), before)

    def test_resume_without_gate_is_contract_error(self):
        runner, _ = _runner(INTERACTIVE, _Agent({}))
        with self.assertRaises(KernelContractError):
            runner.resume(Decision(type="approve"))


class FailureTests(unittest.TestCase):
    def test_agent_exception_fails(self):
        runner, _ = _runner(DELIVERABLE, _Agent(error=RuntimeError("boom")))
        outcome = runner.run(TurnRequest(messages=[]))
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertIn("boom", outcome.error)

    def test_view_failure_fails_without_partial_view(self):
        runner, _ = _runner(DELIVERABLE, _Agent({}), view=None)
        runner._view_factory = None
        with self.assertRaises(KernelContractError):
            runner.run(TurnRequest(messages=[]))

    def test_failed_outcome_has_no_view(self):
        runner, _ = _runner(DELIVERABLE, _Agent(error=ValueError("x")))
        outcome = runner.run(TurnRequest(messages=[]))
        self.assertIsNone(outcome.view)
        self.assertNotIn("result", outcome.as_dict())


class ConstructionTests(unittest.TestCase):
    def test_agent_construction_symbols_only_in_builder(self):
        """C1：整个服务目录里只有宿主装配层 agent_engine.py 允许出现构造符号。

        auto-042 曾把构造入口放在 kernel/builder.py；本轮重构解除 kernel 与
        agent_engine 的循环依赖后，装配（模型/工具/技能）回到宿主层，
        kernel 只保留运行时。契约不变：构造符号全服务仅允许出现一个文件。
        """
        allowed = (SERVICE_DIR / "agent_engine.py").resolve()
        offenders = []
        for path in SERVICE_DIR.rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "__pycache__", "tests"}:
                continue
            if path.resolve() == allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "create_deep_agent(" in text or "create_agent(" in text:
                offenders.append(str(path.relative_to(SERVICE_DIR)))
        self.assertEqual(offenders, [])

    def test_skills_come_from_profile_declaration(self):
        """auto-042 7.2：注入的技能目录来自姿态声明，不是整个 agent_skills/。"""
        import dataclasses

        import agent_engine
        from kernel.profile import DELIVERABLE

        narrow = dataclasses.replace(DELIVERABLE, skills=("deep-analysis",))
        self.assertEqual([Path(p).name for p in agent_engine.skill_paths(narrow)],
                         ["deep-analysis"])

        declared = {Path(p).name for p in agent_engine.skill_paths(DELIVERABLE)}
        self.assertEqual(declared, {"deep-analysis", "plan-drafting",
                                    "execute-plan", "report-authoring"})

    def test_undeclared_skill_fails_at_build_time(self):
        import dataclasses

        import agent_engine
        from kernel.profile import DELIVERABLE

        broken = dataclasses.replace(DELIVERABLE, skills=("no-such-skill",))
        with self.assertRaises(ValueError):
            agent_engine.skill_paths(broken)

    def test_ledger_writes_only_in_context_module(self):
        """C5：新增文件里不允许直接 append 到 verified_steps。"""
        offenders = []
        for path in (SERVICE_DIR / "kernel").glob("*.py"):
            if path.name == "context.py":
                continue
            text = path.read_text(encoding="utf-8")
            if 'verified_steps"].append' in text or "verified_steps'].append" in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
