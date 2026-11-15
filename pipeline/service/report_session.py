"""Outline-gate orchestration for deep-analysis jobs (auto-030 8.5, design D9 方案 B).

``submit_analysis_plan`` is interrupt-gated: the agent run pauses for human
outline review instead of executing code. Each job owns a ReportSession
(checkpointer + tool context); the job store stays the single source of truth
for the lifecycle (D5) — an awaiting job occupies no execution slot, and
session cleanup is synchronized with job cleanup. Resume decisions map
confirm→approve / edit→edited_action / regenerate→reject.

Spike-verified behaviors locked in tests/test_interrupt_gate_spike.py:
interrupt value shape, resume decision schema, and the composite ToolMessage
("middleware note + Tool response:") on the edit path.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import config
import jobs

REGENERATE_LIMIT = 3
PLAN_MAX_CHARS = 8_000
# 澄清轮次保险丝：答复达到该轮数后强制放行（大纲门禁兜底，D10/E2E 2026-10-28）
CLARIFY_MAX_ROUNDS = 2
_THREAD_PREFIX = "report-"


class ReportSession:
    """One deep-analysis run that pauses at the outline gate and resumes."""

    def __init__(self, question: str, aspect: str | None = None,
                 brief: dict[str, Any] | None = None,
                 progress: Callable[[str], None] | None = None) -> None:
        self.question = question
        self.aspect = aspect
        self.brief = brief
        self._progress = progress or (lambda phase: None)
        self._thread_id = ""
        # auto-042：装配经 kernel.builder.build_runner，runner 持有 agent 与 checkpointer。
        self._runner: Any = None
        # auto-041：kernel.context.RunContext（延迟导入）。交付链路与问答链路
        # 共用同一个状态对象，不再各自维护 dict schema。
        self._context: Any = None
        self._started = 0.0
        self._delivery_spec: dict[str, Any] | None = None

    def close(self) -> None:
        """Release per-job data resources after completion, failure or eviction."""
        self._context = None

    def new_thread_id(self) -> str:
        self._thread_id = f"{_THREAD_PREFIX}{uuid.uuid4().hex}"
        return self._thread_id

    def _ensure_runner(self) -> Any:
        """装配唯一入口（auto-042 5.2）：交付链与问答链共用 `build_runner`。

        runner 只在首次调用时构造并保存在实例上，checkpointer 因此随会话复用；
        resume 必须命中同一个 MemorySaver 实例，否则中断点会丢失。
        """
        if self._runner is not None:
            return self._runner
        if not config.model_configured():
            raise RuntimeError("model not configured or data transfer not approved")
        import agent_engine
        from kernel import builder
        from kernel.context import RunContext
        from kernel.profile import DELIVERABLE

        baseline = agent_engine._baseline(self.aspect)
        self._context = RunContext(
            budget=DELIVERABLE.budget,
            submissions=[], code_failures={},
            submit_attempts=0, accepted_submission=False,
            tool_errors=0, successful_tool_calls=0,
            interactive=True, progress=self._progress)
        self._context.record_step(agent_engine._baseline_step(self.aspect, baseline))
        self._started = time.perf_counter()

        def _view(state: dict[str, Any]) -> dict[str, Any]:
            return agent_engine.report_outcome(self._context, state,
                                               self.question, self._started)

        self._runner = builder.build_runner(
            DELIVERABLE, self._context,
            view_factory=_view,
            agent_factory=agent_engine.default_agent_factory,
            config_factory=self._config,
            resume_builder=_resume_command,
            interrupt_reader=_pending_plan)
        self._baseline = baseline
        return self._runner

    def _config(self) -> dict[str, Any]:
        # thread_id 决定 checkpointer 上的中断点归属；recursion_limit 由 profile 提供。
        return {"configurable": {"thread_id": self._thread_id}}

    def run(self, thread_id: str) -> dict[str, Any]:
        """First invoke: run until the outline gate pauses or the job finishes."""
        import agent_engine
        from kernel.runner import TurnRequest

        self._thread_id = thread_id
        runner = self._ensure_runner()
        content = agent_engine._opening_message(self.question, self.aspect,
                                                self.brief, self._baseline)
        outcome = runner.run(TurnRequest(
            messages=[{"role": "user", "content": content}],
            question=self.question,
            extra={"pinned_skills": ["deep-analysis"]}))
        self._progress("收尾中")
        return self._auto_reject_invalid(outcome).as_dict()

    def resume(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Continue a paused run with one gate decision (approve/edit/reject).

        HITL batched protocol (8.4 spike): the middleware expects
        ``Command(resume={"decisions": [...]})`` — a bare decision dict raises
        KeyError('decisions') on resume.
        """
        from kernel.runner import Decision

        if self._runner is None:
            raise RuntimeError("report session lost: 会话已释放，无法恢复大纲确认")
        decisions = decision.get("decisions") if isinstance(decision, dict) \
            and "decisions" in decision else [decision]
        self._record_outline_decision(decisions)
        outcome = self._runner.resume(Decision(type="decisions",
                                               payload={"decisions": decisions}))
        self._progress("收尾中")
        return self._auto_reject_invalid(outcome).as_dict()

    def _auto_reject_invalid(self, outcome: Any, budget: int = 2) -> Any:
        """草案过不了确定性预检时，不进人工审查：带错误反馈退回给模型重写。

        批准一份必然被拒的草案，只会产生"暂停 → 批准 → 报错 → 重写 → 再暂停"
        的空转；预检只做参数级判定，权威校验仍在 submit_analysis_plan。
        """
        import agent_tools
        from kernel.runner import STATUS_AWAITING, Decision

        for _ in range(budget):
            if outcome.status != STATUS_AWAITING:
                return outcome
            plan = outcome.pending or {}
            problems = agent_tools.plan_problems(plan.get("plan_json") or "")
            if not problems:
                return outcome
            self._progress("计划预检未通过，退回重写")
            self._record_outline_decision([{"type": "reject"}])
            outcome = self._runner.resume(Decision(type="decisions", payload={"decisions": [{
                "type": "reject",
                "message": "草案未通过确定性校验（无需人工确认），请修正后重新提交："
                           + "；".join(problems[:3]),
            }]}))
        return outcome

    def _record_outline_decision(self, decisions: list[Any]) -> None:
        """记录大纲审批结果。

        旧实现用 `pop("outline_decision")` 删除键；字典桥不允许删除，置 None 与
        "键不存在"对工具侧的 `context.get(...)` 完全等价（auto-041 D2）。
        """
        ctx = self._context
        if ctx is None:
            return
        ctx.outline_approved = bool(decisions) and all(
            isinstance(item, dict) and item.get("type") in {"approve", "edit"}
            for item in decisions)
        if ctx.outline_approved:
            ctx.outline_decision = {
                "types": [item["type"] for item in decisions],
                "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        else:
            ctx.outline_decision = None

    def set_delivery_spec(self, spec: dict[str, Any]) -> None:
        """Receive the optional 重点/受众 spec carried with confirm/edit (8.10/D12).

        Stored on the shared tool context; the gated tool surfaces it to the
        model in its ToolMessage after approval. NOTE: do NOT inject it as a
        user message via update_state before resuming — the graph is paused
        right after an assistant message with pending tool_calls, and inserting
        a user message there produces an invalid message order that the
        OpenAI-compatible endpoint rejects (E2E finding 2026-10-28).
        """
        self._delivery_spec = spec
        if self._context is not None:
            self._context.extras["delivery_spec"] = spec

def _resume_command(decision: Any) -> Any:
    """把 Decision 转成 LangGraph 批处理 resume 协议（HITL middleware 要求 decisions 数组）。"""
    from langgraph.types import Command

    decisions = (decision.payload or {}).get("decisions") or [{"type": decision.type}]
    return Command(resume={"decisions": decisions})


def _pending_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    """把 LangGraph 的中断状态转成 runner 的 pending；无中断返回 None。"""
    interrupts = state.get("__interrupt__") or []
    if not interrupts:
        return None
    return _plan_from_interrupt(interrupts[0])


def _plan_from_interrupt(interrupt: Any) -> dict[str, Any]:
    """Extract the proposed plan from a batched HITL interrupt value."""
    value = getattr(interrupt, "value", interrupt)
    requests = (value or {}).get("action_requests") or []
    for request in requests:
        if request.get("name") == "submit_analysis_plan":
            raw = (request.get("args") or {}).get("plan_json")
            try:
                plan = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (TypeError, ValueError):
                plan = {}
            return {"plan_json": raw if isinstance(raw, str) else json.dumps(
                plan, ensure_ascii=False), "plan": plan if isinstance(plan, dict) else {}}
    return {"plan_json": "", "plan": {}}


# ---------------- job orchestration (jobs.py stays the lifecycle truth) ----------------

_SESSIONS: dict[str, ReportSession] = {}
_SESSIONS_LOCK = threading.Lock()


def start_job(job_id: str, question: str,
              brief: dict[str, Any] | None = None) -> None:
    """Clarify-first orchestration (D10), run in background (assess may call
    the LLM): assess sufficiency → pause at 澄清中 or launch 数据探索中."""
    def flow() -> None:
        import clarify
        assessment = clarify.assess(question, brief)
        if assessment.get("needed"):
            jobs.pause_for_clarify(job_id, assessment["questions"])
            return
        _launch(job_id, question, brief)

    _spawn_flow(job_id, flow)


def submit_clarification(job_id: str, answer: dict[str, Any]) -> None:
    """Re-assess after one user reply; relaunch when sufficient (4.3/D10).
    Background execution — the client polls the status endpoint for the
    outcome (still 澄清中 with new questions, or 数据探索中)."""
    def flow() -> None:
        import clarify
        job = jobs.get_job(job_id)
        if job is None or job.get("status") != "clarifying":
            return
        answers = list(job.get("clarifications") or []) + [answer]
        if len(answers) >= CLARIFY_MAX_ROUNDS:
            # E2E 实测保险丝（2026-10-28）：语义判定在部分问题上不收敛，
            # 连问多轮。按 D10"大纲门禁兜底"，达到轮次上限后强制放行探索。
            jobs.record_clarification(job_id, answer, [])
            if not jobs.claim_for_run(job_id, "数据探索中"):
                return
            _launch(job_id, job.get("question") or "", job.get("brief"))
            return
        assessment = clarify.assess(job.get("question") or "", job.get("brief"),
                                    answers=answers)
        if assessment.get("needed"):
            jobs.record_clarification(job_id, answer, assessment["questions"])
            return
        jobs.record_clarification(job_id, answer, [])
        if not jobs.claim_for_run(job_id, "数据探索中"):
            return
        _launch(job_id, job.get("question") or "", job.get("brief"))

    _spawn_flow(job_id, flow)


def _launch(job_id: str, question: str,
            brief: dict[str, Any] | None = None) -> None:
    """Create the session for a job and run it up to the gate."""
    session = ReportSession(question, brief=brief,
                            progress=lambda phase: jobs.set_phase(job_id, phase))
    with _SESSIONS_LOCK:
        _SESSIONS[job_id] = session
    _spawn(job_id, lambda: session.run(session.new_thread_id()))


def resume_job(job_id: str, decision: dict[str, Any],
               delivery_spec: dict[str, Any] | None = None) -> bool:
    """Resume a paused job with a gate decision; False when the session is lost."""
    _sweep()
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(job_id)
    if session is None:
        return False
    if delivery_spec:
        session.set_delivery_spec(delivery_spec)
    _spawn(job_id, lambda: session.resume(decision))
    return True


def drop_session(job_id: str) -> None:
    with _SESSIONS_LOCK:
        session = _SESSIONS.pop(job_id, None)
    if session is not None and callable(getattr(session, "close", None)):
        session.close()


def _sweep() -> None:
    """Drop sessions whose job no longer exists (D5: job store is the truth)."""
    with _SESSIONS_LOCK:
        stale = [job_id for job_id in _SESSIONS if jobs.get_job(job_id) is None]
    for job_id in stale:
        drop_session(job_id)


def _spawn_flow(job_id: str, work: Callable[[], None]) -> None:
    """Background flow (clarify assessment etc.): failures surface, no result."""
    def target() -> None:
        try:
            work()
        except Exception as exc:  # failures must surface, never be swallowed
            jobs.finish_error(job_id, {"error": f"{type(exc).__name__}: {exc}"})
            drop_session(job_id)

    threading.Thread(target=target, daemon=True).start()


def _spawn(job_id: str, work: Callable[[], dict[str, Any]]) -> None:
    def target() -> None:
        try:
            outcome = work()
        except Exception as exc:  # failures must surface, never be swallowed
            jobs.finish_error(job_id, {"error": f"{type(exc).__name__}: {exc}"})
            drop_session(job_id)
            return
        if outcome.get("status") == "awaiting_review":
            plan = outcome.get("plan") or {}
            import task_brief
            jobs.pause_for_review(job_id, {"plan": plan,
                                           "plan_json": plan.get("plan_json", ""),
                                           "outline": task_brief.outline_projection(plan.get("plan"))})
        else:
            jobs.finish_ok(job_id, outcome.get("result") or {})
            drop_session(job_id)

    threading.Thread(target=target, daemon=True).start()
