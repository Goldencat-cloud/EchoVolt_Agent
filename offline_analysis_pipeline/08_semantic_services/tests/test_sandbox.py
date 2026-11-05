"""Sandbox tests: execution works, guards hold, failures carry diagnostics."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_tools
import sandbox


class SandboxTests(unittest.TestCase):
    def test_trivial_code_runs(self):
        out = sandbox.run_code("result = 1")
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["result"], 1)

    def test_pandas_frames_support_attribute_and_key_access(self):
        out = sandbox.run_code(
            "import_text = frames.metrics.sort_values('negative_share', ascending=False)"
            ".head(3)\nresult = import_text[['aspect', 'negative_share']]")
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(len(out["result"]), 3)

    def test_import_is_blocked(self):
        out = sandbox.run_code("import os")
        self.assertFalse(out["ok"])
        self.assertIn("import", out["error"])

    def test_open_call_is_blocked(self):
        out = sandbox.run_code("result = open('x.txt')")
        self.assertFalse(out["ok"])
        self.assertIn("open", out["error"])

    def test_pandas_io_is_patched_out(self):
        out = sandbox.run_code("result = pd.read_csv('secret.csv')")
        self.assertFalse(out["ok"])
        self.assertIn("sandbox", str(out.get("error")))

    def test_syntax_error_is_reported(self):
        out = sandbox.run_code("result = (")
        self.assertFalse(out["ok"])
        self.assertIn("语法错误", out["error"])

    def test_failure_payload_carries_diagnostics(self):
        out = sandbox.run_code("result = frames.nonexistent")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("error"))


class SandboxErrorHintTests(unittest.TestCase):
    """8.8：沙箱失败映射为可执行修复提示 + 预算计数回传。"""

    def _python_tool(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0, "successful_tool_calls": 0,
                   "plan": {"use_python": True, "workstreams": []}}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        return tools["python_analyze"], context

    def _invoke(self, code: str) -> dict:
        tool, _context = self._python_tool()
        return json.loads(tool.invoke({"code": code}))

    def test_keyerror_hint_lists_actual_columns(self):
        payload = self._invoke("result = frames.metrics['不存在列']")
        self.assertFalse(payload["ok"])
        self.assertIn("KeyError", payload.get("error", ""))
        self.assertIn("实际可用列", payload["hint"])
        self.assertIn("aspect", payload["hint"])
        self.assertIn("error_budget_left", payload)

    def test_attributeerror_hint_names_common_members(self):
        payload = self._invoke("result = frames.metrics.grpby('aspect')")
        self.assertFalse(payload["ok"])
        self.assertIn("AttributeError", payload.get("error", ""))
        self.assertIn("groupby", payload["hint"])

    def test_timeout_error_maps_to_split_hint(self):
        hint = agent_tools._sandbox_error_hint({"error": "执行超时（>20s）"})
        self.assertIn("拆成多次小调用", hint)

    def test_empty_result_hint_carries_counts(self):
        payload = self._invoke(
            "result = frames.metrics[frames.metrics['aspect'] == '不存在的议题']")
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertTrue(payload.get("empty_result"))
        self.assertIn("非空", payload["hint"])
        self.assertIn("去重", payload["hint"])

    def test_success_response_carries_budget_counts(self):
        payload = self._invoke("result = 1")
        self.assertTrue(payload["ok"])
        self.assertIn("successful_calls_left", payload)
        self.assertIn("error_budget_left", payload)

    def test_budget_warning_at_80_percent(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0,
                   "successful_tool_calls": int(agent_tools.MAX_SUCCESSFUL_TOOL_CALLS * 0.8) + 1,
                   "plan": {"use_python": True, "workstreams": []}}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        payload = json.loads(tools["python_analyze"].invoke({"code": "result = 1"}))
        self.assertTrue(payload["ok"])
        self.assertIn("budget_warning", payload)


if __name__ == "__main__":
    unittest.main()
