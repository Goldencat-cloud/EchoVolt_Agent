"""auto-030 8.4 spike: deepagents 0.7.32 interrupt_on + SkillsMiddleware coexistence.

Fake-model probe (no network, no LLM config) answering three questions from
design D9:
  1. Does an interrupt_on-gated tool call pause the run (checkpointer + thread_id)?
  2. Do the three resume decisions map as designed: confirm→approve /
     edit→edited_action (tool receives edited args) / regenerate→reject
     (model receives rejection feedback)?
  3. Does it coexist with SkillsMiddleware (same create_deep_agent wiring as
     production: skills=[AGENT_SKILLS_DIR] + FilesystemBackend)?

Deterministic; stays in the suite as the regression lock for 8.5.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

HERE = Path(__file__).resolve().parents[1]
AGENT_SKILLS_DIR = HERE / "agent_skills"


@tool
def submit_analysis_plan(plan_json: str) -> str:
    """Submit the analysis plan for human outline review (gated by interrupt_on)."""
    return json.dumps({"accepted": True, "received": plan_json}, ensure_ascii=False)


PLAN_JSON = json.dumps({"workstreams": [{"id": "w1", "question": "q"}]}, ensure_ascii=False)


class _ScriptedModel(GenericFakeChatModel):
    """GenericFakeChatModel + no-op bind_tools (deepagents binds the tool table)."""

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003 — test fake
        return self


def _agent(model_msgs: list[AIMessage]):
    """Agent wired exactly like production, with a scripted fake model."""
    model = _ScriptedModel(messages=iter(model_msgs))
    return create_deep_agent(
        model=model,
        tools=[submit_analysis_plan],
        system_prompt="You must call submit_analysis_plan once, then answer.",
        skills=[str(AGENT_SKILLS_DIR)],
        backend=FilesystemBackend(root_dir=AGENT_SKILLS_DIR),
        interrupt_on={"submit_analysis_plan": True},
        checkpointer=MemorySaver(),
    )


def _run(model_msgs: list[AIMessage], thread_id: str,
         resume: dict | None = None) -> dict:
    """Invoke then (optionally) resume on the SAME agent/checkpointer."""
    agent = _agent(model_msgs)
    cfg = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [HumanMessage("分析 SU7 充电问题")]}, cfg)
    if resume is not None:
        result = agent.invoke(Command(resume=resume), cfg)
    return result


def _interrupted(result: dict) -> bool:
    return bool(result.get("__interrupt__"))


def _tool_messages(result: dict) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


class InterruptOnSpikeTests(unittest.TestCase):
    """D9 方案 B 前置 spike：interrupt 触发 + 三决定 resume + 技能中间件共存。"""

    def _call(self) -> AIMessage:
        return AIMessage(content="", tool_calls=[
            {"name": "submit_analysis_plan", "args": {"plan_json": PLAN_JSON},
             "id": "call_1", "type": "tool_call"}])

    def test_interrupt_pauses_run_and_skills_middleware_present(self):
        result = _run([self._call(), AIMessage(content="done")], "t-approve")
        self.assertTrue(_interrupted(result))
        # SkillsMiddleware coexistence: skills were wired into the same graph
        # (see _agent) and the run still reaches the interrupt cleanly.
        self.assertFalse(_tool_messages(result))

    def test_confirm_maps_to_approve_and_tool_runs(self):
        result = _run([self._call(), AIMessage(content="计划已批准，继续执行")],
                      "t-approve", resume={"decisions": [{"type": "approve"}]})
        self.assertFalse(_interrupted(result))
        tools = _tool_messages(result)
        self.assertEqual(len(tools), 1)
        payload = json.loads(tools[0].content)
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["received"], PLAN_JSON)

    def test_edit_maps_to_edited_action_and_tool_receives_edited_args(self):
        edited = json.dumps({"workstreams": [{"id": "w1", "question": "编辑后的问题"}]},
                            ensure_ascii=False)
        result = _run([self._call(), AIMessage(content="编辑版已接收")],
                      "t-edit",
                      resume={"decisions": [{"type": "edit", "edited_action": {
                          "name": "submit_analysis_plan",
                          "args": {"plan_json": edited}}}]})
        self.assertFalse(_interrupted(result))
        content = _tool_messages(result)[0].content
        # middleware note confirms the edited call is what executed
        self.assertIn("Executed instead: submit_analysis_plan", content)
        # and the tool itself ran with the edited args and returned its payload
        response = content.split("Tool response:\n", 1)[1]
        payload = json.loads(response)
        self.assertEqual(payload["received"], edited)

    def test_regenerate_maps_to_reject_and_model_gets_feedback(self):
        result = _run([self._call(), AIMessage(content="已按反馈重新起草")],
                      "t-reject",
                      resume={"decisions": [{"type": "reject",
                                             "message": "议题太泛，请重出草案"}]})
        self.assertFalse(_interrupted(result))
        tools = _tool_messages(result)
        self.assertEqual(len(tools), 1)
        # rejection feedback is routed back to the model as a tool message
        self.assertIn("重出草案", tools[0].content)
        # and the run finishes with the scripted follow-up answer
        self.assertEqual(result["messages"][-1].content, "已按反馈重新起草")


if __name__ == "__main__":
    unittest.main()

