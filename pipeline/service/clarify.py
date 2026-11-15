"""Clarification sufficiency engine (auto-030 8.6, design D10).

必要信息 = 研究主题具体度 + 品牌范围 + 对比意图；时间窗口可默认全区间。
确定性快路径优先：能由快照元数据直接判定的缺口（品牌待澄清分支）不烧 LLM。
主题过泛/对比意图需要语义判断：用一次小调用问全当前全部缺口；用户答复后
重新评估，已答复信息保留、不重复问；每轮由用户答复驱动，不自行循环。

兜底：语义判定调用失败 → 有确定性缺口则只问确定性的；否则跳过澄清直接
探索——方向偏差由大纲审查门禁兜住（D10 裁定"按澄清程度而非次数"）。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import task_brief

Judge = Callable[..., dict[str, Any]]


def assess(topic: str, brief: dict[str, Any] | None = None,
           answers: list[dict[str, str]] | None = None,
           con: Any = None, judge: Judge | None = None) -> dict[str, Any]:
    """Decide whether clarification is needed; returns
    {needed, questions: [{field, question}], reason}.

    Deterministic gaps are resolved from snapshot metadata first; the semantic
    judge (one small call) then asks whatever remains in a single round.
    """
    brief = brief or {}
    gaps: list[dict[str, str]] = []
    coverage = task_brief.snapshot_coverage(con)
    scope = task_brief.resolve_brand_scope(brief.get("brand"), coverage["brands"])
    if scope.get("needs_clarification"):
        names = task_brief._brand_names(coverage["brands"])
        gaps.append({"field": "brand",
                     "question": f"本次分析对象是哪个品牌？（快照覆盖：{'、'.join(names)}）"})

    semantic: dict[str, Any] | None = None
    try:
        result = (judge or _llm_judge)(topic=topic, brief=brief,
                                       answers=answers or [], gaps=gaps)
        if isinstance(result, dict) and isinstance(result.get("questions"), list):
            semantic = result
    except Exception:  # noqa: BLE001 — 判定失败必须兜底，不得阻塞主流程
        semantic = None

    if semantic is None:
        if gaps:  # 确定性缺口仍然要问；语义缺口放弃（大纲门禁兜底）
            return {"needed": True, "questions": gaps,
                    "reason": "judge_unavailable_deterministic_only"}
        return {"needed": False, "questions": [],
                "reason": "clarify_judge_failed_skip"}

    questions = gaps + [q for q in semantic["questions"]
                        if isinstance(q, dict) and q.get("question")]
    questions = questions[:3]  # 单轮问题数上限：澄清是辅助，不是问卷
    return {"needed": bool(questions), "questions": questions,
            "reason": "sufficient" if not questions else "gaps_found"}


def _llm_judge(*, topic: str, brief: dict[str, Any],
               answers: list[dict[str, str]], gaps: list[dict[str, str]]) -> dict[str, Any]:
    """One small LLM call asking all remaining semantic gaps at once."""
    import os

    import llm

    model = llm.chat_model(timeout=60, max_retries=1)
    source_note = ("新管道实时数据（不问平台/采集范围/样本来源）"
                   if os.environ.get("AUTOINSIGHT_PIPELINE_DB", "").strip()
                   else "汽车之家精选帖子池的冻结快照（不问平台/采集范围/样本来源）")
    prompt = (
        "你是研究澄清判定器。判断下面的研究主题是否足够具体，可直接起草数据分析计划。\n"
        "以下事实由系统固定，一律不得提问：\n"
        "- 分析对象已锁定：小米 SU7（品牌裁定），不问品牌/车型版本/竞品选择；\n"
        f"- 数据来源：{source_note}；\n"
        "- 口径已固定：声明级与帖子级两种（不问情感判定标准/分类编码方式）；\n"
        "- 时间窗口默认全区间（不必问时间）；交付为结构化报告（不问交付形式/受众/用途）。\n"
        "只允许问两类问题：① 研究主题的范围界定（具体关注哪些议题维度/场景）；\n"
        "② 对比意图（想和什么比）。一次列出全部剩余问题（最多 3 个），"
        "已答复过的内容不要重复问。\n"
        "判定倾向：只要能起草出一份可审查的分析计划就视为足够（大纲审查阶段用户还会"
        "把关），宁可少问，不要连环追问。\n"
        f"研究主题：{topic}\n"
        f"已知信息：{json.dumps(brief, ensure_ascii=False)}\n"
        f"已答复澄清：{json.dumps(answers, ensure_ascii=False)}\n"
        "只输出 JSON：{\"questions\": [{\"field\": \"topic|compare|brand|other\", "
        "\"question\": \"...\"}]}；足够具体则输出 {\"questions\": []}。")
    response = model.invoke([{"role": "user", "content": prompt}])
    content = response.content if isinstance(response.content, str) else str(response.content)
    start, end = content.find("{"), content.rfind("}")
    parsed = json.loads(content[start:end + 1])
    return {"questions": parsed.get("questions") or []}
