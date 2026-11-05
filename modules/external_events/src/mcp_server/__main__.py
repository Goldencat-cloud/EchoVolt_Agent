"""入口：默认 stdio；--http HOST:PORT 切 streamable-http。"""
from __future__ import annotations

import argparse

from .server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="product-timeline-research MCP server")
    parser.add_argument("--http", metavar="HOST:PORT", default=None,
                        help="以 streamable-http 模式启动（缺省 stdio）")
    args = parser.parse_args()
    if args.http:
        host, _, port = args.http.partition(":")
        mcp.settings.host = host or "127.0.0.1"
        mcp.settings.port = int(port or 8000)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
