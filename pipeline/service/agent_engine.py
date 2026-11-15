"""DeepAgents engine: explore → draft → analyze (code interpreter) → report.

Workflow structure is carried outside the prompt:
  - the four-phase procedure lives in agent_skills/deep-analysis/SKILL.md,
    loaded via DeepAgents' SkillsMiddleware (progressive disclosure);
  - deterministic context (data overview + baseline statistics) is injected
    into the opening message by the orchestrator, so the agent skips its
    exploration round-trips;
  - failure handling is budgeted (per-tool retries capped) and every phase
    transition is reported through a progress callback for monitoring.

The model only sees the semantic layer; every number in the report must come
from tool/code results.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import config
import prompts
import sandbox
from research import service
import task_brief

HERE = Path(__file__).resolve().parent
AGENT_SKILLS_DIR = HERE / "agent_skills"
RECURSION_LIMIT = 32
# 深度报告工作流：模型/工具每轮各占 1 个图节点，还叠加技能与规划中间件；
# 工具成功调用预算 18 次 + 计划/证据/提交修订，32 层递归不够用（GraphRecursionError）。
REPORT_RECURSION_LIMIT = 128

# 静态提示词经 prompts.py 注册表统一管理（缓存契约见该模块 docstring）：
# 系统 prompt 与行动块逐字节稳定，构成跨 job 可缓存前缀；动态数据只允许出现在其后。
SYSTEM_PROMPT = prompts.DEEP_ANALYSIS_SYSTEM
CONVERSATION_PROMPT = prompts.CONVERSATION_SYSTEM



def _model():
    """Agent 主链路模型。经统一客户端 llm.chat_model 创建（fixture 可整体替换本函数）。"""
    import llm
    return llm.chat_model()


# ---------------- 宿主装配（自 kernel/builder 迁入，循环依赖已解除） ----------------
# kernel 只保留运行时；模型/工具/技能等宿主资源由本模块提供，
# 经 agent_factory 注入 build_runner。依赖方向：agent_engine → kernel（单向）。

def build_tools_for(profile, ctx) -> list:
    """按 profile 白名单挑工具。白名单意味着新工具默认不可见。"""
    import agent_tools

    return [tool for tool in agent_tools.build_tools(ctx.tool_context())
            if profile.allows(tool.name)]


def skill_permissions() -> list:
    """技能目录只读：拒绝改写技能定义，其余路径保持可写（摘要中间件要用）。

    backend 的 root_dir 就是 `agent_skills/`，若不设规则，`write_file` 可以改
    模型自己的技能文件——技能是可评审的工程资产，不该在运行期被改写。
    """
    from deepagents.middleware.filesystem import FilesystemPermission

    return [FilesystemPermission(operations=["write"],
                                 paths=["/**/SKILL.md", "/**/reference/**"],
                                 mode="deny")]


def assert_skills_exist(names) -> None:
    """profile 声明的技能必须在技能目录里真实存在（否则提示词会指向空路径）。"""
    for name in names:
        if not (AGENT_SKILLS_DIR / name / "SKILL.md").is_file():
            raise ValueError(f"profile 声明的技能不存在：{name!r}")


def skill_paths(profile) -> list[str]:
    """按姿态声明解析技能目录；未声明的技能不注入（auto-042 7.2）。

    此前注入的是整个 `agent_skills/` 目录，姿态声明只用于断言存在性，
    「每阶段至多读 1 个技能」因此只能靠提示词自律。改为注入声明集合后，
    约束由装配期决定。
    """
    assert_skills_exist(profile.skills)
    # 返回虚拟路径（backend 的 root_dir 就是 agent_skills/）：SkillsMiddleware 会把
    # source 原样写进系统提示的「技能位置」，传 Windows 绝对路径会诱导模型拿它调用
    # read_file，而该工具只接受 / 开头的虚拟路径（E2E 2026-11-04：每次运行白失败两次）。
    return [f"/{name}" for name in profile.skills]


def _chat_agent(profile, ctx):
    from langchain.agents import create_agent

    return create_agent(model=_model(),
                        tools=build_tools_for(profile, ctx),
                        system_prompt=CONVERSATION_PROMPT)


def _deep_agent(profile, ctx):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
    from langgraph.checkpoint.memory import MemorySaver

    from kernel.profile import MIDDLEWARE_PLAN_GATE

    interrupt_on = {}
    if MIDDLEWARE_PLAN_GATE in profile.middleware:
        interrupt_on = {"submit_analysis_plan": InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"])}
    return create_deep_agent(
        model=_model(),
        tools=build_tools_for(profile, ctx),
        system_prompt=SYSTEM_PROMPT,
        backend=FilesystemBackend(root_dir=AGENT_SKILLS_DIR),
        skills=skill_paths(profile),
        permissions=skill_permissions(),
        interrupt_on=interrupt_on,
        checkpointer=MemorySaver())


def default_agent_factory(profile, ctx):
    """宿主默认装配：kernel.builder.build_runner 的 agent_factory 注入点。"""
    if profile.artifact == "report":
        return _deep_agent(profile, ctx)
    return _chat_agent(profile, ctx)


def _baseline(aspect: str | None) -> dict[str, Any]:
    """Inject overview baselines while retaining all aspects for multi-facet questions."""
    try:
        stats = service.query_stats(aspect)
        return {"aspect": aspect, "rows": stats["data"], "caliber": stats["caliber"]}
    except (OSError, ValueError, KeyError):
        return {"aspect": aspect, "rows": [], "caliber": ""}


def _baseline_step(aspect: str | None, baseline: dict[str, Any]) -> dict[str, Any]:
    """Baseline as a provenance-ledger step (D13/D-CTX2): its numbers become
    reportable without re-running the same statistics, while the gate's
    numeric-provenance check still applies to everything else."""
    return {"kind": "baseline", "aspect": aspect,
            "method": "aspect_scope_compare" if aspect else "negative_share_by_aspect",
            "rows": baseline.get("rows", []), "caliber": baseline.get("caliber", ""),
            "verification": {"ok": True, "errors": [], "warnings": [],
                             "checks": ["server_precomputed_baseline"]}}


def _opening_message(question: str, aspect: str | None,
                     brief: dict[str, Any] | None = None,
                     baseline: dict[str, Any] | None = None) -> str:
    """Static-first opening message (cache contract, prompts.py): the static
    action block precedes the dynamic task brief."""
    baseline = baseline if baseline is not None else _baseline(aspect)
    message = task_brief.build_task_brief(question, aspect, baseline, brief)
    return prompts.DEEP_ANALYSIS_ACTION_BLOCK + "\n\n---\n\n" + message


def _tool_log(state: dict[str, Any]) -> list[dict[str, str]]:
    log = []
    for message in state.get("messages", []):
        kind = type(message).__name__
        if kind == "ToolMessage":
            log.append({"tool": getattr(message, "name", ""),
                        "output": str(getattr(message, "content", ""))[:600]})
        elif kind == "AIMessage":
            for call in (getattr(message, "tool_calls", None) or []):
                log.append({"tool": call.get("name", ""),
                            "args": str(call.get("args", ""))[:600]})
    return log[-60:]


def report_metrics(context: dict[str, Any]) -> dict[str, int]:
    """8.11 行为验收计量：一次运行的确定性计数（同批问题修订前后可对比）。"""
    return {"successful_tool_calls": context.get("successful_tool_calls", 0),
            "tool_errors": context.get("tool_errors", 0),
            "code_failures": sum((context.get("code_failures") or {}).values()),
            "submit_attempts": context.get("submit_attempts", 0),
            "gate_rejections": context.get("gate_rejections", 0)}


def _as_context(context: Any) -> Any:
    """兼容入口：把旧的 dict 上下文收窄成 `RunContext`（auto-041 D4）。

    只映射已声明字段与 `EXTRA_KEYS`；未知键忽略而不报错——严格性保留在
    `RunContext` 构造期，这里是迁移期适配，不是新的 schema 入口。
    """
    from kernel.context import EXTRA_KEYS, RunContext
    from kernel.profile import DELIVERABLE

    if isinstance(context, RunContext):
        return context
    mapping = context if isinstance(context, Mapping) else {}
    ctx = RunContext(budget=DELIVERABLE.budget)
    for name in ("submissions", "report_hits", "code_failures", "plan", "progress",
                 "live_context", "interactive", "accepted_submission",
                 "submit_attempts", "tool_errors", "successful_tool_calls",
                 "gate_rejections", "outline_approved", "outline_decision"):
        if name in mapping:
            setattr(ctx, name, mapping[name])
    ctx.evidence_ids = set(mapping.get("evidence_claim_ids") or ())
    # verified_steps 是账本而非普通字段：必须逐条经 record_step 写入，
    # 直接 setattr 会被 StepLedger 的只读视图挡住（auto-041）。
    for step in mapping.get("verified_steps") or ():
        ctx.record_step(step)
    for key in EXTRA_KEYS:
        if key in mapping:
            ctx.extras[key] = mapping[key]
    return ctx


def _evidence_index(ctx: Any) -> list[dict[str, Any]]:
    """auto-034 2.14：证据索引随结果下发，前端把正文 claim_id 折叠成编号角标。"""
    ids = sorted(ctx.evidence_ids)
    if not ids:
        return []
    try:
        from research import service
        return [
            {k: d.get(k) for k in ("claim_id", "url", "date", "title",
                                    "aspect", "sentiment", "ownership", "experience")}
            for d in service.evidence_details(ids)["details"] if d.get("found")]
    except Exception:
        return []  # 索引缺失只影响角标悬停信息，不影响报告本体


def report_outcome(context: Any, state: dict[str, Any],
                   question: str, started: float) -> dict[str, Any]:
    """Build the report outcome from a finished agent state (shared by the
    gate-less legacy path and the outline-gated session, D9)."""
    from kernel.derive import to_report_view

    messages = state.get("messages", [])
    final_message = str(messages[-1].content) if messages else ""
    ctx = _as_context(context)
    if not ctx.submissions:
        # 保留原错误信息：最近工具调用是排查"报告为什么没交"的主要线索。
        tail = json.dumps(_tool_log(state), ensure_ascii=False)[:1500]
        raise RuntimeError(
            "深度分析未完成：Agent 未提交通过门禁的报告。"
            + f"最终消息：{(final_message or '（空）')[:500]}；最近工具调用：" + tail)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # auto-034 2.8：图表随结果下发（前端报告视图直接渲染），与发布视图同源——
    # 只画已验证数据（计划 visualization 意图 + verified_steps），无数据则为空数组。
    import report_charts
    charts = report_charts.charts_for(
        {"analysis_plan": ctx.plan or {}},
        {"verified_steps": ctx.verified_steps})
    # auto-041：字段组装与截断统一走 kernel.derive，报告链路不再有第二份实现。
    return to_report_view(
        ctx, question=question, final_message=final_message, elapsed_ms=elapsed_ms,
        charts=charts, evidence_index=_evidence_index(ctx),
        tool_log=_tool_log(state))


def run_agent_conversation(question: str, history: list[dict[str, str]] | None = None,
                           session: dict[str, Any] | None = None) -> dict[str, Any]:
    return _run_agent_conversation(question, history, session)


def _final_text(state: dict[str, Any]) -> str:
    """取最后一条消息的文本块；非文本块（图片/工具）不计入回答。"""
    all_messages = state.get("messages", []) if isinstance(state, dict) else []
    final_content = all_messages[-1].content if all_messages else ""
    if isinstance(final_content, list):
        return "\n".join(str(block.get("text", "")) for block in final_content
                         if isinstance(block, dict) and block.get("type") == "text")
    return str(final_content)


def _run_agent_conversation(question: str, history: list[dict[str, str]] | None = None,
                            session: dict[str, Any] | None = None) -> dict[str, Any]:
    """Answer one turn through the shared kernel runner (auto-042 5.1)."""
    import report_source
    from research import service
    from kernel import builder
    from kernel.context import RunContext
    from kernel.derive import to_answer_view
    from kernel.profile import INTERACTIVE
    from kernel.runner import STATUS_DONE, TurnRequest

    if not config.model_configured():
        raise RuntimeError("model not configured or data transfer not approved")
    ctx = RunContext(budget=INTERACTIVE.budget, interactive=True)
    messages = []
    for turn in (history or [])[-12:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content[:5000]})
    messages.append({"role": "user", "content": json.dumps({
        "message": question,
        "previous_result": (session or {}).get("last_result"),
        "current_focus": (session or {}).get("filters", {}).get("aspect"),
        "data_version": service.display_version(),
    }, ensure_ascii=False, default=str)})

    # 派生统一走 kernel.derive：字段映射、去重与限流只有一处实现（auto-040）。
    # applied_filters 只包含本轮确认的维度：旧会话筛选仍留在历史里供模型参考，
    # 但不能被渲染成"当前筛选"。
    def _view(state: dict[str, Any]) -> dict[str, Any]:
        final = _final_text(state)
        if not final.strip():
            raise RuntimeError("对话 Agent 未返回可用内容")
        return to_answer_view(
            ctx, final,
            data_version=service.snapshot_version(),
            snapshot_hash=service.snapshot_hash(),
            sanitizer=_strip_unknown_citations,
            citation_parser=report_source.parse_citations)

    # 装配唯一入口（C1）：工具白名单、提示词与构造库都来自 profile。
    # kernel 不再反向 import 宿主：装配能力由本模块显式注入（循环依赖已解除）。
    runner = builder.build_runner(INTERACTIVE, ctx, view_factory=_view,
                                  agent_factory=default_agent_factory)
    outcome = runner.run(TurnRequest(messages=messages, question=question))
    if outcome.status != STATUS_DONE or outcome.view is None:
        raise RuntimeError(outcome.error or "对话 Agent 未返回可用结果")
    return outcome.view


def report_id_for(title: str, markdown: str) -> str:
    return hashlib.sha256(f"{title}:{markdown}".encode()).hexdigest()[:12]


def _strip_unknown_citations(text: str) -> str:
    """Remove citation anchors that do not exist in the displayed report.

    Fabricated anchors must never reach the UI as clickable citations; the
    literal token is stripped so the answer stays readable and only verifiable
    anchors survive.
    """
    import report_source
    sections = report_source.parse_citations(text)
    unknown = sections.get("unknown") or []
    for anchor in unknown:
        text = text.replace(f"[{anchor}]", "")
    return text
