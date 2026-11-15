"""Versioned business definitions shared by reports, agents, APIs and MCP."""
from __future__ import annotations

from typing import Any

CATALOG_VERSION = "2026-10-28.1"

METRICS: dict[str, dict[str, str]] = {
    "negativeShare": {"meaning": "负面观点声明数占该议题全部观点声明数的比例", "unit": "比例", "denominator": "该议题 claims", "source": "全量冻结快照 aspect-sentiment.csv", "scope": "全量观点声明"},
    "posts": {"meaning": "提及该议题的去重帖子数", "unit": "帖子数", "denominator": "不适用", "source": "全量冻结快照 aspect-sentiment.csv", "scope": "全量帖子"},
    "negative_posts": {"meaning": "含该议题负向观点的去重帖子数", "unit": "帖子数", "denominator": "不适用", "source": "全量冻结快照 aspect-sentiment.csv", "scope": "全量帖子"},
    "claims": {"meaning": "该议题的观点声明数", "unit": "声明数", "denominator": "不适用", "source": "全量冻结快照 aspect-sentiment.csv", "scope": "全量观点声明"},
    "negative": {"meaning": "该议题的负面观点声明数", "unit": "声明数", "denominator": "不适用", "source": "全量冻结快照 aspect-sentiment.csv", "scope": "全量观点声明"},
}

DIMENSIONS: dict[str, dict[str, Any]] = {
    "aspect": {"meaning": "反馈涉及的议题", "field": "aspect", "scope": "全量指标；精选证据子集", "missing": "未知议题不允许查询", "methods": ["semantic_aggregate"]},
    "sentiment": {"meaning": "观点情感分类", "field": "sentiment", "scope": "精选 core/potential 观点子集", "missing": "空值不参与情感分布", "methods": ["semantic_aggregate"]},
    "journey": {"meaning": "用户所处阶段", "field": "journey", "scope": "精选 core/potential 观点子集", "missing": "显示为未标注，不推断阶段", "methods": ["semantic_aggregate"]},
    "ownership": {"meaning": "车辆拥有状态及亲历程度", "field": "ownership/experience", "scope": "精选 core/potential 观点子集", "missing": "分别显示为未标注", "methods": ["semantic_aggregate"]},
    "product": {"meaning": "同一议题相关帖子提及的产品", "field": "post_scope.raw_name/series", "scope": "精选证据关联帖子，按帖子去重", "missing": "无产品映射时不展示", "methods": ["semantic_aggregate"]},
    "time": {"meaning": "精选负向观点的月份分布", "field": "claim.date", "scope": "精选 core/potential 观点子集，不代表全量声量趋势", "missing": "无有效日期的观点不参与", "methods": ["semantic_aggregate"]},
}
# auto-042：METHODS 只剩 semantic_aggregate（auto-039 起旧方法不可达），
# 这里只登记真实可声明的方法，避免目录对外宣称不存在的方法。
METHOD_DIMENSIONS: dict[str, set[str]] = {
    method: {dimension for dimension, definition in DIMENSIONS.items()
             if method in definition["methods"]}
    for method in {method for definition in DIMENSIONS.values() for method in definition["methods"]}
}
# 语义层方法可切分维度由模型决定，"other" 是计划可声明但不参与分组的占位类别。
METHOD_DIMENSIONS.setdefault("semantic_aggregate", set()).add("other")

# ---- 聚合能力声明 ----
# auto-042：原语（run_aggregate）退役后，本表只剩"表单选项是否开放"的开关；
# 指标/维度/口径的定义与校验由 semantic/model.yaml 与计划校验器负责。
PRIMITIVE_CAPABILITIES: dict[str, bool] = {
    "date_range_filter": True,   # 日期区间过滤（作用于精选子集 claims.date）
    "cross_dimension": True,     # 已登记维度内 ≤2 维交叉分组
    "brand_compare": False,      # 跨品牌对比：多品牌分支未开放（Owner 2026-10-27 裁定）
}


def primitive_capabilities() -> dict[str, bool]:
    """Capability declarations that drive the form options and plan validation.

    auto-042：名字保留历史称呼，实际作用于 `semantic_aggregate` 的表单选项；
    能力为 False 时对应选项不出现在 `/api/analysis/options`。
    """
    return dict(PRIMITIVE_CAPABILITIES)


def validate_brief(brief: dict[str, Any]) -> None:
    expected = {"schema_version", "catalog_version", "brief_id", "title", "questions", "metrics", "dimensions",
                "default_aspect", "minimum_posts",
                "required_evidence", "required_sections", "coverage_notice"}
    if (not isinstance(brief, dict) or set(brief) != expected
            or brief.get("schema_version") != "research-brief-3"
            or brief.get("catalog_version") != CATALOG_VERSION):
        raise ValueError("research brief fields or schema version are invalid")
    if (not brief["questions"] or not brief["metrics"] or not isinstance(brief["minimum_posts"], int)
            or brief["minimum_posts"] < 1):
        raise ValueError("research brief questions, metrics, or threshold are invalid")
    if not set(brief["metrics"]) <= set(METRICS) or not set(brief["dimensions"]) <= set(DIMENSIONS):
        raise ValueError("research brief contains unsupported metrics or dimensions")
    if not set(brief["required_evidence"]) <= {"quote", "url", "claim_id", "data_version"}:
        raise ValueError("research brief contains unsupported evidence requirements")
    if not set(brief["required_sections"]) <= {"observation", "comparison", "evidence", "interpretation", "limitations", "next_questions"}:
        raise ValueError("research brief contains unsupported report sections")


def catalogue() -> dict[str, Any]:
    """Return the single business definition source for APIs, agents and MCP."""
    return {"catalog_version": CATALOG_VERSION, "metrics": METRICS,
            "dimensions": DIMENSIONS,
            "method_dimensions": {key: sorted(value) for key, value in METHOD_DIMENSIONS.items()},
            "primitive": {"capabilities": primitive_capabilities()}}
