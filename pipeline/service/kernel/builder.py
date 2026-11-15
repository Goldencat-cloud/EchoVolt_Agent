"""唯一装配入口（C1）：`create_agent` / `create_deep_agent` 只能出现在宿主层。

两条链路过去各自调用不同的构造库，导致升级与中间件装配需要验证两遍。
auto-042 把装配收敛到本模块的 `build_runner(profile, ctx)`。

依赖方向（本轮重构固定，kernel 不再反向依赖宿主层）：

    agent_engine（宿主：模型/工具/技能装配）  →  kernel（本包：运行时）
    tests / report_session                    →  kernel

宿主通过 `agent_factory` 注入真实装配（`agent_engine.default_agent_factory`）；
测试注入 `agent` 或替身 factory。kernel 内部不得 import agent_engine /
agent_tools / langchain / deepagents。
"""
from __future__ import annotations

from typing import Any, Callable

from kernel.context import RunContext
from kernel.profile import Profile
from kernel.runner import KernelRunner


def build_runner(profile: Profile, ctx: RunContext, *,
                 agent: Any = None,
                 agent_factory: Callable[[Profile, RunContext], Any] | None = None,
                 view_factory: Callable[[Any], dict[str, Any]] | None = None,
                 config_factory: Callable[[], dict[str, Any]] | None = None,
                 resume_builder: Callable[[Any], Any] | None = None,
                 interrupt_reader: Callable[[Any], Any] | None = None) -> KernelRunner:
    """构造 runner。测试可注入 `agent` 或 `agent_factory` 以避开真实模型。

    `agent` 与 `agent_factory` 必须二选一：kernel 不再内置宿主默认装配
    （此前 builder 反向 import agent_engine 形成循环依赖，本轮已解除）。

    交付链的 `config_factory` / `resume_builder` / `interrupt_reader` 必须由此
    透传：只传 `agent` 会让 `ReportSession` 的 thread_id 与中断点归属丢失，
    并在构造期抛 `TypeError`（真实冒烟发现，见 auto-042 验证记录 8）。
    """
    if agent is None:
        if agent_factory is None:
            raise TypeError(
                "build_runner 需要显式 agent_factory（kernel 不反向依赖宿主装配）；"
                "生产代码请传 agent_engine.default_agent_factory")
        agent = agent_factory(profile, ctx)
    return KernelRunner(profile, ctx, agent=agent, view_factory=view_factory,
                        config_factory=config_factory,
                        resume_builder=resume_builder,
                        interrupt_reader=interrupt_reader)
