"""本地部署健康检查：不调用搜索或模型，不输出密钥。"""
import argparse
import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def check(args):
    with httpx.Client(trust_env=False, timeout=5) as client:
        response = client.get(f"http://127.0.0.1:{args.web_port}/api/config")
        response.raise_for_status()
        config = response.json()
        assert set(config) == {"search", "llm", "embedding"}
    async with streamablehttp_client(f"http://127.0.0.1:{args.mcp_port}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "product_timeline_research" in {t.name for t in tools.tools}
    print(json.dumps({"web": "ok", "mcp": "ok", "configured": config}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-port", type=int, default=8879)
    parser.add_argument("--mcp-port", type=int, default=8878)
    asyncio.run(asyncio.wait_for(check(parser.parse_args()), timeout=20))
