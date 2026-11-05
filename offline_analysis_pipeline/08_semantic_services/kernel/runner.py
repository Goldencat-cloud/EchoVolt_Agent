"""统一状态机：`run` 与 `resume` 产出同一个 `Outcome`。

三种终态取代了两条链路各自的返回约定：
- `done`：运行结束且有视图；
- `awaiting_review`：只可能出现在声明了人工闸门的 profile；
- `failed`：失败语义由 profile 决定（terminal 不得降级为部分产物）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from kernel.context import KernelContractError, RunContext
from kernel.profile import Profile

STATUS_DONE = "done"
STATUS_AWAITING = "awaiting_review"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class TurnRequest:
    messages: list[dict[str, Any]]
    question: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    type: str  # approve | edit | reject
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    status: str
    view: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    error: str | None = None
    metrics: Mapping[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "metrics": dict(self.metrics)}
        if self.view is not None:
            payload["result"] = self.view
        if self.pending is not None:
            payload["plan"] = self.pending
        if self.error is not None:
            payload["error"] = self.error
        return payload


class AgentLike(Protocol):
    def invoke(self, payload: dict[str, Any], config: dict[str, Any]) -> Any: ...


class KernelRunner:
    """把 agent 调用包进统一的预算、闸门与失败语义。"""

    def __init__(self, profile: Profile, ctx: RunContext, *,
                 agent: AgentLike,
                 view_factory: Callable[[Any], dict[str, Any]] | None = None,
                 config_factory: Callable[[], dict[str, Any]] | None = None,
                 resume_builder: Callable[[Decision], Any] | None = None,
                 interrupt_reader: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None
                 ) -> None:
        self._profile = profile
        self._ctx = ctx
        self._agent = agent
        self._view_factory = view_factory
        # 交付链需要 thread_id（checkpointer 复用）与 LangGraph 的 Command 协议；
        # 交互链两者都不用，保持默认实现（auto-042 5.2）。
        self._config_factory = config_factory
        self._resume_builder = resume_builder
        self._interrupt_reader = interrupt_reader

    @property
    def profile(self) -> Profile:
        return self._profile

    def _config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"recursion_limit": self._profile.budget.recursion_limit}
        if self._config_factory is not None:
            config.update(self._config_factory())
        return config

    def run(self, request: TurnRequest) -> Outcome:
        return self._invoke({"messages": request.messages, **dict(request.extra)})

    def resume(self, decision: Decision) -> Outcome:
        if not self._profile.requires_approval:
            raise KernelContractError(
                f"profile {self._profile.name} 没有人工闸门，不允许 resume")
        if self._resume_builder is not None:
            # 交付链：reject 是"退回模型重写"而非终止，交由 builder 构造 Command。
            return self._invoke(self._resume_builder(decision))
        if decision.type == "reject":
            return Outcome(status=STATUS_FAILED, error="plan rejected",
                           metrics=self._ctx.metrics())
        return self._invoke({"messages": [], "resume": {
            "type": decision.type, **dict(decision.payload)}})

    # -- 内部 -------------------------------------------------------------
    def _failed(self, error: str) -> Outcome:
        return Outcome(status=STATUS_FAILED, error=error, metrics=self._ctx.metrics())

    def _invoke(self, payload: Any) -> Outcome:
        try:
            raw = self._agent.invoke(payload, self._config())
        except Exception as exc:  # 失败语义由 profile 决定，不自行降级
            return self._failed(f"{type(exc).__name__}: {exc}")
        state = raw if isinstance(raw, Mapping) else {}

        if self._interrupt_reader is not None:
            pending = self._interrupt_reader(state)
            if pending is not None:
                if not self._profile.requires_approval:
                    return self._failed("契约违背：交互 profile 不得停在人工闸门")
                return Outcome(status=STATUS_AWAITING, pending=dict(pending),
                               metrics=self._ctx.metrics())

        status = state.get("status", STATUS_DONE)

        if status == STATUS_AWAITING:
            if not self._profile.requires_approval:
                return self._failed(
                    "契约违背：交互 profile 不得停在人工闸门")
            return Outcome(status=STATUS_AWAITING, pending=dict(state.get("plan") or {}),
                           metrics=self._ctx.metrics())
        if status not in (STATUS_DONE, "ok", None):
            return self._failed(str(state.get("error") or f"unexpected status: {status}"))

        if self._view_factory is None:
            raise KernelContractError("缺少 view_factory：无法把运行结果转成视图")
        try:
            view = self._view_factory(state)
        except Exception as exc:
            return self._failed(f"{type(exc).__name__}: {exc}")
        return Outcome(status=STATUS_DONE, view=view, metrics=self._ctx.metrics())
