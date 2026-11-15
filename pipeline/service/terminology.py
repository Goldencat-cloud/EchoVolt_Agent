"""Public wording for research concepts; internal keys stay inside contracts."""
from __future__ import annotations

METRIC_LABELS = {
    "negativeShare": "负面观点占比（按观点条数）",
    "posts": "相关帖子数",
    "negative_posts": "含负面反馈的帖子数",
    "claims": "观点条数",
    "negative": "负面观点条数",
}

DIMENSION_LABELS = {
    "aspect": "关注话题",
    "sentiment": "反馈倾向",
    "journey": "用户所处阶段",
    "ownership": "车辆持有情况",
    "product": "同时提及的车型",
    "time": "反馈时间",
}


def metric_caliber() -> str:
    return "负面观点条数 ÷ 全部观点条数；按观点条数统计。帖子数是另一统计单位，不能与观点条数直接相除。"


def public_dimension(key: str) -> str:
    return DIMENSION_LABELS.get(key, "分析维度")


def public_phase(phase: str) -> str:
    """Translate workflow phases for the UI without exposing internal stages."""
    return {
        "queued": "等待开始",
        "planning": "梳理研究问题",
        "analyzing": "分析数据与观点",
        "writing": "整理研究报告",
        "verifying": "核对数据与证据",
        "done": "分析完成",
        "failed": "分析未完成",
    }.get(phase, "正在分析")
