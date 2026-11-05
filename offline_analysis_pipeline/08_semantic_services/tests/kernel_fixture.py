"""内核等价性 fixture：录制格式与录制器。

fixture 记录三样东西，缺一不可：

1. `input`    —— 问题、历史、会话（回放时的输入）
2. `steps`    —— 该轮进入 `verified_steps` 的账本条目（工具调用的产物）
3. `expected` —— **旧实现**在同一账本下产出的响应字典（比对基准）

`source` 区分两种来源：
- `synthetic`：账本条目为构造数据，模型调用被替身替换。用于验证"胶水与派生"
  是否等价，不覆盖统计正确性。
- `live`：真实模型与真实数据产出。当前仓库无冻结快照数据，尚无此类条目。

录制器通过替身驱动旧实现 `agent_engine._run_agent_conversation`，
因此录制与回放都不触网、不调用真实模型。
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

#: auto-030 的历史对话工具排除名单。生产常量已随 auto-042 移除；
#: 保留为「白名单必须与旧排除名单等价」的对照基准。
LEGACY_CONVERSATION_EXCLUDED_TOOLS = frozenset({"submit_report", "python_analyze"})

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "kernel"

MODEL_ENV = {"AI_BASE_URL": "http://fixture.invalid/v1",
             "AI_API_KEY": "fixture-key",
             "AI_MODEL": "fixture-model",
             "AI_DATA_APPROVED": "1"}

TOOL_NAMES = ("semantic_overview", "run_analysis_method", "search_claims",
              "submit_analysis_plan", "search_published_report")


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeAgent:
    """替身 agent：把 fixture 的账本条目写回上下文，返回固定最终文本。"""

    def __init__(self, captured: dict[str, Any], steps: Sequence[Mapping[str, Any]],
                 final_text: str) -> None:
        self._captured = captured
        self._steps = steps
        self._final_text = final_text

    def invoke(self, payload: Any, config: Any = None) -> dict[str, Any]:
        context = self._captured["context"]
        for step in self._steps:
            context.setdefault("verified_steps", []).append(dict(step))
        context["successful_tool_calls"] = len(self._steps)
        return {"messages": [_FakeMessage(self._final_text)]}


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


@contextlib.contextmanager
def old_implementation(steps: Sequence[Mapping[str, Any]], final_text: str,
                       *, tool_errors: int = 0,
                       history: Sequence[Mapping[str, str]] | None = None,
                       session: Mapping[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """用替身驱动 `_run_agent_conversation`，产出与生产同形的响应字典。

    时效性说明（auto-040 之后）：交互链路已接线到内核，本函数现在驱动的是**当前**
    实现。`fixtures/kernel/` 下的 `expected` 全部录制于接线之前，所以回放比对仍然
    以旧实现为基准；但本函数无法再伪造旧实现，只能用于生成"当前实现"的录制。
    新增基准必须来自接线前的提交，不得用本函数补录后声称是等价性证据。
    """
    import agent_engine
    import agent_tools
    import config
    from research import service

    captured: dict[str, Any] = {}
    saved_env = {key: os.environ.get(key) for key in MODEL_ENV}
    os.environ.update(MODEL_ENV)

    real_build_tools = agent_tools.build_tools
    real_model_configured = config.model_configured
    real_model = agent_engine._model
    real_create_agent = None

    def spy_build_tools(context: dict[str, Any]) -> list[Any]:
        captured["context"] = context
        return [_FakeTool(name) for name in TOOL_NAMES]

    def spy_model_configured() -> bool:
        return True

    import langchain.agents as langchain_agents
    real_create_agent = langchain_agents.create_agent
    langchain_agents.create_agent = lambda **kwargs: _FakeAgent(captured, steps, final_text)

    agent_tools.build_tools = spy_build_tools
    config.model_configured = spy_model_configured
    agent_engine._model = lambda: "fixture-model"
    try:
        result = agent_engine._run_agent_conversation(
            "（fixture）",
            [dict(turn) for turn in (history or [])],
            dict(session or {}))
        if tool_errors:
            result["tool_errors"] = tool_errors
        yield result
    finally:
        agent_tools.build_tools = real_build_tools
        config.model_configured = real_model_configured
        agent_engine._model = real_model
        langchain_agents.create_agent = real_create_agent
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def record(case_id: str, question: str, steps: Sequence[Mapping[str, Any]],
           final_text: str, *, source: str = "synthetic",
           history: Sequence[Mapping[str, str]] | None = None,
           session: Mapping[str, Any] | None = None,
           note: str = "") -> dict[str, Any]:
    """录制一条 fixture：输入 + 账本 + 旧实现的响应。"""
    with old_implementation(steps, final_text) as expected:
        payload = {
            "id": case_id,
            "source": source,
            "note": note,
            "input": {"question": question,
                      "history": list(history or []),
                      "session": dict(session or {})},
            "steps": [dict(step) for step in steps],
            "final_text": final_text,
            "expected": expected,
        }
    return payload


def save(fixture: Mapping[str, Any], root: Path | None = None) -> Path:
    directory = Path(root or FIXTURE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{fixture['id']}.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_all(root: Path | None = None) -> list[dict[str, Any]]:
    directory = Path(root or FIXTURE_DIR)
    if not directory.exists():
        return []
    fixtures = []
    for path in sorted(directory.glob("*.json")):
        fixtures.append(json.loads(path.read_text(encoding="utf-8")))
    return fixtures
