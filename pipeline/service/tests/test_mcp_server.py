"""MCP adapter tests exercise the shared semantic layer without an MCP host."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import mcp_server
from research import service


class MCPAdapterTests(unittest.TestCase):
    def test_tool_allowlist_is_read_only_and_bounded(self):
        self.assertEqual(mcp_server.TOOL_NAMES, {
            "health", "metric_catalogue", "query_stats", "query_claims",
            "analysis_catalogue", "run_analysis_method"})
        self.assertFalse(any("publish" in name or "python" in name or "sql" in name
                             for name in mcp_server.TOOL_NAMES))

    def test_stats_and_evidence_match_shared_service_contract(self):
        stats = mcp_server.query_stats("空间与舒适性")
        direct = service.query_stats("空间与舒适性")
        self.assertEqual(stats, direct)
        claims = mcp_server.query_claims("空间与舒适性", "负面", limit=2)
        self.assertEqual(claims["data_version"], service.snapshot_version())
        self.assertTrue(all(row["claim_id"] and row["url"] for row in claims["data"]))

    def test_catalogues_define_scope_without_exposing_sql(self):
        metrics = mcp_server.metric_catalogue()
        methods = mcp_server.analysis_catalogue()
        self.assertIn("denominator", metrics["data"]["metrics"]["negativeShare"])
        self.assertIn("journey", metrics["data"]["dimensions"])
        self.assertTrue(methods["data"])
        self.assertTrue(all("sql" not in row for row in methods["data"]))

    def test_method_execution_is_verified_and_does_not_return_sql(self):
        result = mcp_server.run_analysis_method(
            "semantic_aggregate",
            '{"metrics": ["claims"], "dimensions": ["aspect"], "limit": 5}')
        self.assertTrue(result["verification"]["ok"])
        self.assertEqual(result["data_version"], service.snapshot_version())
        self.assertNotIn("sql", result)

    def test_unsupported_methods_and_unbounded_pages_rejected(self):
        with self.assertRaises(ValueError):
            mcp_server.run_analysis_method("arbitrary_sql", "{}")
        with self.assertRaises(ValueError):
            mcp_server.query_claims(limit=10000)

    def test_missing_sdk_fails_explicitly(self):
        try:
            import mcp.server  # noqa: F401
        except ImportError:
            with self.assertRaisesRegex(RuntimeError, "MCP SDK is missing"):
                mcp_server.create_server()

    def test_official_sdk_adapter_registers_only_the_read_only_allowlist(self):
        registered = []
        class FakeServer:
            def __init__(self, name):
                self.name = name
            def tool(self):
                return lambda function: registered.append(function) or function
        parent = types.ModuleType("mcp")
        child = types.ModuleType("mcp.server")
        child.MCPServer = FakeServer
        parent.server = child
        with patch.dict(sys.modules, {"mcp": parent, "mcp.server": child}):
            server = mcp_server.create_server()
        self.assertEqual(server.name, "AutoInsight Research")
        self.assertEqual({function.__name__ for function in registered}, mcp_server.TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
