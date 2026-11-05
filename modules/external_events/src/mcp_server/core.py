"""复合编排逻辑 v2（task 2.3/2.8，ADR-3/9/10）。

两轮检索（综述种子 + 通用事件切片）→ 漏斗 → 去重 → 归一 → 确定性聚类
→ LLM 忠实改写与分类（可降级）→ 影响力规则打分 → schema v2 事件集。
跨域泛用：品牌/产品词从参数派生；模板、分级、聚合均不预设行业。
"""
from __future__ import annotations

import hashlib
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from . import cluster as cluster_mod
from . import llm as llm_mod
from . import rules as rules_mod
from . import textvec
from .volcengine import VolcengineClient

SCHEMA_VERSION = 3

ASPECTS = ["product", "competitor", "policy", "tech", "public"]

# 跨域通用查询模板：{bp}=品牌+产品连写；{hint}=可选领域提示
OVERVIEW_TEMPLATES = ["{bp} 大事记 时间线", "{bp} 盘点 回顾", "{bp} 发展历程"]
ASPECT_TEMPLATES: dict[str, list[str]] = {
    "product": ["{bp} 发布 上市", "{bp} 价格", "{bp} 更新 升级", "{bp} 召回 质量"],
    "competitor": ["{bp} 竞品 对比"],
    "policy": ["{bp} 行业 政策 监管"],
    "tech": ["{bp} 技术"],
    "public": ["{bp} 舆情 争议", "{bp} 事故 投诉"],
}
# 严格离题判定仅用于这些主题（宽进主题由聚合阶段 LLM 裁决）
_STRICT_ASPECTS = {"product", "overview"}


def build_queries(brand: str, product: str, aspects: list[str],
                  time_from: str | None, time_to: str | None,
                  domain_hint: str | None = None) -> list[dict]:
    bp = f"{brand}{product}".replace(" ", "")
    suffix = f" {domain_hint}" if domain_hint else ""
    years: list[str] = []
    if time_from and time_to:
        try:
            y0, y1 = int(time_from[:4]), int(time_to[:4])
            years = [str(y) for y in range(min(y0, y1), max(y0, y1) + 1)]
        except ValueError:
            years = []

    queries: list[dict] = []
    for tpl in OVERVIEW_TEMPLATES:
        queries.append({"query": tpl.format(bp=bp) + suffix, "aspect": "overview"})
    for aspect in aspects:
        for tpl in ASPECT_TEMPLATES.get(aspect, []):
            base = tpl.format(bp=bp) + suffix
            if years:
                for y in years:
                    queries.append({"query": f"{base} {y}", "aspect": aspect})
            else:
                queries.append({"query": base, "aspect": aspect})
    return queries


def normalize_date(raw: str | None) -> tuple[str | None, str, bool]:
    if not raw:
        return None, "unknown", True
    s = str(raw).strip()
    # 完整 ISO 日期优先，不能把 PublishTime 的日精度截成月初。
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), "day", False
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d"), "day", False
    except (TypeError, ValueError):
        pass
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", s)
    if m:
        try:
            return date(*map(int, m.groups())).isoformat(), "day", False
        except ValueError:
            return None, "unknown", True
    m = re.fullmatch(r"(\d{4})(?:年|[-/])(\d{1,2})月?", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), 1).isoformat(), "month", False
        except ValueError:
            return None, "unknown", True
    m = re.fullmatch(r"(\d{4})年?", s)
    if m:
        try:
            return date(int(m[1]), 1, 1).isoformat(), "year", False
        except ValueError:
            pass
    return None, "unknown", True


def _event_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _in_window(d: str | None, time_from: str | None, time_to: str | None) -> bool:
    if not (time_from and time_to and d):
        return True
    try:
        return date.fromisoformat(time_from) <= date.fromisoformat(d) <= date.fromisoformat(time_to)
    except ValueError:
        return True


def _media_coverage(source_domains: set[str], tiers: list[str]) -> dict:
    """媒体覆盖面（非影响力！可能含投放，真实影响力由分析侧 community_resonance 度量）。"""
    n = len(source_domains)
    max_tier = "T1" if "T1" in tiers else ("T2" if "T2" in tiers else "T3")
    level = "high" if n >= 10 else ("medium" if n >= 3 else "low")
    return {"source_count": n, "max_tier": max_tier, "level": level}


def _authority(members: list[dict], rules: dict) -> int:
    """事件权威分 = 最高来源置信度 + 独立来源印证加成（0/10/15），上限 100。"""
    base = max(m["conf"] for m in members)
    extra = len({m["domain"] for m in members}) - 1
    bonus = 0 if extra <= 0 else (10 if extra == 1 else 15)
    return min(100, base + bonus)


def run(brand: str, product: str, aspects: list[str] | None = None,
        time_from: str | None = None, time_to: str | None = None,
        domain_hint: str | None = None, official_domains: list[str] | None = None,
        client: VolcengineClient | None = None, rules: dict | None = None,
        vectorizer: textvec.Vectorizer | None = None,
        rewriter=None, max_results: int = 8, progress_callback=None) -> dict:
    """执行一次调研，返回完整事件集 dict（schema v2）。rewriter 可注入（默认 llm.rewrite_clusters）。"""
    if time_from:
        date.fromisoformat(time_from)
    if time_to:
        date.fromisoformat(time_to)
    if time_from and time_to and time_from > time_to:
        raise ValueError("时间窗起点不能晚于终点")
    rules = rules or rules_mod.load_rules()
    client = client or VolcengineClient()
    vectorizer = vectorizer or textvec.Vectorizer()
    rewriter = rewriter or llm_mod.rewrite_clusters
    aspects = [a for a in (aspects or ASPECTS) if a in ASPECTS] or list(ASPECTS)
    tokens = rules_mod.brand_tokens(brand, product)
    official = frozenset(d.lower() for d in (official_domains or []))
    ccfg = rules.get("cluster", {})

    queries = build_queries(brand, product, aspects, time_from, time_to, domain_hint)

    completed = 0
    progress_lock = threading.Lock()

    def _one(q: dict) -> dict:
        nonlocal completed
        r = client.search(q["query"], max_results=max_results,
                          time_range=f"{time_from}..{time_to}" if time_from and time_to else None)
        with progress_lock:
            completed += 1
            if progress_callback:
                progress_callback("搜索与过滤", completed, len(queries))
        return {**q, **r}

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(_one, queries))

    query_stats = [{"query": r["query"], "aspect": r["aspect"],
                    "hits": len(r["results"]), "ok": r["ok"],
                    "error": r.get("error"), "error_code": r.get("error_code"),
                    "request_id": r.get("request_id")} for r in responses]
    filter_stats = {"noise_dropped": 0, "out_of_window": 0,
                    "duplicate_url": 0, "member_ignored": 0, "llm_ignored": 0,
                    "fallback": 0, "low_authority_dropped": 0}

    best_by_url: dict[str, tuple[int, dict]] = {}
    for r in responses:
        if not r["ok"]:
            continue
        for item in r["results"]:
            url = item["url"]
            if not url:
                continue
            strict = r["aspect"] in _STRICT_ASPECTS
            reason = rules_mod.noise_reason(item["title"], item.get("content", ""),
                                            item["domain"], rules, tokens, strict)
            if reason:
                filter_stats["noise_dropped"] += 1
                continue
            d, precision, missing = normalize_date(item.get("published_date"))
            if not _in_window(d, time_from, time_to):
                filter_stats["out_of_window"] += 1
                continue
            richness = len(item.get("title", "")) + len(item.get("content", ""))
            prev = best_by_url.get(url)
            if prev is None:
                best_by_url[url] = (richness, {**item, "date": d, "precision": precision,
                                               "date_missing": missing, "aspect": r["aspect"]})
            else:
                filter_stats["duplicate_url"] += 1
                if richness > prev[0]:
                    best_by_url[url] = (richness, {**item, "date": d, "precision": precision,
                                                   "date_missing": missing, "aspect": r["aspect"]})

    cands = []
    for url, (_, it) in best_by_url.items():
        dom = it["domain"].lower()
        if rules_mod.learn_official(dom, product):
            official = official | {dom}
        tier = rules_mod.tier_of(dom, rules, official)
        conf = rules_mod.confidence_of(dom, tier, rules, official,
                                       has_date=it["date"] is not None)
        cands.append({**it, "tier": tier, "conf": conf})

    if progress_callback:
        progress_callback("聚类与改写", completed, len(queries))
    # 确定性聚类
    vectors = vectorizer.embed([f"{c['title']} {c.get('content', '')[:200]}" for c in cands])
    groups = cluster_mod.cluster_candidates(
        cands, vectors,
        cos_threshold=ccfg.get("cos_threshold", 0.55),
        date_window_days=ccfg.get("date_window_days", 3))

    # LLM 忠实改写与分类（可降级）
    cluster_inputs = [[{**cands[i], "date": cands[i]["date"]} for i in g] for g in groups]
    llm_used, rewritten = True, None
    try:
        rewritten = rewriter(cluster_inputs)
    except llm_mod.LLMUnavailable:
        llm_used, rewritten = False, [None] * len(cluster_inputs)

    events = []
    min_auth = rules.get("confidence", {}).get("min_event_authority", 50)
    for members, rw in zip(cluster_inputs, rewritten):
        if rw is not None and rw.get("ignore"):
            filter_stats["llm_ignored"] += 1  # 整簇无关
            continue
        # 条级去噪：LLM 逐条判定，无关成员不进入事件
        ignored_ids = set()
        if rw is not None:
            ignored_ids = {v["id"] for v in (rw.get("member_verdicts") or [])
                           if isinstance(v, dict) and v.get("ignore")}
        kept = [m for i, m in enumerate(members) if i not in ignored_ids]
        filter_stats["member_ignored"] += len(members) - len(kept)
        if not kept:
            filter_stats["llm_ignored"] += 1  # 全部成员被忽略
            continue
        domains = {m["domain"] for m in kept}
        authority = _authority(kept, rules)
        if authority < min_auth:
            filter_stats["low_authority_dropped"] += 1
            continue
        if rw is None:
            filter_stats["fallback"] += 1
            best = max(kept, key=lambda m: len(m["title"]) + len(m.get("content", "")))
            summary = (best.get("content") or best["title"])[:100]
            etype = {"product": "product", "competitor": "competitor", "policy": "policy",
                     "tech": "tech", "public": "public_opinion", "overview": "product"
                     }[best["aspect"]]
            rel = "core" if any(t.lower() in f"{best['title']} {best.get('content','')}".lower()
                                for t in tokens) else "context"
            title, subtype = best["title"], rules_mod.subtype_of(best["title"], rules)
        else:
            title, summary = rw["title"], rw["summary"]
            etype, subtype, rel = rw["event_type"], rw["subtype"], rw["relevance"]
        dates = [m["date"] for m in kept if m["date"]]
        rep_date = min(dates) if dates else None
        precisions = [m["precision"] for m in kept if m["date"]]
        rep_prec = "day" if "day" in precisions else (
            "month" if "month" in precisions else ("year" if "year" in precisions else "unknown"))
        if rep_date is None and not dates:
            rep_prec = "unknown"
        events.append({
            "event_id": _event_id("|".join(sorted(m["url"] for m in kept))),
            "event_date": rep_date,
            "date_precision": rep_prec,
            "date_missing": rep_date is None,
            "event_type": etype,
            "subtype": subtype,
            "relevance": rel,
            "title": title,
            "summary": summary,
            "media_coverage": _media_coverage(domains, [m["tier"] for m in kept]),
            "authority": authority,
            "sources": [{"source_domain": m["domain"], "source_tier": m["tier"],
                         "confidence": m["conf"], "url": m["url"],
                         "published_date": m["date"], "title": m["title"],
                         **({"published_date_raw": m.get("published_date"),
                             "content_kind": m.get("content_kind"),
                             "search_provider": m["provider"],
                             "provider_rank_score": m.get("provider_rank_score"),
                             "provider_auth_level": m.get("provider_auth_level")}
                            if m.get("provider") else {})} for m in kept],
        })
    events.sort(key=lambda e: (e["event_date"] is None, e["event_date"] or "", e["event_id"]))

    any_failed = any(not q["ok"] for q in query_stats)
    status = ("search_error" if all(not q["ok"] for q in query_stats) else
              "partial" if any_failed else "ok" if events else "empty")
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "brand": brand, "product": product, "domain_hint": domain_hint,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "time_window": ({"from": time_from, "to": time_to}
                            if time_from and time_to else None),
            "status": status, "llm_used": llm_used,
            "search_provider": getattr(client, "provider", "injected"),
            "query_stats": query_stats, "filter_stats": filter_stats,
        },
        "events": events,
    }
