"""派生层：`verified_steps` 到对外视图的唯一转换点（C5）。

两条既有链路曾各自把账本翻译成响应：交互链路内联在
`agent_engine._run_agent_conversation`（驼峰映射、统计/证据拆分），
交付链路内联在 `agent_engine.report_outcome`。字段命名规则一旦分散，
同一指标就会出现两个名字。所有映射收敛到这里。
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from kernel.context import KernelContractError, RunContext

STATS_LIMIT = 40
EVIDENCE_LIMIT = 20
REPORT_HITS_LIMIT = 8
ANSWER_LIMIT = 8000
FINAL_MESSAGE_LIMIT = 2000


def _camel(row: Mapping[str, Any]) -> dict[str, Any]:
    """单行统计字段的唯一映射规则。"""
    item = dict(row)
    if "negative_share" in item:
        item["negativeShare"] = item["negative_share"]
    if "negative" in item:
        item["negative_claims"] = item["negative"]
    return item


def to_answer_view(ctx: RunContext, final_text: str, *,
                   data_version: str | None,
                   snapshot_hash: str | None = None,
                   source_mode: str | None = None,
                   live: bool = False,
                   sanitizer: Callable[[str], str] | None = None,
                   citation_parser: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """交互链路视图。字段与 `_run_agent_conversation` 的返回字典逐键等价。"""
    stats: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    steps = ctx.verified_steps

    for step in steps:
        result = step.get("result")
        if not isinstance(result, Mapping):
            continue
        warnings.extend(result.get("warnings", []) or [])
        rows = result.get("rows", []) or []
        if step.get("kind") in {"method", "overview"}:
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                item = _camel(row)
                stats.append(item)
                if item.get("claim_id"):
                    evidence.append(item)
        data = (result.get("rows", []) or []) if live else (result.get("data", []) or [])
        if step.get("kind") == "evidence" and isinstance(data, list):
            evidence.extend(item for item in data if isinstance(item, Mapping))

    unique_evidence: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if item.get("claim_id"):
            unique_evidence[item["claim_id"]] = item

    text = sanitizer(final_text) if sanitizer else final_text
    view: dict[str, Any] = {
        "answer": text[:ANSWER_LIMIT],
        "stats": stats[:STATS_LIMIT],
        "evidence": list(unique_evidence.values())[:EVIDENCE_LIMIT],
        "applied_filters": {"aspects": list(dict.fromkeys(
            step.get("aspect") for step in steps
            if step.get("kind") == "method" and step.get("aspect")))},
        "data_version": data_version,
        "snapshot_hash": snapshot_hash,
        "warnings": list(dict.fromkeys(warnings)),
        "citations": citation_parser(text) if citation_parser else None,
        "report_hits": list(ctx.report_hits)[:REPORT_HITS_LIMIT],
        "tool_errors": ctx.tool_errors,
        "successful_tool_calls": ctx.successful_tool_calls,
    }
    if source_mode:
        view["source_mode"] = source_mode
    return view


def to_report_view(ctx: RunContext, *,
                   question: str,
                   final_message: str,
                   elapsed_ms: int,
                   charts: Sequence[Mapping[str, Any]] | None = None,
                   evidence_index: Sequence[Mapping[str, Any]] | None = None,
                   tool_log: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """交付链路视图。确定性字段与 `report_outcome` 逐键等价。

    `charts` / `evidence_index` 由交付链路的图表与证据协作者产出（它们依赖
    `report_charts` 与 `service`），本函数只负责组装，不重复实现其查询逻辑。
    """
    submission = ctx.submissions[-1] if ctx.submissions else None
    if submission is None:
        raise KernelContractError(
            "深度分析未完成：Agent 未提交通过门禁的报告。"
            + f"最终消息：{(final_message or '（空）')[:500]}")
    return {
        "ok": True,
        "report_id": submission.get("report_id"),
        "title": submission.get("title") or question,
        "report_md": submission.get("report_md") or final_message,
        "key_findings": submission.get("key_findings", []),
        "publication_status": submission.get("status"),
        "data_version": submission.get("data_version"),
        "charts": list(charts or []),
        "evidence_index": list(evidence_index or []),
        "final_message": final_message[:FINAL_MESSAGE_LIMIT],
        "tool_log": list(tool_log or []),
        "tool_errors": ctx.tool_errors,
        "metrics": ctx.metrics(),
        "elapsed_ms": elapsed_ms,
    }
