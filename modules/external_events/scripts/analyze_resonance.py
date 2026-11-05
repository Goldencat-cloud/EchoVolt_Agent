"""事件-评论共鸣分析（task 2.10，ADR-11）。

对事件集中每个事件，取事件前/后 N 天窗口的评论样本，由 LLM（deepseek 兼容端点，
temperature 0）逐条判定"是否真的在讨论该事件"，输出 community_resonance：
相关率差（百分点）+ 判定样例（含 post_id，可回挂原文）。

用法（工具根目录 event-timeline-research/，已激活 venv）：
  python scripts/analyze_resonance.py                     # 全量事件
  python scripts/analyze_resonance.py --min-coverage 10   # 仅高覆盖事件（快）
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # <工具根目录>/scripts -> 根
sys.path.insert(0, str(ROOT / "src"))

from mcp_server import llm as llm_mod  # noqa: E402

DEFAULT_EVENTS = ROOT / "outputs" / "research" / "小米_SU7_timeline.json"
DEFAULT_CORPUS = ROOT / "data" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"

SYS = ("你是论坛评论分析员。判断每条评论是否与给定事件相关:仅当评论直接讨论该事件本身"
       "或其直接影响才算相关;泛泛聊车、聊其他话题不算。"
       "输出严格 JSON 数组:[{\"id\":序号,\"related\":布尔,\"note\":\"≤8字理由\"}],只输出 JSON。")


def judge(event: dict, comments: pd.DataFrame) -> list[dict]:
    items = [{"id": i, "date": str(r["day"]), "text": r["text"][:160]}
             for i, (_, r) in enumerate(comments.iterrows())]
    user = (f"事件: {event['title']}({event['event_date']}) {event['summary'][:120]}\n"
            f"评论列表:\n" + json.dumps(items, ensure_ascii=False))
    content = llm_mod._chat([{"role": "system", "content": SYS},
                             {"role": "user", "content": user}])
    return json.loads(llm_mod._strip_json(content))


def related_rate(arr: list[dict]) -> float:
    return sum(1 for x in arr if x.get("related")) / max(1, len(arr))


def main() -> int:
    ap = argparse.ArgumentParser(description="事件-评论共鸣分析")
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--window", type=int, default=14, help="前后窗口天数")
    ap.add_argument("--sample", type=int, default=40, help="每窗口抽样评论数")
    ap.add_argument("--min-coverage", type=int, default=1,
                    help="仅分析 media_coverage.source_count ≥ 该值的事件")
    ap.add_argument("--min-window-sample", type=int, default=10,
                    help="任一窗口有效样本低于该值则跳过该事件（防相关率按 0%% 虚高，task 4.4）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    t = json.load(open(args.events, encoding="utf-8"))
    events = [e for e in t["events"]
              if e["event_date"] and e["media_coverage"]["source_count"] >= args.min_coverage]

    df = pd.read_csv(args.corpus, usecols=["post_id", "created_at", "clean_text", "text_content", "title"],
                     parse_dates=["created_at"])
    df["day"] = df["created_at"].dt.date
    body = df["clean_text"].fillna("").str.strip()
    body = body.mask(body == "", df["text_content"].fillna("").str.strip())  # clean_text 缺失回退
    df["text"] = (body + " " + df["title"].fillna("")).str.strip()
    df = df[df["text"].str.len() > 4]

    out = []
    skipped = []
    for e in events:
        d = pd.Timestamp(e["event_date"])
        b = df[(df["day"] >= (d - timedelta(days=args.window)).date())
               & (df["day"] <= (d - timedelta(days=1)).date())]
        a = df[(df["day"] >= d.date())
               & (df["day"] <= (d + timedelta(days=args.window)).date())]
        # task 4.4 修复：任一窗口样本不足即跳过——前窗口为空时旧逻辑会把
        # related_rate_before 记为 0%，虚高 resonance（"没讨论"≠"讨论了但不相关"）
        if min(len(b), len(a)) < args.min_window_sample:
            skipped.append({"event_id": e["event_id"], "event_date": e["event_date"],
                            "title": e["title"],
                            "n_before": int(len(b)), "n_after": int(len(a))})
            continue
        bs = b.sample(min(args.sample, len(b)), random_state=args.seed)
        as_ = a.sample(min(args.sample, len(a)), random_state=args.seed)
        arr_b = judge(e, bs) if len(bs) else []
        arr_a = judge(e, as_)
        rb, ra = related_rate(arr_b), related_rate(arr_a)
        examples = [{"post_id": as_.iloc[x["id"]]["post_id"],
                     "text": as_.iloc[x["id"]]["text"][:80],
                     "note": x.get("note", "")}
                    for x in arr_a if x.get("related")][:3]
        out.append({"event_id": e["event_id"], "event_date": e["event_date"],
                    "title": e["title"], "media_coverage": e["media_coverage"],
                    "n_sampled": [len(arr_b), len(arr_a)],
                    "related_rate_before": round(rb, 3), "related_rate_after": round(ra, 3),
                    "resonance_pp": round((ra - rb) * 100, 1), "examples": examples})
        print(f"[{e['event_date']}] {e['title'][:32]:<34} "
              f"相关率 {rb:.0%}→{ra:.0%} (resonance {(ra - rb) * 100:+.1f}pp)")

    out.sort(key=lambda x: -x["resonance_pp"])
    pps = [x["resonance_pp"] for x in out]
    summary = None
    if pps:
        q1, med, q3 = pd.Series(pps).quantile([0.25, 0.5, 0.75]).tolist()
        summary = {"n_events": len(pps), "median_pp": round(med, 1),
                   "q1_pp": round(q1, 1), "q3_pp": round(q3, 1),
                   "mean_pp": round(sum(pps) / len(pps), 1),
                   "share_positive": round(sum(1 for p in pps if p > 0) / len(pps), 3),
                   "n_skipped_low_sample": len(skipped)}
    result = {"schema_version": 2, "window_days": args.window,
              "sample_per_window": args.sample, "generated_at":
                  pd.Timestamp.now().isoformat(timespec="seconds"),
              "summary": summary, "skipped_events": skipped, "events": out}
    out_path = Path(args.events).with_suffix("").with_name(
        Path(args.events).stem + "_resonance.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已写入: {out_path}（{len(out)} 个事件；样例含 post_id 可回挂原文）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except llm_mod.LLMUnavailable as e:
        print(f"配置/服务错误: {e}", file=sys.stderr)
        sys.exit(2)
