"""运行姿态（profile）：把预算、闸门、技能、工具白名单与失败语义变成数据。

新增第三个姿态时不需要写新的子类，只需要加一份实例并让它通过导入期校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from kernel import registry
from kernel.context import Budget

Artifact = Literal["answer", "report"]
Failure = Literal["retryable", "terminal"]

MIDDLEWARE_PLAN_GATE = "hitl.plan"


@dataclass(frozen=True)
class Profile:
    name: str
    tools: frozenset[str]
    budget: Budget
    artifact: Artifact
    failure: Failure
    timeout_s: int
    middleware: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.artifact not in ("answer", "report"):
            raise ValueError(f"artifact 非法：{self.artifact!r}")
        if self.failure not in ("retryable", "terminal"):
            raise ValueError(f"failure 非法：{self.failure!r}")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s 必须为正")
        # C3：白名单里的每个工具都必须已登记
        registry.resolve(self.tools)
        # C4：预算与递归必须自洽
        self.budget.check_recursion_fits()
        # 交付物与闸门必须一致：报告姿态必须人工审批，问答姿态不得要求审批
        if self.artifact == "report" and not self.requires_approval:
            raise ValueError(f"profile {self.name} 产出报告但未声明 {MIDDLEWARE_PLAN_GATE}")
        if self.artifact == "answer" and self.requires_approval:
            raise ValueError(f"profile {self.name} 产出问答却要求人工审批")

    @property
    def requires_approval(self) -> bool:
        return MIDDLEWARE_PLAN_GATE in self.middleware

    def allows(self, tool_id: str) -> bool:
        return tool_id in self.tools


INTERACTIVE = Profile(
    name="interactive",
    # 与现状等价：CONVERSATION_EXCLUDED_TOOLS 排除 submit_report 与 python_analyze。
    tools=registry.tools_for({registry.CAP_READ, registry.CAP_COMPUTE, registry.CAP_PLAN})
    - {"python_analyze"},
    # 与现状等价：现网交互链路使用共享常量 18 次，但图递归上限只有 32 个节点，
    # 每轮至少消费 2 个节点，实际可达约 (32-4)/2 = 14 次。声明 14 是让配置
    # 与真实上限一致（C4），不改变可达轮次，也不放宽任何现有边界。
    budget=Budget(tool_calls=14, errors=6, submits=4, code_failures=3, recursion_limit=32),
    artifact="answer",
    failure="retryable",
    timeout_s=60,
)

DELIVERABLE = Profile(
    name="deliverable",
    tools=registry.tools_for(registry.VALID_CAPABILITIES),
    budget=Budget(tool_calls=18, errors=6, submits=4, code_failures=3, recursion_limit=128),
    artifact="report",
    failure="terminal",
    timeout_s=300,
    middleware=(MIDDLEWARE_PLAN_GATE,),
    # 阶段技能全部显式声明：deep-analysis 负责入口判别与阶段派发，其余三个是
    # 被派发对象。只注入声明者，不注入整个技能目录（auto-042 7.2）。
    skills=("deep-analysis", "plan-drafting", "execute-plan", "report-authoring"),
)

PROFILES: Mapping[str, Profile] = {profile.name: profile for profile in (INTERACTIVE, DELIVERABLE)}


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"未知 profile：{name!r}，可用：{sorted(PROFILES)}") from exc
