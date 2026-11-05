"""AutoInsight 统一 agent 内核（装配、预算、闸门与失败语义）。

`build_runner` 是唯一装配入口（auto-042）；`RunContext` 是唯一运行状态。
对外只暴露这些名字；内部实现文件不承诺稳定。
"""
from kernel.context import (Budget, BudgetExhausted, KernelContractError,
                            RunContext, Step, StepLedger)
from kernel.derive import to_answer_view, to_report_view
from kernel.profile import DELIVERABLE, INTERACTIVE, PROFILES, Profile, get
from kernel.runner import Decision, KernelRunner, Outcome, TurnRequest
from kernel.builder import build_runner, build_tools
from kernel.runtime import AgentRuntime

__all__ = [
    "Budget", "BudgetExhausted", "KernelContractError", "RunContext", "Step",
    "StepLedger", "to_answer_view", "to_report_view", "Profile", "PROFILES",
    "INTERACTIVE", "DELIVERABLE", "get", "Decision", "KernelRunner", "Outcome",
    "TurnRequest", "build_runner", "build_tools", "AgentRuntime",
]
