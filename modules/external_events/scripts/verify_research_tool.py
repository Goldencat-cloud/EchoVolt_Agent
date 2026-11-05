"""端到端验证（task 3.1）：经 MCP stdio 真实调用一次时间线调研。

流程：读清洗语料 created_at min/max 作时间窗 → stdio 拉起 MCP server →
tools/list → 携带时间窗实调"小米SU7" → 校验返回为摘要且落盘文件结构完整。

运行（工具根目录 event-timeline-research/，已激活 venv）：
  python scripts/verify_research_tool.py
  python scripts/verify_research_tool.py --time-from 2024-03-01 --time-to 2026-10-03
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # <工具根目录>/scripts -> 根
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

CORPUS = ROOT / "data" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"
EXPECTED_FIELDS = {"event_id", "event_date", "date_precision", "date_missing",
                   "event_type", "subtype", "relevance", "title", "summary",
                   "media_coverage", "authority", "sources"}


def corpus_window(corpus: Path) -> tuple[str, str]:
    if not Path(corpus).exists():
        sys.exit(f"语料不存在: {corpus}\n请用 --corpus 指定清洗语料 CSV，"
                 f"或用 --time-from/--time-to 直接给时间窗。")
    df = pd.read_csv(corpus, usecols=["created_at"], parse_dates=["created_at"])
    return df["created_at"].min().strftime("%Y-%m-%d"), df["created_at"].max().strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="事件聚合工具端到端验证（MCP stdio 实调）")
    ap.add_argument("--corpus", default=str(CORPUS), help="清洗语料 CSV（仅需 created_at 列）")
    ap.add_argument("--time-from", default=None, help="时间窗起点 YYYY-MM-DD，缺省由语料推断")
    ap.add_argument("--time-to", default=None, help="时间窗终点 YYYY-MM-DD，缺省由语料推断")
    ap.add_argument("--brand", default="小米")
    ap.add_argument("--product", default="SU7")
    return ap.parse_args()


async def main(args: argparse.Namespace) -> int:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    time_from, time_to = args.time_from, args.time_to
    if not (time_from and time_to):
        time_from, time_to = corpus_window(args.corpus)
    print(f"语料时间窗: {time_from} ~ {time_to}")

    client = MultiServerMCPClient({
        "research": {
            "command": sys.executable,
            "args": ["-m", "mcp_server"],
            "transport": "stdio",
            "env": {**dict(__import__("os").environ), "PYTHONPATH": str(ROOT / "src")},
        }
    })
    tools = await client.get_tools()
    names = [t.name for t in tools]
    print(f"tools/list: {names}")
    assert "product_timeline_research" in names, "工具未注册"

    tool = next(t for t in tools if t.name == "product_timeline_research")
    result = await tool.ainvoke({
        "brand": args.brand, "product": args.product,
        "time_from": time_from, "time_to": time_to,
    })
    if isinstance(result, list) and result and isinstance(result[-1], dict):
        # langchain 工具返回可能被包成 [{"type":"text","text":"<json>"}]
        result = json.loads(result[-1]["text"])
    elif isinstance(result, str):
        result = json.loads(result)
    print(f"工具返回(摘要): {json.dumps(result, ensure_ascii=False)}")

    assert "events" not in result, "违反返回契约：返回值不得包含完整事件列表"
    assert result.get("output_path"), "返回值缺少落盘路径"

    path = Path(result["output_path"])
    assert path.exists(), f"落盘文件不存在: {path}"
    timeline = json.loads(path.read_text(encoding="utf-8"))
    events = timeline["events"]
    print(f"落盘事件数: {len(events)}, status: {timeline['meta']['status']}, "
          f"过滤: {timeline['meta']['filter_stats']}")

    dates = [e["event_date"] for e in events if e["event_date"]]
    assert dates == sorted(dates), "事件未按日期升序"
    assert all(EXPECTED_FIELDS <= set(e) for e in events), "事件字段不完整"
    assert all(e["media_coverage"]["source_count"]
               == len({s["source_domain"] for s in e["sources"]}) for e in events), "source_count 应等于独立域名数"
    assert all(e["authority"] >= 50 for e in events), "存在低于权威门槛的事件"
    assert all(time_from <= d <= time_to for d in dates), "存在窗口外事件"
    print(f"聚合统计: 输入报道 {sum(len(e['sources']) for e in events)} 条 → 事件 {len(events)} 个; "
          f"llm_used={timeline['meta']['llm_used']}, 过滤={timeline['meta']['filter_stats']}")
    print("[PASS] 验收通过：摘要返回契约成立，落盘文件结构完整且全部事件在时间窗内")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
