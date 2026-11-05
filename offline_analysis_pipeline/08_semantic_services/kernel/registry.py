"""工具能力登记表：工具必须先登记，才能被 profile 引用（C3）。

登记的内容是**能力标签**而不是实现。工具实现仍由 `agent_tools.py` 提供；
本模块只回答"这个工具属于哪一类能力"，从而让 profile 能用白名单表达
"允许哪类能力"，而不是用黑名单排除具体工具。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

CAP_READ = "read"        # 读快照/语料，无副作用
CAP_COMPUTE = "compute"  # 执行计算（方法/聚合/沙箱）
CAP_PLAN = "plan"        # 提交分析计划，触发人工闸门
CAP_SUBMIT = "submit"    # 产出可发布物，写入存储

VALID_CAPABILITIES = frozenset({CAP_READ, CAP_COMPUTE, CAP_PLAN, CAP_SUBMIT})


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    capability: str

    def __post_init__(self) -> None:
        if self.capability not in VALID_CAPABILITIES:
            raise ValueError(f"未知能力标签 {self.capability!r}（工具 {self.tool_id}）")


# 与 agent_tools.build_tools 返回的工具一一对应。
TOOLS: dict[str, ToolSpec] = {
    spec.tool_id: spec
    for spec in (
        ToolSpec("semantic_overview", CAP_READ),
        ToolSpec("search_claims", CAP_READ),
        ToolSpec("get_negative_evidence", CAP_READ),
        ToolSpec("search_published_report", CAP_READ),
        ToolSpec("run_semantic_aggregate", CAP_COMPUTE),
        ToolSpec("python_analyze", CAP_COMPUTE),
        ToolSpec("submit_analysis_plan", CAP_PLAN),
        ToolSpec("submit_report", CAP_SUBMIT),
    )
}


def resolve(tool_ids: Iterable[str]) -> frozenset[str]:
    """校验并规范化 profile 的工具白名单。"""
    resolved = frozenset(tool_ids)
    unknown = sorted(resolved - set(TOOLS))
    if unknown:
        raise ValueError(f"profile 引用了未登记的工具：{unknown}")
    return resolved


def tools_for(capabilities: Iterable[str]) -> frozenset[str]:
    """按能力标签展开成 tool_id 集合，便于 profile 用能力而非具体工具表达。"""
    wanted = frozenset(capabilities)
    unknown = sorted(wanted - VALID_CAPABILITIES)
    if unknown:
        raise ValueError(f"未知能力标签：{unknown}")
    return frozenset(tool_id for tool_id, spec in TOOLS.items() if spec.capability in wanted)


def describe() -> Mapping[str, str]:
    return {tool_id: spec.capability for tool_id, spec in TOOLS.items()}
