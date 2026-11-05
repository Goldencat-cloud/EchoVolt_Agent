"""价值层评估脚本固化（task 4.3，评估与优化方案 E2a/E2b）。

两个检验，全部数字可从仓库复现（替代初版 ADR-11 中未入库的评估）：

A. 放大倍数伪事件对照（检验"事件预测评论量放大"是否优于随机）
   - 真实事件：amp = 事件±W 天评论量 / (全期日均评论量 × 窗口天数)
   - 伪事件：随机日期同法计算，重复 N 组试验，得到伪事件中位数的分布
   - 报告：真实中位数、伪事件中位数分布与 p 值（伪事件试验中位数 ≥ 真实中位数的比例）、
     ≥2x 占比对照

B. 波峰对齐 + 随机日期基线（检验"事件解释波峰"，E2b 硬要求含对照行）
   - 真实波峰：评论量 Top-N 的"局部峰值日"（峰值间隔 ≥ sep 天），
     统计落在事件±W 天内的命中率
   - 基线：均匀随机日期的同口径命中率（必须同表报告）
   - 另报告日历覆盖率（±W 天内有事件的日子占比），用于判断命中率是否平凡

用法（工具根目录 event-timeline-research/，已激活 venv）：
  python scripts/eval_influence.py
  python scripts/eval_influence.py --pseudo 500 --window 7 --peak-top 15
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # <工具根目录>/scripts -> 根
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_EVENTS = ROOT / "outputs" / "research" / "小米_SU7_timeline.json"
DEFAULT_CORPUS = ROOT / "data" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"
DEFAULT_OUT = ROOT / "outputs" / "eval" / "influence_eval.json"


def load_daily_counts(corpus: Path) -> tuple[dict[date, int], int]:
    df = pd.read_csv(corpus, usecols=["post_id", "created_at"], parse_dates=["created_at"])
    df = df.dropna(subset=["created_at"])
    counts = df["created_at"].dt.date.value_counts()
    day_counts = {d: int(c) for d, c in counts.items()}
    return day_counts, len(df)


def window_hit(events: list[date], d: date, window: int) -> bool:
    return any(abs((e - d).days) <= window for e in events)


def amp_ratio(day_counts: dict[date, int], d: date, window: int, mean_daily: float) -> float:
    actual = sum(day_counts.get(d + timedelta(days=o), 0) for o in range(-window, window + 1))
    expected = mean_daily * (2 * window + 1)
    return actual / expected if expected > 0 else 0.0


def find_peaks(day_counts: dict[date, int], top_n: int, sep_days: int) -> list[date]:
    """局部峰值日（严格高于两侧邻日），按评论量降序选 Top-N，峰值间隔 >= sep_days。"""
    days = sorted(day_counts)
    peaks: list[tuple[int, date]] = []
    for i, d in enumerate(days):
        c = day_counts[d]
        left = day_counts.get(days[i - 1], 0) if i > 0 else 0
        right = day_counts.get(days[i + 1], 0) if i + 1 < len(days) else 0
        if c > left and c > right:
            peaks.append((c, d))
    peaks.sort(key=lambda x: -x[0])
    selected: list[date] = []
    for _, d in peaks:
        if all(abs((d - s).days) >= sep_days for s in selected):
            selected.append(d)
            if len(selected) >= top_n:
                break
    return sorted(selected)


def main() -> int:
    ap = argparse.ArgumentParser(description="价值层评估：伪事件对照 + 波峰对齐含随机基线")
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--pseudo", type=int, default=300, help="伪事件试验组数 / 随机基线抽样数")
    ap.add_argument("--window", type=int, default=7, help="事件±窗口天数")
    ap.add_argument("--peak-top", type=int, default=15)
    ap.add_argument("--peak-sep", type=int, default=14, help="波峰最小间隔天数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    rng = random.Random(args.seed)

    t = json.load(open(args.events, encoding="utf-8"))
    day_counts, total_comments = load_daily_counts(Path(args.corpus))
    d_min, d_max = min(day_counts), max(day_counts)
    span_days = (d_max - d_min).days + 1
    mean_daily = total_comments / span_days

    events = []
    dropped = 0
    for e in t["events"]:
        raw = e.get("event_date")
        if not raw:
            dropped += 1
            continue
        d = date.fromisoformat(raw[:10])
        if not (d_min <= d <= d_max):
            dropped += 1
            continue
        events.append(d)
    if not events:
        print("无有效事件（日期缺失或全部在语料时间范围外），退出", file=sys.stderr)
        return 1

    def random_day() -> date:
        return d_min + timedelta(days=rng.randint(0, span_days - 1))

    # 事件纪元：评论量随时间剧烈不均（2024-03 起才放量），全程均匀抽伪事件会
    # 把低活跃早期算进基线、人为压低伪事件倍数。故检验 A 的伪事件与检验 B 的
    # 纪元基线均在 [min(事件)-W, max(事件)+W] 内抽取，控制时期混杂。
    era_start = max(d_min, min(events) - timedelta(days=args.window))
    era_end = min(d_max, max(events) + timedelta(days=args.window))
    era_days = (era_end - era_start).days + 1

    def random_era_day() -> date:
        return era_start + timedelta(days=rng.randint(0, era_days - 1))

    # ---- 检验 A：放大倍数伪事件对照 ----
    real_amps = [amp_ratio(day_counts, d, args.window, mean_daily) for d in events]
    real_median = sorted(real_amps)[len(real_amps) // 2]
    real_ge2 = sum(1 for a in real_amps if a >= 2.0) / len(real_amps)

    pseudo_trial_medians, pseudo_all_amps = [], []
    for _ in range(args.pseudo):
        amps = [amp_ratio(day_counts, random_era_day(), args.window, mean_daily)
                for _ in range(len(events))]
        pseudo_trial_medians.append(sorted(amps)[len(amps) // 2])
        pseudo_all_amps.extend(amps)
    pseudo_median = sorted(pseudo_trial_medians)[len(pseudo_trial_medians) // 2]
    p_value = sum(1 for m in pseudo_trial_medians if m >= real_median) / len(pseudo_trial_medians)
    pseudo_ge2 = sum(1 for a in pseudo_all_amps if a >= 2.0) / len(pseudo_all_amps)

    # ---- 检验 B：波峰对齐 + 随机基线（同表对照，E2b）----
    peaks = find_peaks(day_counts, args.peak_top, args.peak_sep)
    peak_hits = sum(1 for p in peaks if window_hit(events, p, args.window))
    peak_rate = peak_hits / len(peaks) if peaks else 0.0
    baseline_hits = sum(1 for _ in range(args.pseudo)
                        if window_hit(events, random_day(), args.window))
    baseline_rate = baseline_hits / args.pseudo
    era_baseline_hits = sum(1 for _ in range(args.pseudo)
                            if window_hit(events, random_era_day(), args.window))
    era_baseline_rate = era_baseline_hits / args.pseudo
    coverage = sum(1 for i in range(span_days)
                   if window_hit(events, d_min + timedelta(days=i), args.window)) / span_days
    era_coverage = sum(1 for i in range(era_days)
                       if window_hit(events, era_start + timedelta(days=i), args.window)) / era_days

    result = {
        "schema_version": 1,
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "params": {"events_file": str(args.events), "corpus": str(args.corpus),
                   "pseudo_trials": args.pseudo, "window_days": args.window,
                   "peak_top": args.peak_top, "peak_sep_days": args.peak_sep,
                   "seed": args.seed},
        "corpus": {"total_comments": total_comments, "span_days": span_days,
                   "first_day": str(d_min), "last_day": str(d_max),
                   "mean_daily": round(mean_daily, 2)},
        "events_used": len(events), "events_dropped": dropped,
        "test_a_amplification": {
            "real_median": round(real_median, 3),
            "pseudo_median": round(pseudo_median, 3),
            "p_value_median": round(p_value, 4),
            "real_share_ge2x": round(real_ge2, 4),
            "pseudo_share_ge2x": round(pseudo_ge2, 4),
            "real_amps": [round(a, 2) for a in real_amps],
        },
        "test_b_peak_alignment": {
            "peaks_found": len(peaks),
            "peak_days": [str(d) for d in peaks],
            "peak_hit_rate": round(peak_rate, 4),
            "random_baseline_hit_rate": round(baseline_rate, 4),
            "baseline_hits": baseline_hits, "baseline_samples": args.pseudo,
            "era_baseline_hit_rate": round(era_baseline_rate, 4),
            "era_baseline_hits": era_baseline_hits,
            "calendar_coverage_share": round(coverage, 4),
            "era_coverage_share": round(era_coverage, 4),
            "era_start": str(era_start), "era_end": str(era_end),
            "verdict": ("significant" if peak_rate > max(baseline_rate, era_baseline_rate) + 0.1
                        else "trivial_or_inconclusive"),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"语料: {total_comments} 条评论, {span_days} 天 ({d_min} ~ {d_max}), "
          f"日均 {mean_daily:.1f} | 有效事件 {len(events)} 个 (丢弃 {dropped})")
    print(f"\n[检验 A] 放大倍数 (窗口 ±{args.window} 天, 伪事件限定事件纪元 "
          f"{era_start} ~ {era_end})")
    print(f"  真实事件中位数: {real_median:.2f}x | 伪事件中位数: {pseudo_median:.2f}x | "
          f"p={p_value:.3f}")
    print(f"  >=2x 占比: 真实 {real_ge2:.1%} vs 伪事件 {pseudo_ge2:.1%}")
    print(f"\n[检验 B] 波峰对齐 (Top{len(peaks)} 波峰, ±{args.window} 天)")
    print(f"  真实波峰命中率:   {peak_hits}/{len(peaks)} = {peak_rate:.1%}")
    print(f"  随机日期基线(全程): {baseline_hits}/{args.pseudo} = {baseline_rate:.1%}   <-- 对照行")
    print(f"  随机日期基线(纪元): {era_baseline_hits}/{args.pseudo} = {era_baseline_rate:.1%}   <-- 对照行")
    print(f"  日历覆盖率(事件±{args.window}天占全期): {coverage:.1%} | 占纪元: {era_coverage:.1%}")
    print(f"  结论: {result['test_b_peak_alignment']['verdict']}")
    print(f"\n已写入: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
