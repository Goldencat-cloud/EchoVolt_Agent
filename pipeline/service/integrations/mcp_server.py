"""Read-only MCP adapter over AutoInsight's existing research query layer.

Run with ``python mcp_server.py``. MCP uses stdio so protocol output remains
separate from normal service logs. No filesystem, SQL, Python or publishing
tools are registered here.
"""
from __future__ import annotations

import json
from typing import Any

from research import analysis_methods
from research import service

TOOL_NAMES = frozenset({"health", "metric_catalogue", "query_stats", "query_claims",
                        "analysis_catalogue", "run_analysis_method"})


def health() -> dict[str, Any]:
    """Check service and frozen snapshot availability without model calls."""
    return service.health()


def metric_catalogue() -> dict[str, Any]:
    """Return the canonical metric and dimension catalogue and method mapping."""
    from research import catalog as research_catalog
    return {"data": research_catalog.catalogue(),
            "data_version": service.snapshot_version()}


def query_stats(aspect: str = "") -> dict[str, Any]:
    """Query deterministic full-snapshot metrics for one known aspect or all aspects."""
    result = service.query_stats(aspect or None)
    return result


def query_claims(aspect: str = "", sentiment: str = "", journey: str = "",
                 ownership: str = "", limit: int = 5, offset: int = 0) -> dict[str, Any]:
    """Read a bounded page of curated evidence; results are not population estimates."""
    if not 1 <= int(limit) <= 20 or not 0 <= int(offset) <= 500:
        raise ValueError("limit must be 1..20 and offset 0..500")
    return service.query_claims(aspect=aspect or None, sentiment=sentiment or None,
                                journey=journey or None, ownership=ownership or None,
                                limit=int(limit), offset=int(offset))


def analysis_catalogue() -> dict[str, Any]:
    """Return named, parameterized analysis methods without exposing SQL."""
    return {"data": analysis_methods.catalogue(),
            "data_version": service.snapshot_version()}


def run_analysis_method(method: str, params_json: str = "{}") -> dict[str, Any]:
    """Run one predeclared method with validated parameters; SQL is never accepted."""
    if len(params_json) > 2000:
        raise ValueError("params_json exceeds 2000 characters")
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        raise ValueError("params_json must be valid JSON") from exc
    if not isinstance(params, dict):
        raise ValueError("params_json must be a JSON object")
    result = analysis_methods.run(method, params)
    import verifier
    verdict = verifier.verify_step(result)
    if not verdict["ok"]:
        raise ValueError("analysis result failed deterministic verification")
    public_result = {key: value for key, value in result.items() if key != "sql"}
    public_result.update({"data_version": service.snapshot_version(),
                          "snapshot_hash": service.snapshot_hash(),
                          "verification": verdict})
    return public_result


def create_server():
    """Create the MCP server lazily, keeping ordinary Web installs lightweight."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError("MCP SDK is missing; install requirements.txt") from exc
    server = MCPServer("AutoInsight Research")
    server.tool()(health)
    server.tool()(metric_catalogue)
    server.tool()(query_stats)
    server.tool()(query_claims)
    server.tool()(analysis_catalogue)
    server.tool()(run_analysis_method)
    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
