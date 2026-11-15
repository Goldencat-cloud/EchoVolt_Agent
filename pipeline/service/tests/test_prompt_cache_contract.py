"""Deterministic tests for the static/dynamic prompt cache contract (auto-030 D13).

Locks the KV-cache architecture constraints:
- static prompts (system prompts, action block) contain no volatile values
  (timestamps, dates, job data) and are byte-stable across calls;
- the static prefix is identical for every job — only the task brief varies,
  and it comes after the static action block;
- tool docstrings (part of the request prefix) are byte-stable across builds.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
import agent_tools
import prompts

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|\d{2}:\d{2}:\d{2}")


class StaticPromptTests(unittest.TestCase):
    """Static prompts must be free of volatile values (cache invalidators)."""

    def test_no_timestamps_in_static_prompts(self):
        for name, text in [("deep_analysis", prompts.DEEP_ANALYSIS_SYSTEM),
                           ("action_block", prompts.DEEP_ANALYSIS_ACTION_BLOCK),
                           ("conversation", prompts.CONVERSATION_SYSTEM)]:
            self.assertIsNone(_DATE_RE.search(text),
                              f"{name} contains a date/time literal")

    def test_engine_aliases_point_at_registry(self):
        self.assertEqual(agent_engine.SYSTEM_PROMPT, prompts.DEEP_ANALYSIS_SYSTEM)
        self.assertEqual(agent_engine.CONVERSATION_PROMPT, prompts.CONVERSATION_SYSTEM)

    def test_static_prompts_are_byte_stable(self):
        first = (prompts.DEEP_ANALYSIS_SYSTEM, prompts.CONVERSATION_SYSTEM,
                 prompts.DEEP_ANALYSIS_ACTION_BLOCK)
        second = (prompts.DEEP_ANALYSIS_SYSTEM, prompts.CONVERSATION_SYSTEM,
                  prompts.DEEP_ANALYSIS_ACTION_BLOCK)
        self.assertEqual(first, second)


class OpeningMessagePrefixTests(unittest.TestCase):
    """The only per-job variance starts at the task brief, after static text."""

    def test_static_prefix_identical_across_jobs(self):
        msg_a = agent_engine._opening_message("问题A", None)
        msg_b = agent_engine._opening_message("问题B 是另一个完全不同的问题", None)
        action = prompts.DEEP_ANALYSIS_ACTION_BLOCK
        self.assertTrue(msg_a.startswith(action))
        self.assertTrue(msg_b.startswith(action))
        separator = "\n\n---\n\n"
        self.assertEqual(msg_a.split(separator)[0], msg_b.split(separator)[0])

    def test_dynamic_brief_follows_static_block(self):
        message = agent_engine._opening_message("测试问题", None)
        self.assertLess(message.index(prompts.DEEP_ANALYSIS_ACTION_BLOCK[:20]),
                        message.index("# 任务简报"))
        self.assertIn("# 任务简报", message)


class ToolSchemaStabilityTests(unittest.TestCase):
    """Tool definitions are part of the request prefix; they must not vary."""

    def test_tool_docstrings_byte_stable_across_builds(self):
        ctx_a = {"interactive": True, "submissions": []}
        ctx_b = {"interactive": True, "submissions": []}
        tools_a = {t.name: t for t in agent_tools.build_tools(ctx_a)}
        tools_b = {t.name: t for t in agent_tools.build_tools(ctx_b)}
        self.assertEqual(set(tools_a), set(tools_b))
        for name in tools_a:
            self.assertEqual(tools_a[name].description, tools_b[name].description,
                             f"docstring of {name} varies between builds")




class StaticTextGovernanceTests(unittest.TestCase):
    """auto-032: static agent-facing text carries no snapshot facts, no ticket
IDs, and no restated hard constraints (tool docstrings are the canonical
layer; prompts/skills may only point at them)."""

    _SKILLS_DIR = Path(agent_engine.AGENT_SKILLS_DIR)
    _SNAPSHOT_FACT_PHRASES = ('小米', 'SU7', '临时样本')
    _TICKET_RE = re.compile(r'auto-\d{3}')
    _RESTATED_PHRASES = ('全流程仅此一次', '一次性修正全部字段', '至多 3 次', '最多 3 次',
                         '重复提交已获批')

    def _static_texts(self):
        texts = {
            'prompts:deep_analysis_system': prompts.DEEP_ANALYSIS_SYSTEM,
            'prompts:action_block': prompts.DEEP_ANALYSIS_ACTION_BLOCK,
            'prompts:conversation_system': prompts.CONVERSATION_SYSTEM,
        }
        for skill in sorted(self._SKILLS_DIR.glob('*/SKILL.md')):
            texts[f'skill:{skill.parent.name}'] = skill.read_text(encoding='utf-8')
        return texts

    def test_no_snapshot_facts_in_static_text(self):
        for name, text in self._static_texts().items():
            for phrase in self._SNAPSHOT_FACT_PHRASES:
                self.assertNotIn(phrase, text, f'{name} contains snapshot fact')

    def test_no_ticket_ids_in_static_text(self):
        for name, text in self._static_texts().items():
            self.assertIsNone(self._TICKET_RE.search(text), f'{name} contains a ticket id')

    def test_hard_constraints_not_restated(self):
        for name, text in self._static_texts().items():
            for phrase in self._RESTATED_PHRASES:
                self.assertNotIn(phrase, text, f'{name} restates hard constraint: {phrase}')

    def test_tool_docstrings_still_canonical_layer(self):
        ctx = {'interactive': True, 'submissions': []}
        tools = {t.name: t for t in agent_tools.build_tools(ctx)}
        self.assertIn('整个运行只调用一次', tools['submit_analysis_plan'].description)


if __name__ == "__main__":
    unittest.main()
