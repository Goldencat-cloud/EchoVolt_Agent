"""运行上下文：唯一的 schema 与唯一的落账入口。

本模块是 C2（未知字段必须在构造期报错）与 C5（`verified_steps` 只能经
`record_step` 写入）的落点。任何运行期状态都必须在这里声明，禁止再向
`dict` 里自由增删键。
"""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping


class BudgetExhausted(RuntimeError):
    """预算类上限被击穿时抛出，具体是哪一类由 `kind` 指明。"""

    def __init__(self, kind: str, limit: int) -> None:
        super().__init__(f"budget exhausted: {kind} >= {limit}")
        self.kind = kind
        self.limit = limit


class KernelContractError(RuntimeError):
    """调用方违反内核契约（例如交互 profile 意外要求人工审批）。"""


@dataclass
class Budget:
    """一次运行允许消耗的上限。数值来源见 `profile.py`，此处只定义结构。"""

    tool_calls: int = 18
    errors: int = 6
    submits: int = 4
    code_failures: int = 3
    recursion_limit: int = 128

    def __post_init__(self) -> None:
        for name in ("tool_calls", "errors", "submits", "code_failures", "recursion_limit"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"budget.{name} 必须是正整数，收到 {value!r}")

    def check_recursion_fits(self) -> None:
        """C4：图递归上限必须容得下工具预算（每轮至少消费 2 个节点）。"""
        needed = self.tool_calls * 2 + 4
        if self.recursion_limit < needed:
            raise ValueError(
                f"budget 自洽性失败：tool_calls={self.tool_calls} 需要 "
                f"recursion_limit>={needed}，实际 {self.recursion_limit}")


@dataclass(frozen=True)
class Step:
    """一条已验证步骤。`result` 保持原始结构，派生转换只发生在 `derive.py`。"""

    kind: str
    aspect: str | None = None
    method: str | None = None
    result: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        # 保留原始结构：既有链路对 result 的容错（非映射即跳过）必须一并对齐，
        # 因此这里不能假设 result 一定是映射。
        result = dict(self.result) if isinstance(self.result, Mapping) else self.result
        payload: dict[str, Any] = {"kind": self.kind, "result": result}
        if self.aspect is not None:
            payload["aspect"] = self.aspect
        if self.method is not None:
            payload["method"] = self.method
        return payload


class StepLedger:
    """`verified_steps` 的唯一容器。外部只能追加，不能拿到可变列表。"""

    __slots__ = ("_steps",)

    def __init__(self, steps: list[Mapping[str, Any]] | None = None) -> None:
        self._steps: list[dict[str, Any]] = [dict(step) for step in (steps or [])]

    def record(self, step: Step | Mapping[str, Any]) -> None:
        payload = step.as_dict() if isinstance(step, Step) else dict(step)
        if "kind" not in payload:
            raise KernelContractError("step 必须包含 kind")
        self._steps.append(payload)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(tuple(self._steps))

    def __len__(self) -> int:
        return len(self._steps)

    def as_list(self) -> list[dict[str, Any]]:
        return [dict(step) for step in self._steps]

    def raw(self) -> list[dict[str, Any]]:
        """迁移期适配：仅供 `ToolContext` 交给既有工具直接 append。

        新代码必须使用 `RunContext.record_step`；本方法存在是为了让 9 个既有
        工具无需修改即可继续记账，同时保证它们写的仍是同一份账本。
        """
        return self._steps


@dataclass
class RunContext:
    """一次运行的全部可变状态。

    字段集合是两个既有实现上下文键的并集：交互链路与交付链路都从这里取用，
    新增字段必须同时在这里声明，否则构造期即报错。
    """

    budget: Budget
    ledger: StepLedger = field(default_factory=StepLedger)
    submissions: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: set[str] = field(default_factory=set)
    report_hits: list[dict[str, Any]] = field(default_factory=list)
    code_failures: dict[str, int] = field(default_factory=dict)
    plan: dict[str, Any] | None = None
    progress: Callable[[str], None] | None = None
    live_context: Any = None
    interactive: bool = True
    accepted_submission: bool = False
    submit_attempts: int = 0
    tool_errors: int = 0
    successful_tool_calls: int = 0
    # auto-041：交付链路的大纲闸门状态。工具会读 outline_approved /
    # outline_decision，并在被拒时累加 gate_rejections；未登记就接线路由会 KeyError。
    gate_rejections: int = 0
    outline_approved: bool = False
    outline_decision: dict[str, Any] | None = None
    # 既有工具的辅助键（live_evidence / delivery_spec 等）。集中声明在此，
    # 避免再次出现"随处 setdefault 一个新键"的隐性 schema 扩张。
    extras: dict[str, Any] = field(default_factory=dict)

    # -- 预算消费：所有计数变化都必须经过这些方法 -------------------------
    def spend_tool_call(self) -> None:
        if self.successful_tool_calls >= self.budget.tool_calls:
            raise BudgetExhausted("tool_calls", self.budget.tool_calls)
        self.successful_tool_calls += 1

    def spend_error(self) -> None:
        if self.tool_errors >= self.budget.errors:
            raise BudgetExhausted("errors", self.budget.errors)
        self.tool_errors += 1

    def spend_submit(self) -> None:
        if self.submit_attempts >= self.budget.submits:
            raise BudgetExhausted("submits", self.budget.submits)
        self.submit_attempts += 1

    def spend_code_failure(self, reason: str) -> None:
        count = self.code_failures.get(reason, 0) + 1
        if count > self.budget.code_failures:
            raise BudgetExhausted("code_failures", self.budget.code_failures)
        self.code_failures[reason] = count

    # -- 账本 -------------------------------------------------------------
    @property
    def verified_steps(self) -> list[dict[str, Any]]:
        """只读视图：调用方可以遍历，但无法通过它追加。"""
        return self.ledger.as_list()

    def record_step(self, step: Step | Mapping[str, Any]) -> None:
        self.ledger.record(step)

    def add_evidence(self, claim_ids: Any) -> None:
        for claim_id in claim_ids or ():
            if claim_id:
                self.evidence_ids.add(str(claim_id))

    def metrics(self) -> dict[str, int]:
        """与既有 `report_metrics` 同构的确定性计数。"""
        return {
            "successful_tool_calls": self.successful_tool_calls,
            "tool_errors": self.tool_errors,
            "code_failures": sum(self.code_failures.values()),
            "submit_attempts": self.submit_attempts,
            # auto-041：原先硬编码 0，会让内核侧指标与真实闸门拒绝次数不一致。
            "gate_rejections": self.gate_rejections,
        }

    def tool_context(self) -> "ToolContext":
        """给既有工具使用的字典桥（迁移期适配层）。"""
        return ToolContext(self)


#: 允许经字典桥透传到 `RunContext.extras` 的辅助键。
EXTRA_KEYS = frozenset({"live_evidence", "delivery_spec", "detailed_notes"})


class ToolContext(MutableMapping[str, Any]):
    """把 `RunContext` 暴露成既有工具期望的 `dict` 接口。

    存在的理由：`agent_tools` 里的 9 个工具以 `dict` 读写上下文。本类让它们
    无需修改即可工作，同时保持 `RunContext` 是唯一状态来源——工具的写入会
    落回同一个对象，而不是另一份副本。
    """

    _SCALARS = ("tool_errors", "successful_tool_calls", "submit_attempts",
                "accepted_submission", "interactive", "gate_rejections",
                "outline_approved")
    #: 桥接键的顺序即 `__iter__` 的顺序，`__len__` 必须与之一致（C5）。
    _KEYS = ("verified_steps", "evidence_claim_ids", *_SCALARS,
             "submissions", "code_failures", "report_hits", "plan",
             "outline_decision", "live_context", "progress", *EXTRA_KEYS)
    #: 只读键：工具可以读，但不允许整体替换。
    _READ_ONLY = ("verified_steps", "evidence_claim_ids", "live_context", "progress")

    def __init__(self, ctx: RunContext) -> None:
        self._ctx = ctx

    def __getitem__(self, key: str) -> Any:
        ctx = self._ctx
        if key == "verified_steps":
            return ctx.ledger.raw()
        if key == "evidence_claim_ids":
            return ctx.evidence_ids
        if key in EXTRA_KEYS:
            return ctx.extras[key]
        if key in self._KEYS:
            return getattr(ctx, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        ctx = self._ctx
        if key in EXTRA_KEYS:
            ctx.extras[key] = value
        elif key in self._KEYS and key not in self._READ_ONLY:
            setattr(ctx, key, value)
        else:
            raise KeyError(f"不支持的上下文键：{key}")

    def __delitem__(self, key: str) -> None:
        raise KernelContractError("上下文键不允许删除")

    def __iter__(self) -> Iterator[str]:
        return iter(self._KEYS)

    def __len__(self) -> int:
        return len(self._KEYS)
