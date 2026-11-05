"""小窗口真实 MCP 冒烟；会消耗搜索 API 配额，不是离线测试。"""
import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(args):
    async with streamablehttp_client(args.url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "product_timeline_research" in {t.name for t in tools.tools}
            result = await session.call_tool("product_timeline_research", {
                "brand": args.brand, "product": args.product, "aspects": ["tech"],
                "time_from": args.time_from, "time_to": args.time_to})
            summary = json.loads(next(c.text for c in result.content if c.type == "text"))
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            assert not result.isError and summary["status"] in ("ok", "empty"), summary
            assert "events" not in summary
            path = Path(summary["output_path"])
            timeline = json.loads(path.read_text(encoding="utf-8"))
            assert timeline["meta"]["search_provider"] == "volcengine"
            assert all(q["ok"] for q in timeline["meta"]["query_stats"])
            assert path.with_suffix(".txt").exists()
            print("MCP / 搜索 / JSON+TXT 验证通过；不代表事件质量已人工验收。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8878/mcp")
    parser.add_argument("--brand", default="小米")
    parser.add_argument("--product", default="SU7")
    parser.add_argument("--time-from", default="2026-08-01")
    parser.add_argument("--time-to", default="2026-08-31")
    asyncio.run(run(parser.parse_args()))
