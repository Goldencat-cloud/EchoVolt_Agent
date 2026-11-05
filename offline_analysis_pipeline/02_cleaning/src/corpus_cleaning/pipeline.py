# -*- coding: utf-8 -*-
"""清洗主管线：一次遍历完成标注 + 别名映射 + 落库，返回统计（含锚点对照）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import aliases as AL
from . import annotate as AN
from . import contracts as C
from . import spam as SP
from . import store as ST
from .polish import norm_key, normalize_base, polish_multimodal, polish_text

DEFAULT_CLEANING_VERSION = "clean-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def run(db_path: str, cleaning_version: str = DEFAULT_CLEANING_VERSION, dry_run: bool = False) -> dict:
    """执行清洗。dry_run=True 时计算全部标注并返回统计，但不写库。"""
    generated_at = _now_iso()
    conn = ST.connect(db_path)
    try:
        posts = [dict(r) for r in conn.execute(
            "SELECT post_id, author_id, title, body_text, clean_text, content_segments_json, "
            "author_context_json, published_at FROM posts ORDER BY rowid").fetchall()]
        specs = [dict(r) for r in conn.execute(
            "SELECT spec_id, series_id, spec_name, series_name, brand_name FROM product_specs").fetchall()]

        # ---- 逐帖标注 ----
        rows: list[dict] = []
        url_before = url_after = 0
        base_map: dict[str, str] = {}
        for p in posts:
            body_raw = p["body_text"] or ""
            # 归一基座（去零宽+折叠空白+strip）：norm_key 与 text_changed 的比较基座，
            # 对齐旧管线 text_content 规范化口径（design 决策5 锚点复算）；净化输出不受影响。
            base = normalize_base(body_raw)
            base_map[p["post_id"]] = base
            segments = AN.parse_segments(p["content_segments_json"])
            media = AN.has_media(segments)
            excluded, ex_reasons = AN.classify_excluded(base, body_raw, (p["clean_text"] or ""), media)
            pm_json, _, media_after = polish_multimodal(p["content_segments_json"] or "")
            url_before += AN.count_media(segments)
            url_after += media_after
            ctx = {}
            try:
                ctx = json.loads(p["author_context_json"] or "{}")
            except json.JSONDecodeError:
                pass
            rows.append({
                "post_id": p["post_id"],
                "excluded": excluded,
                "ex_reasons": ex_reasons,
                "norm_key": norm_key(base) if base else "",
                "polished_text": polish_text(base),
                "polished_multimodal": pm_json,
                "author_id": p["author_id"],
                "published_at": p["published_at"],
                "registered_at_raw": ctx.get("registered_at_raw"),
                "platform_post_count": ctx.get("platform_post_count"),
            })

        # ---- 去重（参与范围：非删除/非空媒体，对齐旧管线）----
        dedup_input = [(r["post_id"], r["norm_key"]) for r in rows
                       if r["excluded"] not in ("post_deleted", "empty_no_media")]
        group_by, dup_by, group_count = AN.dedup(dedup_input)

        # ---- 水军聚合（r1/r2 仅对未剔除行； Owner 抽查指示：排除已剔除行与超短键噪声）----
        spam_map = SP.compute_spam([
            {"post_id": r["post_id"], "author_id": r["author_id"], "norm_key": r["norm_key"],
             "excluded": r["excluded"],
             "published_at": r["published_at"], "registered_at_raw": r["registered_at_raw"],
             "platform_post_count": r["platform_post_count"]}
            for r in rows
        ])

        # ---- 汇总标注行 ----
        for r in rows:
            r["dedup_group_id"] = group_by.get(r["post_id"], 0)
            r["is_duplicate"] = dup_by.get(r["post_id"], False)
            sp = spam_map.get(r["post_id"], {"spam_suspect": 0, "spam_reasons": {}})
            r["spam_suspect"] = sp["spam_suspect"]
            reasons = dict(sp["spam_reasons"])
            if r["ex_reasons"]:
                reasons["excluded_rule"] = r["ex_reasons"]
            r["spam_reasons_json"] = SP.reasons_to_json(reasons)
        # text_changed 以归一基座为准（旧锚点口径，见 data-contract）
        for r in rows:
            r["text_changed"] = r["polished_text"] != base_map.get(r["post_id"], "")

        # ---- 统计与锚点 ----
        stats = _stats(rows, group_count, url_before, url_after)

        # ---- 别名映射（与清洗同遍历；语料挖掘复用全部文本）----
        alias_rows = AL.build_official_variant(specs, generated_at)
        existing_norms = {r["alias_norm"] for r in alias_rows}
        existing_norms |= {r["alias_norm"] for r in AL.competitor_rows(generated_at)}  # 竞品种子优先于社区候选
        candidates, alias_stats = AL.mine_community(specs, AL.load_corpus_texts(
            [{"title": p["title"], "body_text": p["body_text"]} for p in posts]),
            generated_at, existing_norms)
        alias_rows += candidates + AL.competitor_rows(generated_at)
        stats["aliases"] = alias_stats
        stats["alias_rows_total"] = len(alias_rows)

        if not dry_run:
            ST.ensure_schema(conn)
            n = ST.write_annotations(conn, cleaning_version, generated_at, rows)
            alias_w = ST.write_aliases(conn, alias_rows)
            conn.commit()
            stats["written_annotations"] = n
            stats["written_aliases"] = alias_w
        return stats
    finally:
        conn.close()


def _stats(rows: list[dict], group_count: int, url_before: int, url_after: int) -> dict:
    counted = [r for r in rows if r["excluded"] not in ("post_deleted", "empty_no_media")]
    by_excluded: dict[str, int] = {}
    for r in rows:
        by_excluded[r["excluded"]] = by_excluded.get(r["excluded"], 0) + 1
    clean_subset = sum(
        1 for r in rows
        if r["excluded"] == "" and not r["is_duplicate"] and (r["polished_text"] or "") != ""
    )
    actual = {
        "post_deleted": by_excluded.get("post_deleted", 0),
        "empty_no_media": by_excluded.get("empty_no_media", 0),
        "duplicate_rows": sum(1 for r in counted if r["is_duplicate"]),
        "system_junk": by_excluded.get("system_junk", 0),
        "gibberish": by_excluded.get("gibberish", 0),
        "clean_subset": clean_subset,
        "text_changed": sum(1 for r in rows if r["text_changed"]),
        "multimodal_urls_before": url_before,
    }
    drift = {k: {"anchor": C.ANCHORS[k], "actual": actual.get(k), "delta": actual.get(k, 0) - C.ANCHORS[k]}
             for k in C.ANCHORS if k in actual}
    return {
        "posts_total": len(rows),
        "excluded_counts": by_excluded,
        "dedup_groups": group_count,
        "spam_suspect": sum(1 for r in rows if r["spam_suspect"]),
        "spam_reason_breakdown": _spam_breakdown(rows),
        "anchors": drift,
        "urls_before": url_before,
        "urls_after": url_after,
    }


def _spam_breakdown(rows: list[dict]) -> dict:
    breakdown: dict[str, int] = {}
    for r in rows:
        try:
            reasons = json.loads(r["spam_reasons_json"])
        except json.JSONDecodeError:
            continue
        for k in reasons:
            breakdown[k] = breakdown.get(k, 0) + 1
    return breakdown
