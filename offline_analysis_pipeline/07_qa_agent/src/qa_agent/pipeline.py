"""Answer pipeline: full-context mode (whole report in the LLM context window).

Rationale: report.md is ~15KB (~10k tokens), far below modern context limits.
Full-context beats retrieval here: 100% recall, zero retrieval code, anchors
naturally accurate. Retrieval (mature libs / provider embeddings) becomes
worthwhile only when the knowledge base outgrows the context window - see
docs/design-notes.md for the threshold and upgrade path.

Deterministic guarantees (independent of the LLM):
  - a data-version footer is always appended to the answer
  - cited anchors are validated against the report
  - refusal list [R] and template [T] live inside the report text, so they are
    always in context by construction
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

from . import llm
from .paths import CONFIGS, DATA_VERSION, OUTPUT, REPORT_MD

ANCHOR_IN_TEXT = re.compile(r"\[([A-Z][A-Z0-9]*)\]")
CONTEXT_CHAR_BUDGET = 60_000  # ~40k tokens; above this, consider retrieval


def _version_line():
    if DATA_VERSION.is_file():
        dv = json.loads(DATA_VERSION.read_text(encoding="utf-8"))
        note, gen = dv.get("data_version", ""), dv.get("generated_at", "")
    else:
        note, gen = "unknown", ""
    return f"数据版本：{note}（知识库生成于 {gen}）。回答基于该历史快照。"


def _system_prompt():
    p = CONFIGS / "system-prompt.md"
    base = p.read_text(encoding="utf-8") if p.is_file() else "你是数据分析报告问答助手。"
    return base + "\n\n" + _version_line()


def _anchors(report_text: str) -> set:
    return set(ANCHOR_IN_TEXT.findall(report_text))


def _validate_anchors(answer: str, anchors: set):
    cited = set(ANCHOR_IN_TEXT.findall(answer))
    return {"cited": sorted(cited), "unknown": sorted(c for c in cited if c not in anchors)}


def diagnostics():
    text = REPORT_MD.read_text(encoding="utf-8") if REPORT_MD.is_file() else ""
    return {"report": str(REPORT_MD), "exists": bool(text), "chars": len(text),
            "anchors": sorted(_anchors(text)), "context_budget_chars": CONTEXT_CHAR_BUDGET,
            "fits_full_context": 0 < len(text) <= CONTEXT_CHAR_BUDGET,
            "version": _version_line()}


def ask(question: str, no_llm: bool = False):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error_code": "empty_question"}
    if not REPORT_MD.is_file():
        return {"ok": False, "error_code": "report_missing", "detail": str(REPORT_MD)}
    report = REPORT_MD.read_text(encoding="utf-8")
    if len(report) > CONTEXT_CHAR_BUDGET:
        return {"ok": False, "error_code": "context_budget_exceeded",
                "detail": f"report is {len(report)} chars, budget {CONTEXT_CHAR_BUDGET}; "
                          f"introduce retrieval (see docs/design-notes.md)"}
    diag = {"chars": len(report), "anchors": sorted(_anchors(report))}

    if no_llm:
        return {"ok": True, "mode": "diagnostics_only", "question": question, "diag": diag,
                "version": _version_line(),
                "note": "未配置 LLM（或显式 --no-llm）：全上下文模式下无检索命中可展示，"
                        "配置 LLM 后整份报告将作为上下文"}

    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user",
         "content": f"报告全文（锚点引用体系：[K] [D] [F1]-[F5] [C] [R] [T]）：\n\n{report}\n\n"
                    f"---\n\n用户问题：{question}\n\n"
                    f"请按系统规则回答：引用锚点、数字逐字来自报告、命中 [R] 拒答清单则拒绝并说明。"},
    ]
    try:
        answer = llm.chat(messages)
    except llm.QaError as e:
        return {"ok": False, "error_code": e.code, "detail": e.detail,
                "note": "LLM 调用失败，不输出任何生成内容"}

    check = _validate_anchors(answer, diag["anchors"])
    footer = f"\n\n---\n{_version_line()}"
    result = {"ok": True, "mode": "full_context", "question": question,
              "answer": answer + footer, "citations": check, "diag": diag}
    if check["unknown"]:
        result["warning"] = f"回答引用了报告中不存在的锚点: {check['unknown']}"
    OUTPUT.mkdir(exist_ok=True)
    log = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "question": question, "answer": answer + footer}
    with (OUTPUT / "qa-log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")
    return result
