"""工具登记契约：全部工具都已登记，白名单以能力为默认值。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel import registry
from kernel.profile import DELIVERABLE, INTERACTIVE

EXPECTED_TOOLS = {
    "semantic_overview", "search_claims", "get_negative_evidence",
    "search_published_report",
    "run_semantic_aggregate", "python_analyze", "submit_analysis_plan", "submit_report",
}


class RegistryTests(unittest.TestCase):
    def test_all_agent_tools_are_registered(self):
        self.assertEqual(set(registry.TOOLS), EXPECTED_TOOLS)

    def test_every_tool_has_a_valid_capability(self):
        for spec in registry.TOOLS.values():
            self.assertIn(spec.capability, registry.VALID_CAPABILITIES)

    def test_registry_matches_agent_tools_build_tools(self):
        """登记表必须与真实工具集同步，否则白名单会静默漏工具。"""
        import agent_tools
        built = {tool.name for tool in agent_tools.build_tools({})}
        self.assertEqual(built, EXPECTED_TOOLS)

    def test_unknown_tool_resolution_fails(self):
        with self.assertRaises(ValueError):
            registry.resolve({"not_a_tool"})

    def test_unknown_capability_fails(self):
        with self.assertRaises(ValueError):
            registry.tools_for({"teleport"})

    def test_capability_expansion(self):
        self.assertEqual(registry.tools_for({registry.CAP_SUBMIT}), {"submit_report"})
        self.assertEqual(registry.tools_for({registry.CAP_PLAN}), {"submit_analysis_plan"})
        self.assertIn("python_analyze", registry.tools_for({registry.CAP_COMPUTE}))

    def test_interactive_excludes_write_capabilities(self):
        self.assertIn("submit_report", DELIVERABLE.tools)
        self.assertIn("python_analyze", DELIVERABLE.tools)
        self.assertNotIn("submit_report", INTERACTIVE.tools)
        self.assertNotIn("python_analyze", INTERACTIVE.tools)

    def test_describe_returns_full_map(self):
        described = registry.describe()
        self.assertEqual(set(described), EXPECTED_TOOLS)
        self.assertEqual(described["run_semantic_aggregate"], registry.CAP_COMPUTE)


if __name__ == "__main__":
    unittest.main()
