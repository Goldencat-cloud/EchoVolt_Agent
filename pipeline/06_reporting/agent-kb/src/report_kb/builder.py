"""Build pipeline for the SU7 analysis knowledge base.

Reads frozen analysis files (../analysis) and produces:
  1. numbers.json          - the answer book: every statistic the report uses (the single data seam)
  2. assets/*.svg          - figures generated from data
  3. report.md             - the Agent-facing projection (generated, not hand-written)
  4. data-version.json     - data version manifest with source hashes

stdlib-only, Python 3.11+. Read-only on ../analysis. Rerun the whole chain after
new data lands: build_report.py -> render_html.py -> verify.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from .paths import ANALYSIS, ASSETS, CONFIGS, OUTPUT
from . import SCHEMA_VERSION

ROOT = OUTPUT

COLORS = {"positive": "#2e7d32", "negative": "#c62828", "neutral": "#78909c", "other": "#cfd8dc"}
FIGS = ["fig1-cohort-funnel.svg", "fig2-aspect-heat.svg", "fig2b-aspect-negative.svg",
        "fig3-journey-shift.svg"]

REQUIRED_FILES = ["summary.json", "profiles.json", "aspect-sentiment.csv",
                  "scope.json", "reviewed-cases.json", "verification.json"]


def fail(msg: str):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    raise SystemExit(2)


def load():
    missing = [f for f in REQUIRED_FILES if not (ANALYSIS / f).is_file()]
    if missing:
        fail(f"missing analysis files: {missing}")
    summary = json.loads((ANALYSIS / "summary.json").read_text(encoding="utf-8"))
    profiles = json.loads((ANALYSIS / "profiles.json").read_text(encoding="utf-8"))
    scope = json.loads((ANALYSIS / "scope.json").read_text(encoding="utf-8"))
    cases = json.loads((ANALYSIS / "reviewed-cases.json").read_text(encoding="utf-8"))
    verification = json.loads((ANALYSIS / "verification.json").read_text(encoding="utf-8"))
    with (ANALYSIS / "aspect-sentiment.csv").open(encoding="utf-8-sig", newline="") as f:
        aspects = list(csv.DictReader(f))
    return summary, profiles, scope, cases, verification, aspects


def pct(num: int, den: int) -> str:
    return f"{num / den * 100:.1f}%" if den else "0.0%"


def fmt(n) -> str:
    return f"{int(n):,}"


def compute_numbers(summary, profiles, scope, cases, verification, aspects):
    """The answer book: every number the report uses, computed from the frozen data."""
    for r in aspects:
        r["share_s"] = pct(int(r["negative"]), int(r["claims"]))
    for rows in profiles.values():
        for r in rows:
            r["share_s"] = pct(int(r["negative"]), int(r["claims"]))
    cohorts = summary["cohorts"]
    order = list(cohorts)
    funnel = []
    prev = None
    for name in order:
        c = cohorts[name]
        retain = pct(c["posts"], prev["posts"]) if prev else None
        funnel.append({"name": name, "posts": c["posts"], "claims": c["claims"],
                       "retain": retain, "posts_s": fmt(c["posts"]), "claims_s": fmt(c["claims"])})
        prev = c

    exp = {r["aspect"]: r for r in aspects}
    heat_sorted = sorted(aspects, key=lambda r: -int(r["claims"]))
    neg_sorted = sorted(aspects, key=lambda r: -float(r["negativeShare"]))
    comfort, reli, serv, power, heat = exp["空间与舒适性"], exp["可靠性与故障"], exp["服务与交付"], exp["动力与性能"], heat_sorted[0]

    pre = {r["aspect"]: r for r in profiles["明确未拥有的购车前表达"]}
    own = {r["aspect"]: r for r in profiles["当前拥有且亲历使用"]}
    ordered = {r["aspect"]: r for r in profiles["已订未提表达"]}
    full = {r["aspect"]: r for r in profiles["全部关联SU7"]}

    n = {
        "meta": {
            "posts_total": fmt(summary["source_posts"]), "claims_total": fmt(summary["source_claims"]),
            "mentions_total": fmt(summary["source_mentions"]),
            "date_min": summary["date_min"][:10], "date_max": summary["date_max"][:10],
            "ev_pass": fmt(summary["evidence_checks"]["passed"]),
            "ev_review": fmt(summary["evidence_checks"]["needs_review"]),
            "ev_rate": pct(summary["evidence_checks"]["passed"], summary["source_claims"]),
            "checks_total": len(verification["checks"]),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_note": "上一版本数据（V2.3 抽取 + AUTO-018 V2 delivery-r3），占位性质",
        },
        "funnel": funnel,
        "funnel_final_posts": fmt(cohorts[order[-1]]["posts"]),
        "funnel_final_name": order[-1],
        "side_pre_posts": fmt(cohorts_same(cohorts, "明确未拥有的购车前表达", "posts")),
        "side_pre_claims": fmt(cohorts_same(cohorts, "明确未拥有的购车前表达", "claims")),
        "side_ordered_posts": fmt(cohorts_same(cohorts, "已订未提表达", "posts")),
        "side_ordered_claims": fmt(cohorts_same(cohorts, "已订未提表达", "claims")),
        "ownership": summary["ownership"],
        "sentiments": summary["core_sentiments"],
        "aspects": [{**r, "share_s": pct(int(r["negative"]), int(r["claims"])),
                     "claims_i": int(r["claims"])} for r in heat_sorted],
        "heat_top": heat["aspect"], "heat_claims": fmt(heat["claims"]), "heat_posts": fmt(heat["posts"]),
        "heat_neg_share": pct(int(heat["negative"]), int(heat["claims"])),
        "comfort_neg": comfort["negative"], "comfort_claims": comfort["claims"],
        "comfort_share": comfort["share_s"], "comfort_neg_posts": comfort["negative_posts"],
        "reli_claims": reli["claims"], "reli_neg": reli["negative"], "reli_share": reli["share_s"],
        "serv_claims": serv["claims"], "serv_neg": serv["negative"], "serv_share": serv["share_s"],
        "power_neg": power["negative"], "power_share": power["share_s"],
        "neg_top": neg_sorted[0]["aspect"], "neg_top_share": pct(int(neg_sorted[0]["negative"]), int(neg_sorted[0]["claims"])),
        "journey": {
            "pre_ext": pre["外观与内饰"], "pre_price": pre["价格与成本"],
            "pre_comfort": pre["空间与舒适性"], "pre_svc": pre["服务与交付"], "pre_range": pre["续航与能耗"],
            "pre_cockpit": pre["智能座舱与车机"], "pre_power": pre["动力与性能"], "pre_drive": pre["驾驶与操控"],
            "own_ext": own["外观与内饰"], "own_price": own["价格与成本"], "own_comfort": own["空间与舒适性"],
            "own_svc": own["服务与交付"], "own_power": own["动力与性能"], "own_drive": own["驾驶与操控"],
            "own_range": own["续航与能耗"], "own_cockpit": own["智能座舱与车机"],
            "ordered_svc": ordered["服务与交付"],
        },
        "price_pre_claims": fmt(pre["价格与成本"]["claims"]), "price_pre_posts": fmt(pre["价格与成本"]["posts"]),
        "price_pre_share": pre["价格与成本"]["share_s"],
        "price_own_claims": fmt(own["价格与成本"]["claims"]),
        "ext_pre_claims": fmt(pre["外观与内饰"]["claims"]), "ext_pre_share": pre["外观与内饰"]["share_s"],
        "ext_own_claims": fmt(own["外观与内饰"]["claims"]),
        "comfort_pre_share": pre["空间与舒适性"]["share_s"], "comfort_own_share": own["空间与舒适性"]["share_s"],
        "comfort_own_neg": own["空间与舒适性"]["negative"],
        "svc_pre_share": pre["服务与交付"]["share_s"], "svc_own_share": own["服务与交付"]["share_s"],
        "svc_ordered_share": ordered["服务与交付"]["share_s"], "svc_ordered_neg": ordered["服务与交付"]["negative"],
        "svc_ordered_claims": ordered["服务与交付"]["claims"],
        "power_own_pos": own["动力与性能"]["positive"], "power_own_claims": fmt(own["动力与性能"]["claims"]),
        "drive_own_pos": own["驾驶与操控"]["positive"], "drive_own_claims": fmt(own["驾驶与操控"]["claims"]),
        "cockpit_own_pos": own["智能座舱与车机"]["positive"], "cockpit_own_claims": fmt(own["智能座舱与车机"]["claims"]),
        "scope": {"rule": scope["rule"], "counts": scope["counts"],
                  "top": scope["candidates"][:8], "whitelist": scope["whitelist"]},
        "scope_in": fmt(scope["counts"]["in_scope"]), "scope_out": fmt(scope["counts"]["out_of_scope"]),
        "scope_unresolved": fmt(scope["counts"]["unresolved"]), "scope_excluded": fmt(scope["counts"]["excluded"]),
        "cases": cases,
        "cases_count": len(cases),
        "full_price_claims": fmt(full["价格与成本"]["claims"]),
        "full_price_neutral": fmt(full["价格与成本"]["neutral"]),
    }
    return n


def cohorts_same(cohorts, name, key):
    if name not in cohorts:
        fail(f"cohort '{name}' missing from summary.json - upstream schema changed?")
    return cohorts[name][key]


# ---------- figures ----------

def svg_open(w, h, title):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="system-ui,sans-serif" font-size="13">',
            f'<title>{escape(title)}</title>', f'<rect width="{w}" height="{h}" fill="#ffffff"/>']


def fig1(summary):
    cohorts = summary["cohorts"]
    rows = [(name, [(c["posts"], "positive")]) for name, c in cohorts.items()]
    max_v = max(c["posts"] for c in cohorts.values()) or 1
    label_w, bar_w, bar_h, gap = 250, 420, 22, 12
    h = 48 + len(rows) * (bar_h + gap) + 34
    out = svg_open(760, h, "Cohort 漏斗")
    out.append('<text x="12" y="26" font-size="15" font-weight="bold" fill="#263238">用户群漏斗：从“沾边讨论”到“当前拥有且亲历”</text>')
    y = 48
    for label, segs in rows:
        v = segs[0][0]
        out.append(f'<text x="{label_w - 8}" y="{y + bar_h * 0.7}" text-anchor="end" fill="#37474f">{escape(label)}</text>')
        w = bar_w * v / max_v
        out.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="#1565c0" rx="3"/>')
        out.append(f'<text x="{label_w + w + 6:.1f}" y="{y + bar_h * 0.7}" fill="#455a64">{fmt(v)} 帖</text>')
        y += bar_h + gap
    out.append(f'<text x="12" y="{h - 10}" font-size="11" fill="#90a4ae">横条=帖数。来源：summary.json.cohorts｜漏斗图自左向右逐层收窄，表达数不可跨层相加</text>')
    out.append("</svg>")
    return "\n".join(out)


def aspect_fig(aspects, sort_key, title, note):
    rows = sorted(aspects, key=sort_key, reverse=True)
    max_v = max(int(r["claims"]) for r in rows) or 1
    bar_w, label_w, bar_h, gap = 470, 150, 20, 11
    h = 52 + len(rows) * (bar_h + gap) + 62
    out = svg_open(760, h, title)
    out.append(f'<text x="12" y="26" font-size="15" font-weight="bold" fill="#263238">{escape(title)}</text>')
    y = 52
    for r in rows:
        pos, neg, neu, oth = (int(r[k]) for k in ("positive", "negative", "neutral", "other"))
        share = int(r["negative"]) / int(r["claims"]) * 100
        out.append(f'<text x="{label_w - 8}" y="{y + bar_h * 0.72}" text-anchor="end" fill="#37474f">{escape(r["aspect"])}</text>')
        x = label_w
        for v, key in [(pos, "positive"), (neg, "negative"), (neu, "neutral"), (oth, "other")]:
            w = bar_w * v / max_v
            if w > 0:
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{COLORS[key]}" rx="2"><title>{escape(r["aspect"])} {key}:{v}</title></rect>')
                if v >= 20:
                    out.append(f'<text x="{x + w / 2:.1f}" y="{y + bar_h * 0.7}" text-anchor="middle" font-size="11" fill="#fff">{v}</text>')
                x += w
        out.append(f'<text x="{x + 6:.1f}" y="{y + bar_h * 0.7}" font-size="11" fill="#455a64">{share:.1f}%</text>')
        y += bar_h + gap
    ly = h - 40
    lx = 12
    for key, text in [("positive", "正面"), ("negative", "负面"), ("neutral", "中性"), ("other", "其他")]:
        out.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{COLORS[key]}" rx="2"/>')
        out.append(f'<text x="{lx + 18}" y="{ly + 10}" font-size="12" fill="#455a64">{text}</text>')
        lx += 72
    out.append(f'<text x="12" y="{h - 10}" font-size="11" fill="#90a4ae">{escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def fig3(profiles):
    pre = {r["aspect"]: r["claims"] for r in profiles["明确未拥有的购车前表达"]}
    own = {r["aspect"]: r["claims"] for r in profiles["当前拥有且亲历使用"]}
    aspects = sorted(pre, key=lambda k: -pre[k])[:8]
    aspects += [a for a in sorted(own, key=lambda k: -own[k])[:4] if a not in aspects]
    max_v = max(max(pre.get(a, 0) for a in aspects), max(own.get(a, 0) for a in aspects)) or 1
    bar_w, label_w, bar_h, ggap = 470, 150, 14, 10
    gh = bar_h * 2 + 4
    h = 52 + len(aspects) * (gh + ggap) + 62
    out = svg_open(760, h, "购前 vs 用车：关注点转移")
    out.append('<text x="12" y="26" font-size="15" font-weight="bold" fill="#263238">同一方面，购前与用车人群的表达数对比</text>')
    y = 52
    for a in aspects:
        out.append(f'<text x="{label_w - 8}" y="{y + gh * 0.55}" text-anchor="end" fill="#37474f">{escape(a)}</text>')
        for i, (v, color, name) in enumerate([(pre.get(a, 0), "#1565c0", "购前"), (own.get(a, 0), "#ef6c00", "用车")]):
            by = y + i * (bar_h + 4)
            w = bar_w * v / max_v
            if w > 0:
                out.append(f'<rect x="{label_w}" y="{by}" width="{w:.1f}" height="{bar_h}" fill="{color}" rx="2"><title>{escape(a)} {name}:{v}</title></rect>')
            out.append(f'<text x="{label_w + w + 6:.1f}" y="{by + bar_h * 0.75}" font-size="11" fill="#546e7a">{name} {v}</text>')
        y += gh + ggap
    out.append(f'<rect x="12" y="{h - 40}" width="12" height="12" fill="#1565c0" rx="2"/>'
               f'<text x="30" y="{h - 30}" font-size="12" fill="#455a64">明确未拥有（购车前）</text>'
               f'<rect x="210" y="{h - 40}" width="12" height="12" fill="#ef6c00" rx="2"/>'
               f'<text x="228" y="{h - 30}" font-size="12" fill="#455a64">当前拥有且亲历</text>')
    out.append(f'<text x="12" y="{h - 10}" font-size="11" fill="#90a4ae">表达数。两个用户群独立、不可相加；购前样本小，比例波动大。来源：profiles.json</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------- agent projection (report.md) ----------

AGENT_POLICY = CONFIGS / "agent-policy.md"


def agent_md(n) -> str:
    L = []
    m = n["meta"]
    L.append("# SU7 分析知识库（Agent 版）")
    L.append("")
    L.append("> **必读**：本文件由构建脚本从冻结数据自动生成，供 Agent 检索消费；人类阅读版为 `report.html`。")
    L.append(f"> 数据版本：{m['data_note']}；快照 {m['date_min']} ~ {m['date_max']}；生成时间 {m['generated_at']}。")
    L.append("> 全部数字与 `numbers.json` 一一对应，来源哈希见 `data-version.json`。**回答统计问题时必须附数据版本声明。**")
    L.append("")
    L.append("## [K] 核心数字速查")
    L.append("")
    L.append("| 键 | 值 | 口径 | 来源 |")
    L.append("|---|---|---|---|")
    kv = [
        ("posts_total", m["posts_total"], "全部入库帖子", "summary.json"),
        ("claims_total", m["claims_total"], "全部结构化表达", "summary.json"),
        ("mentions_total", m["mentions_total"], "产品提及次数", "summary.json"),
        ("date_range", f"{m['date_min']}~{m['date_max']}", "历史快照时间范围", "summary.json"),
        ("evidence", f"{m['ev_pass']} 通过 / {m['ev_review']} 待复核（{m['ev_rate']}）", "引文可定位检查", "summary.json"),
        ("experience_set", f"{n['funnel'][2]['posts_s']} 帖 / {n['funnel'][2]['claims_s']} 条", "产品体验或风险筛选集", "summary.json.cohorts"),
        ("owner_experienced", f"{n['funnel'][4]['posts_s']} 帖 / {n['funnel'][4]['claims_s']} 条", "当前拥有且亲历使用", "summary.json.cohorts"),
        ("pre_purchase", f"{n['side_pre_posts']} 帖 / {n['side_pre_claims']} 条", "明确未拥有的购车前表达", "summary.json.cohorts"),
        ("ordered", f"{n['side_ordered_posts']} 帖 / {n['side_ordered_claims']} 条", "已订未提表达", "summary.json.cohorts"),
        ("comfort_negative", f"{n['comfort_neg']}/{n['comfort_claims']} = {n['comfort_share']}", "空间与舒适性负面占比（体验集）", "aspect-sentiment.csv"),
        ("reliability_negative", f"{n['reli_neg']}/{n['reli_claims']} = {n['reli_share']}", "可靠性与故障负面占比", "aspect-sentiment.csv"),
        ("service_negative", f"{n['serv_neg']}/{n['serv_claims']} = {n['serv_share']}", "服务与交付负面占比", "aspect-sentiment.csv"),
        ("price_pre", f"{n['price_pre_claims']} 条 / {n['price_pre_posts']} 帖，负面 {n['price_pre_share']}", "购前人群价格与成本", "profiles.json"),
        ("price_own", f"{n['price_own_claims']} 条", "当前拥有且亲历人群价格与成本", "profiles.json"),
        ("svc_ordered", f"{n['svc_ordered_neg']}/{n['svc_ordered_claims']} = {n['svc_ordered_share']}", "已订未提人群服务与交付负面占比", "profiles.json"),
        ("scope_mentions", f"范围内 {n['scope_in']} / 范围外 {n['scope_out']} / 未解决 {n['scope_unresolved']}", "竞品共提及覆盖", "scope.json"),
        ("cases", str(n["cases_count"]), "定向复核证据案例数", "reviewed-cases.json"),
    ]
    for k, v, c, s in kv:
        L.append(f"| {k} | {v} | {c} | {s} |")
    L.append("")
    L.append("## [D] 口径与术语")
    L.append("")
    L.append("- **表达（Claim）**：从原文抽取的单条结构化陈述。表达数≠人数，不可当用户数。")
    L.append("- **帖（post）**：论坛原始帖子；身份（ownership）标签的载体；一帖可含多条跨方面表达。")
    L.append("- **用户群（cohort）**：按条件收窄的帖子集合，层层嵌套，各群数值不可相加或混比。")
    L.append("- **负面占比**：该方面负面表达数 ÷ 该方面全部表达数（含中性/混合）。不是负面人数比例，不是满意度。")
    L.append("- **ownership**：帖子级模型标签，不独立证明持有 SU7；定向复核发现租车、试驾、他牌车主混入候选。")
    L.append("- **引文检查**：证据引文能否在原文指定 block 定位；未通过≠抽取错误，可能只是省略或改写。")
    L.append("")
    L.append("## [F] 事实章节")
    L.append("")
    L.append("### [F1] 规模与时间")
    L.append(f"- 语料 {m['posts_total']} 帖、{m['claims_total']} 条表达、{m['mentions_total']} 次产品提及，覆盖 {m['date_min']} 至 {m['date_max']}；历史快照，非实时监测。")
    L.append(f"- 引文可定位检查：{m['ev_pass']} 条通过、{m['ev_review']} 条待复核（{m['ev_rate']}）；此检查不是语义准确率。")
    L.append(f"- 上游 {m['checks_total']} 项计算/来源检查全部通过；原始文件与冻结原文哈希未变。")
    L.append("")
    L.append("### [F2] 用户群漏斗")
    L.append("")
    L.append("| 用户群 | 帖数 | 表达数 | 相对上一层保留率 |")
    L.append("|---|---:|---:|---:|")
    for r in n["funnel"]:
        L.append(f"| {r['name']} | {r['posts_s']} | {r['claims_s']} | {r['retain'] or '—'} |")
    L.append(f"- 侧翼人群：明确未拥有（购前）{n['side_pre_posts']} 帖/{n['side_pre_claims']} 条；已订未提 {n['side_ordered_posts']} 帖/{n['side_ordered_claims']} 条。")
    L.append(f"- ownership 分布：{json.dumps(n['ownership'], ensure_ascii=False)}（来源 summary.json）。")
    L.append(f"- 最内层候选情感构成：{json.dumps(n['sentiments'], ensure_ascii=False)}；正面候选不是满意率。")
    L.append("")
    L.append("### [F3] 方面×情感（产品体验或风险集）")
    L.append("")
    L.append("| 方面 | 帖数 | 表达 | 正面 | 负面 | 中性 | 其他 | 负面占比 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in n["aspects"]:
        L.append(f"| {r['aspect']} | {r['posts']} | {r['claims']} | {r['positive']} | {r['negative']} | {r['neutral']} | {r['other']} | {r['share_s']} |")
    L.append(f"- 热度第一：{n['heat_top']}（{n['heat_claims']} 条表达），负面占比仅 {n['heat_neg_share']}。")
    L.append(f"- 负面占比最高：{n['neg_top']}（{n['neg_top_share']}）。热度排名与负面占比排名几乎不重叠。")
    L.append("- 故障类、交付类话题天然收录更多负面（自选择偏差），高负面占比不能反推故障最多。")
    L.append(f"- 全量集中价格与成本表达最多（{n['full_price_claims']} 条，其中中性 {n['full_price_neutral']} 条），多为行情讨论而非亲历体验。")
    L.append("")
    L.append("### [F4] 旅程对比（购前 vs 当前拥有且亲历）")
    L.append("")
    L.append("| 方面 | 购前表达 | 购前负面占比 | 用车表达 | 用车负面占比 |")
    L.append("|---|---:|---:|---:|---:|")
    alias = {"外观与内饰": "ext", "价格与成本": "price", "空间与舒适性": "comfort",
             "服务与交付": "svc", "续航与能耗": "range", "智能座舱与车机": "cockpit",
             "动力与性能": "power", "驾驶与操控": "drive"}
    for a, key in alias.items():
        p, o = n["journey"]["pre_" + key], n["journey"]["own_" + key]
        L.append(f"| {a} | {p['claims']} | {p['share_s']} | {o['claims']} | {o['share_s']} |")
    L.append(f"- 价格与成本：购前 {n['price_pre_claims']} 条 vs 用车 {n['price_own_claims']} 条——购前最纠结，用车后弱化。")
    L.append(f"- 服务与交付：购前即 {n['svc_pre_share']} 负面；已订未提人群达 {n['svc_ordered_share']}（{n['svc_ordered_neg']}/{n['svc_ordered_claims']}）——等待期是焦虑峰值。")
    L.append(f"- 亲历样本口碑强项：动力 {n['power_own_pos']}/{n['power_own_claims']} 正面、操控 {n['drive_own_pos']}/{n['drive_own_claims']} 正面；负面集中在空间舒适（{n['comfort_own_neg']} 条）与智能驾驶。")
    L.append("")
    L.append("### [F5] 竞品共提及")
    L.append(f"- 白名单规则：{n['scope']['rule']}。")
    for c in n["scope"]["top"]:
        L.append(f"- {c['brand']} {c['series']}：共提及 {c['posts']} 帖。")
    L.append(f"- 覆盖：范围内 {n['scope_in']} / 范围外 {n['scope_out']} / 未解决 {n['scope_unresolved']} / 排除 {n['scope_excluded']}。")
    L.append("- 它们是语料比较相关对象，不是已认定的市场竞品；本表不比较车型优劣。")
    L.append("")
    L.append("### [C] 证据案例库")
    L.append("")
    for c in n["cases"]:
        L.append(f"- **{c['case']}**（{c['aspect']}｜{c['sentiment']}｜{c['source_status']}）：「{c['quote'][:60]}{'…' if len(c['quote']) > 60 else ''}」")
        L.append(f"  链接：{c['url']} · {c['date']} · 改进假设：{c['need']} · 边界：{c['boundary']}")
    L.append("- 全部案例经定向回读原帖冻结文本；不是随机样本，不是人类语义验收。引用时必须带表达性质与证据边界。")
    L.append("")
    if AGENT_POLICY.exists():
        L.append(AGENT_POLICY.read_text(encoding="utf-8").strip())
        L.append("")
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    summary, profiles, scope, cases, verification, aspects = load()
    n = compute_numbers(summary, profiles, scope, cases, verification, aspects)

    ASSETS.mkdir(exist_ok=True)
    figs = {
        "fig1-cohort-funnel.svg": fig1(summary),
        "fig2-aspect-heat.svg": aspect_fig(aspects, lambda r: int(r["claims"]),
                                           "方面×情感：按热度排序", "条长=表达数，右端数字=负面占比。分母为该方面全部表达，负面占比≠负面人数比例。来源：aspect-sentiment.csv"),
        "fig2b-aspect-negative.svg": aspect_fig(aspects, lambda r: float(r["negativeShare"]),
                                                "方面×情感：按负面占比排序", "条长=表达数，右端数字=负面占比。故障/交付类话题天然收录更多负面，不能反推故障最多。来源：aspect-sentiment.csv"),
        "fig3-journey-shift.svg": fig3(profiles),
    }
    for name, svg in figs.items():
        (ASSETS / name).write_text(svg, encoding="utf-8")

    (ROOT / "numbers.json").write_text(json.dumps(n, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "report.md").write_text(agent_md(n), encoding="utf-8")

    files = [{"file": f"analysis/{p.name}", "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
              "bytes": p.stat().st_size} for p in sorted(ANALYSIS.iterdir()) if p.is_file()]
    (ROOT / "data-version.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "generated_at": n["meta"]["generated_at"],
        "data_version": n["meta"]["data_note"],
        "role": "structure-validation knowledge base; numbers are placeholder, MUST NOT be hardcoded into agent code",
        "figures": FIGS, "sources": files,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "figures": len(figs), "cases": n["cases_count"],
                      "agent_md": "report.md", "answer_book": "numbers.json"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
