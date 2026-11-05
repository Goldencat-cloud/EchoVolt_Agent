"""判定员校准集构建与评分（task 4.4，评估与优化方案 E2c）。

目的：resonance 分析的根基是 LLM 判定员（deepseek，同 analyze_resonance.SYS prompt）
对"评论是否与事件相关"的判断，此前从未被校准。本脚本构建校准集并计算判定准确率。

校准方案（用户决策，方案 C——交叉标注 + 20% 人工复核）：
- deepseek（被校准的判定员）先判定；
- GLM（第二个模型，非人类）对全部条目标注，写入 calibration_labels.json；
- 人工复核其中 20%（每 5 条抽 1 条），复核结果回填 label 后重跑 --score。

用法（工具根目录 event-timeline-research/，已激活 venv）：
  python scripts/make_judge_calibration.py --build          # 采样 + deepseek 判定
  python scripts/make_judge_calibration.py --score          # 合并标注并出报告/复核清单
  python scripts/make_judge_calibration.py --score --review-final  # 人工复核回填后终版
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # <工具根目录>/scripts -> 根
sys.path.insert(0, str(ROOT / "src"))

from mcp_server.llm import LLMUnavailable  # noqa: E402

DEFAULT_EVENTS = ROOT / "outputs" / "research" / "小米_SU7_timeline.json"
DEFAULT_CORPUS = ROOT / "data" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"
OUT_SET = ROOT / "outputs" / "eval" / "calibration_set.json"
OUT_LABELS = ROOT / "outputs" / "eval" / "calibration_labels.json"
OUT_REPORT = ROOT / "outputs" / "eval" / "judge_calibration_report.json"
OUT_REVIEW = ROOT / "outputs" / "eval" / "calibration_review.md"


def load_analyze_resonance():
    """按路径加载 analyze_resonance，复用其 SYS prompt 与 llm 接口，避免 prompt 漂移。"""
    path = ROOT / "scripts" / "analyze_resonance.py"
    spec = importlib.util.spec_from_file_location("analyze_resonance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_build(args) -> int:
    ares = load_analyze_resonance()
    t = json.load(open(args.events, encoding="utf-8"))
    events = [e for e in t["events"] if e["event_date"]]
    # 时间轴上均匀取 N 个事件，保证校准集覆盖不同时期/事件类型
    step = max(1, len(events) // args.n_events)
    picked = events[::step][:args.n_events]

    df = pd.read_csv(args.corpus, usecols=["post_id", "created_at", "clean_text",
                                           "text_content", "title"],
                     parse_dates=["created_at"])
    df["day"] = df["created_at"].dt.date
    body = df["clean_text"].fillna("").str.strip()
    body = body.mask(body == "", df["text_content"].fillna("").str.strip())
    df["text"] = (body + " " + df["title"].fillna("")).str.strip()
    df = df[df["text"].str.len() > 10]

    items, rng = [], random.Random(args.seed)
    for e in picked:
        d = pd.Timestamp(e["event_date"])
        b = df[(df["day"] >= (d - timedelta(days=args.window)).date())
               & (df["day"] <= (d - timedelta(days=1)).date())]
        a = df[(df["day"] >= d.date())
               & (df["day"] <= (d + timedelta(days=args.window)).date())]
        pool = pd.concat([b, a])
        if len(pool) < args.per_event:
            continue
        sample = pool.sample(args.per_event, random_state=args.seed)
        verdicts = ares.judge(e, sample)  # deepseek 判定（与 resonance 同一 prompt）
        vmap = {v["id"]: v for v in verdicts if isinstance(v, dict)}
        for i, (_, r) in enumerate(sample.iterrows()):
            v = vmap.get(i, {})
            items.append({
                "id": len(items), "event_id": e["event_id"],
                "event_title": e["title"], "event_date": e["event_date"],
                "window": "before" if r["day"] < d.date() else "after",
                "post_id": r["post_id"], "text": r["text"][:160],
                "judge_related": bool(v.get("related", False)),
                "judge_note": v.get("note", ""),
                "label": None, "label_note": "", "labeler": None,
            })

    result = {"schema_version": 1,
              "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
              "params": {"events_file": str(args.events), "corpus": str(args.corpus),
                         "n_events": args.n_events, "per_event": args.per_event,
                         "window_days": args.window, "seed": args.seed},
              "items": items}
    OUT_SET.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SET, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"校准集已写入: {OUT_SET}（{len(items)} 条，label 待标注方填入 {OUT_LABELS.name}）")
    return 0


def cmd_score(args) -> int:
    data = json.load(open(OUT_SET, encoding="utf-8"))
    labels = json.load(open(OUT_LABELS, encoding="utf-8"))
    if not isinstance(labels, dict):
        print("labels 文件格式应为 {\"<id>\": {\"related\": bool, \"note\": str}}", file=sys.stderr)
        return 1
    merged = 0
    for it in data["items"]:
        lab = labels.get(str(it["id"])) or labels.get(it["id"])
        if lab and isinstance(lab.get("related"), bool):
            it["label"] = lab["related"]
            it["label_note"] = lab.get("note", "")
            it["labeler"] = lab.get("labeler", "GLM-cross")
            merged += 1
    if not merged:
        print("没有任何标注被合并，请先写 calibration_labels.json", file=sys.stderr)
        return 1

    if args.review_final:  # 人工复核回填的标注优先级高于交叉标注
        for it in data["items"]:
            rev = it.get("human_review")
            if rev and isinstance(rev.get("related"), bool):
                it["label"] = rev["related"]
                it["label_note"] = (it["label_note"] + " | 人工复核:" +
                                    rev.get("note", "")).strip(" |")
                it["labeler"] = "human"

    lab_items = [it for it in data["items"] if isinstance(it["label"], bool)]
    agree = sum(1 for it in lab_items if it["label"] == it["judge_related"])
    tp = sum(1 for it in lab_items if it["judge_related"] and it["label"])
    fp = sum(1 for it in lab_items if it["judge_related"] and not it["label"])
    fn = sum(1 for it in lab_items if not it["judge_related"] and it["label"])
    tn = len(lab_items) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    judge_positive = sum(1 for it in lab_items if it["judge_related"]) / len(lab_items)
    label_positive = sum(1 for it in lab_items if it["label"]) / len(lab_items)

    report = {"schema_version": 1,
              "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
              "judge_model": "deepseek(AGENT_MODEL)", "annotator": "GLM-cross",
              "human_review_applied": bool(args.review_final),
              "n_items": len(data["items"]), "n_labeled": len(lab_items),
              "agreement": round(agree / len(lab_items), 4),
              "judge_positive_rate": round(judge_positive, 4),
              "annotator_positive_rate": round(label_positive, 4),
              "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
              "precision": round(precision, 4) if precision is not None else None,
              "recall": round(recall, 4) if recall is not None else None,
              "disagreements": [{"id": it["id"], "event_title": it["event_title"],
                                 "text": it["text"], "judge": it["judge_related"],
                                 "judge_note": it["judge_note"], "label": it["label"],
                                 "label_note": it["label_note"]}
                                for it in lab_items if it["label"] != it["judge_related"]]}
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    review_items = [it for it in data["items"] if it["id"] % 5 == 0]
    lines = ["# 判定员校准——人工复核清单（方案 C：复核 20%）", "",
             f"生成: {report['generated_at']} | 共 {len(data['items'])} 条，复核 {len(review_items)} 条",
             "对每条给出你的判断（相关/不相关 + 理由），回填 calibration_set.json 的 "
             "human_review 字段后重跑 `--score --review-final`。", ""]
    for it in review_items:
        lines += [f"## #{it['id']}（事件: {it['event_title']} @ {it['event_date']}，窗口: {it['window']}）",
                  f"- 评论: {it['text']}",
                  f"- deepseek: {'相关' if it['judge_related'] else '不相关'}（{it['judge_note']}）",
                  f"- 交叉标注: {it['label']}（{it['label_note']}）",
                  "- 人工复核: （待填）", ""]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print(f"标注合并 {merged}/{len(data['items'])} 条 | 一致率 {report['agreement']:.1%} "
          f"| P={report['precision']} R={report['recall']}")
    print(f"分歧 {len(report['disagreements'])} 条（详见报告 disagreements）")
    print(f"报告: {OUT_REPORT}")
    print(f"复核清单（{len(review_items)} 条）: {OUT_REVIEW}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="判定员校准集构建与评分")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--review-final", action="store_true",
                    help="人工复核已回填时使用，复核结果覆盖交叉标注")
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--n-events", type=int, default=10, help="抽取事件数")
    ap.add_argument("--per-event", type=int, default=5, help="每事件评论数")
    ap.add_argument("--window", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.build:
        return cmd_build(args)
    if args.score:
        return cmd_score(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LLMUnavailable as e:
        print(f"配置/服务错误: {e}", file=sys.stderr)
        sys.exit(2)
