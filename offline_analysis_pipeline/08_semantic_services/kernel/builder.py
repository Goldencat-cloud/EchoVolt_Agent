"""唯一装配入口（C1）：`create_agent` / `create_deep_agent` 只能出现在这里。

两条链路过去各自调用不同的构造库，导致升级与中间件装配需要验证两遍。
本模块把"哪条链路用哪套库"收敛成一个内部判断，对外只暴露
`build_runner(profile, ctx, runtime=...)`。

模型、提示词、技能目录与工具构造都经 `AgentRuntime` 注入，
内核因此不依赖任何外层模块。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from kernel.context import RunContext
from kernel.profile import Profile
from kernel.runner import KernelRunner
from kernel.runtime import AgentRuntime


def build_tools(profile: Profile, ctx: RunContext,
                tool_factory: Callable[[dict[str, Any]], list[Any]]) -> list[Any]:
    """按 profile 白名单挑工具。白名单意味着新工具默认不可见。"""
    return [tool for tool in tool_factory(ctx.tool_context())
            if profile.allows(tool.name)]


def skill_permissions() -> list[Any]:
    """技能目录只读：拒绝改写技能定义，其余路径保持可写（摘要中间件要用）。

    backend 的 root_dir 就是 `agent_skills/`，若不设规则，`write_file` 可以改
    模型自己的技能文件——技能是可评审的工程资产，不该在运行期被改写。
    """
    from deepagents.middleware.filesystem import FilesystemPermission

    return [FilesystemPermission(operations=["write"],
                                 paths=["/**/SKILL.md", "/**/reference/**"],
                                 mode="deny")]


def assert_skills_exist(names: tuple[str, ...] | list[str], skills_dir: Path) -> None:
    """profile 声明的技能必须在技能目录里真实存在（否则提示词会指向空路径）。"""
    for name in names:
        if not (skills_dir / name / "SKILL.md").is_file():
            raise ValueError(f"profile 声明的技能不存在：{name!r}")


def skill_paths(profile: Profile, skills_dir: Path) -> list[str]:
    """按姿态声明解析技能目录；未声明的技能不注入（auto-042 7.2）。

    此前注入的是整个 `agent_skills/` 目录，姿态声明只用于断言存在性，
    「每阶段至多读 1 个技能」因此只能靠提示词自律。改为注入声明集合后，
    约束由装配期决定。
    """
    assert_skills_exist(profile.skills, skills_dir)
    # 返回虚拟路径（backend 的 root_dir 就是 agent_skills/）：SkillsMiddleware 会把
    # source 原样写进系统提示的「技能位置」，传 Windows 绝对路径会诱导模型拿它调用
    # read_file，而该工具只接受 / 开头的虚拟路径（E2E 2026-11-04：每次运行白失败两次）。
    return [f"/{name}" for name in profile.skills]


def build_runner(profile: Profile, ctx: RunContext, *,
                 runtime: AgentRuntime | None = None,
                 agent: Any = None,
                 agent_factory: Callable[[Profile, RunContext], Any] | None = None,
                 view_factory: Callable[[Any], dict[str, Any]] | None = None,
                 config_factory: Callable[[], dict[str, Any]] | None = None,
                 resume_builder: Callable[[Any], Any] | None = None,
                 interrupt_reader: Callable[[Any], Any] | None = None) -> KernelRunner:
    """构造 runner。测试可注入 `agent` 或 `agent_factory` 以避开真实模型。

    交付链的 `config_factory` / `resume_builder` / `interrupt_reader` 必须由此
    透传：只传 `agent` 会让 `ReportSession` 的 thread_id 与中断点归属丢失，
    并在构造期抛 `TypeError`（真实冒烟发现，见 auto-042 验证记录 8）。
    """
    if agent is None:
        if agent_factory is not None:
            agent = agent_factory(profile, ctx)
        elif runtime is not None:
            agent = default_agent_factory(profile, ctx, runtime)
        else:
            raise ValueError("build_runner 需要 runtime，或显式提供 agent/agent_factory")
    return KernelRunner(profile, ctx, agent=agent, view_factory=view_factory,
                        config_factory=config_factory,
                        resume_builder=resume_builder,
                        interrupt_reader=interrupt_reader)


def default_agent_factory(profile: Profile, ctx: RunContext, runtime: AgentRuntime) -> Any:
    if profile.artifact == "report":
        return _deep_agent(profile, ctx, runtime)
    return _chat_agent(profile, ctx, runtime)


def _chat_agent(profile: Profile, ctx: RunContext, runtime: AgentRuntime) -> Any:
    from langchain.agents import create_agent

    return create_agent(model=runtime.model_factory(),
                        tools=build_tools(profile, ctx, runtime.tool_factory),
                        system_prompt=runtime.conversation_prompt)


def _deep_agent(profile: Profile, ctx: RunContext, runtime: AgentRuntime) -> Any:
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
    from langgraph.checkpoint.memory import MemorySaver

    from kernel.profile import MIDDLEWARE_PLAN_GATE

    interrupt_on = {}
    if MIDDLEWARE_PLAN_GATE in profile.middleware:
        interrupt_on = {"submit_analysis_plan": InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"])}
    return create_deep_agent(
        model=runtime.model_factory(),
        tools=build_tools(profile, ctx, runtime.tool_factory),
        system_prompt=runtime.report_prompt,
        backend=FilesystemBackend(root_dir=runtime.skills_dir),
        skills=skill_paths(profile, runtime.skills_dir),
        permissions=skill_permissions(),
        interrupt_on=interrupt_on,
        checkpointer=MemorySaver())
