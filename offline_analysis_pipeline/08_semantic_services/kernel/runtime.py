"""内核运行期依赖：模型、提示词、技能目录与工具构造。

内核只声明"运行一个 agent 需要什么"，由组合根在启动时注入具体实现。
这条边界让 `kernel` 不再反向依赖外层模块，也让内核测试无需真实模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ModelFactory = Callable[[], Any]
ToolFactory = Callable[[dict[str, Any]], list[Any]]


@dataclass(frozen=True)
class AgentRuntime:
    """装配 agent 所需的全部外部能力；缺一项都无法在内核里构造 agent。"""

    model_factory: ModelFactory
    conversation_prompt: str
    report_prompt: str
    skills_dir: Path
    tool_factory: ToolFactory
