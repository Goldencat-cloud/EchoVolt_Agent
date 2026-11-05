"""Deterministic, read-only query tools over the semantic layer.

本模块只保留**取数适配**：所有口径与统计都来自 `semantic/`，不再读
06_reporting 的 CSV/JSON，也不再连接 snapshot.db。上层（HTTP / MCP / Agent）
继续使用既有函数名，因此"数据源换掉"对调用方是透明的。
"""
from __future__ import annotations

import re
from typing import Any

from research import embeddings
from semantic.adapters import records
from semantic.execute import execute
from semantic.spec import QuerySpec

MINIMUM_POSTS = 10
#: 精选口径名：报告引文与"精选观点"表述都以这一级成员为准。
CURATED = "curated"
#: 对外主口径：议题占比与帖子计数默认用它。
PRIMARY = "experience"
SENTIMENTS = {"正面", "负面", "中性", "混合"}

_STATS_METRICS = ("negativeShare", "claims", "negative", "posts", "negativePosts")


def _require_db() -> None:
    if not records.available():
        raise records.RecordsUnavailable(
            f"语义库不存在：{records.db_path()}；先执行 python -m semantic.build")


def snapshot_version() -> str:
    return records.data_version()


def display_version() -> str:
    """User-facing version token；语义库的版本就是模型版本。"""
    raw = snapshot_version()
    match = re.search(r"\d{4}-\d{2}-\d{2}(?:\.\d+)?", raw)
    return match.group(0) if match else raw[:24]


def temporary_sample() -> bool:
    """占位样本标记由构建期写入 meta；没有该标记即视为正式构建。"""
    return bool(records.meta().get("temporary_sample"))


def snapshot_hash() -> str:
    return records.snapshot_hash()


def claim_index() -> dict[str, dict[str, Any]]:
    """All curated claim records keyed by their claim_id."""
    return {row["claim_id"]: _claim_record(row) for row in _curated_rows()}


def known_aspects() -> set[str]:
    _require_db()
    return set(records.aspects())


#: 兼容旧调用方的私有名（app/测试仍在用）；新代码请用 known_aspects。
_known_aspects = known_aspects


def validate_research_brief(brief: dict[str, Any]) -> None:
    """保留入口：brief 校验已由 task_brief.validate_brief 承担。"""
    if not isinstance(brief, dict):
        raise ValueError("brief 必须是对象")


def _claim_record(row: dict[str, Any]) -> dict[str, Any]:
    return {"claim_id": row["claim_id"], "aspect": row.get("aspect"),
            "sentiment": row.get("sentiment"), "content": row.get("content") or "",
            "quote": row.get("quote") or "", "url": row.get("url"),
            "title": row.get("title"), "date": row.get("published_at"),
            "journey": row.get("journey"), "ownership": row.get("ownership"),
            "experience": row.get("experience"), "statement": row.get("statement"),
            "comparison": None, "usage_context": None,
            "source_type": "精选观点证据", "source_set": CURATED}


def _curated_rows() -> list[dict[str, Any]]:
    _require_db()
    return [_claim_record(row) for row in records.claim_rows(population=CURATED)]


def aspects_preview(aspects: list[str] | None = None) -> dict[str, Any]:
    """计划阶段的按议题探索预览（精选口径）。

    每个议题返回：精选证据样本量、按月计数、代表性观点（top 3 带 claim_id）。
    统计走语义引擎，明细走 records —— 两处口径同源（curated）。
    """
    _require_db()
    known = known_aspects()
    if aspects is None:
        aspects = sorted(known)
    unknown = [item for item in aspects if item not in known]
    if unknown:
        raise ValueError("unsupported aspect: " + ", ".join(unknown))
    out: list[dict[str, Any]] = []
    for aspect in aspects:
        sample = records.claim_count(aspect=aspect, population=CURATED, require_quote=True)
        months = _monthly(aspect)
        representative = [{"claim_id": row["claim_id"], "date": row.get("published_at"),
                           "title": row.get("title"), "quote": (row.get("quote") or "")[:120]}
                          for row in records.claim_rows(aspect=aspect, population=CURATED,
                                                        require_quote=True, limit=3)]
        out.append({"aspect": aspect, "sample_size": sample,
                    "support_insufficient": sample < 5,
                    "monthly_counts": months, "representative": representative})
    return {"aspects": out, "n_aspects": len(aspects),
            "caliber": "精选口径（模型声明的 curated 成员，经引文回挂校验）；"
                       "样本量为该议题精选证据条数",
            "support_threshold": 5,
            "data_version": snapshot_version(), "snapshot_hash": snapshot_hash()}


def _monthly(aspect: str) -> list[dict[str, Any]]:
    """按议题的精选证据月度分布（走语义引擎的 time_month 维度）。"""
    envelope = execute(QuerySpec(
        metrics=("curatedNegative", "curatedClaims"), dimensions=("time_month",),
        filters={"aspect": aspect}, order=({"field": "time_month", "dir": "asc"},),
        limit=120, population=CURATED))
    return [{"month": row.get("time_month"), "n": int(row.get("curatedClaims") or 0)}
            for row in envelope.get("rows", [])]


def query_stats(aspect: str | None = None) -> dict[str, Any]:
    """议题级统计：negativeShare 用观点条数作分母，帖子计数独立。"""
    _require_db()
    if aspect is not None and aspect not in known_aspects():
        raise ValueError("unsupported aspect")
    filters = {"aspect": aspect} if aspect else {}
    envelope = execute(QuerySpec(metrics=_STATS_METRICS, dimensions=("aspect",),
                                 filters=filters,
                                 order=({"field": "negativeShare", "dir": "desc"},),
                                 limit=64, population=PRIMARY))
    rows = envelope.get("rows", [])
    if not rows:
        return {"data": [], "caliber": "negativeShare = negative claims / claims",
                "data_version": snapshot_version(), "snapshot_hash": snapshot_hash(),
                "n": 0, "warnings": ["no_matching_aspect"], "truncated": False}
    data = [{"aspect": row.get("aspect"), "posts": int(row.get("posts") or 0),
             "claims": int(row.get("claims") or 0),
             "negative_posts": int(row.get("negativePosts") or 0),
             "negative_claims": int(row.get("negative") or 0),
             "negativeShare": float(row.get("negativeShare") or 0.0)} for row in rows]
    warnings = ["temporary_snapshot_placeholder"] if temporary_sample() else []
    if any(row["posts"] < MINIMUM_POSTS for row in data):
        warnings.append("below_minimum_posts")
    return {"data": data,
            "caliber": "negativeShare = negative claims / claims；观点级口径；"
                       "negative_posts/posts 为独立的帖子级计数",
            "data_version": snapshot_version(), "snapshot_hash": snapshot_hash(),
            "n": sum(row["posts"] for row in data), "warnings": warnings,
            "truncated": False}


def query_claims(*, aspect: str | None = None, sentiment: str | None = None,
                 journey: str | None = None, ownership: str | None = None,
                 limit: int = 5, offset: int = 0) -> dict[str, Any]:
    _require_db()
    if not 1 <= limit <= 20 or offset < 0:
        raise ValueError("limit must be 1..20 and offset must be non-negative")
    if aspect is not None and aspect not in known_aspects():
        raise ValueError("unsupported aspect")
    if sentiment is not None and sentiment not in SENTIMENTS:
        raise ValueError("unsupported sentiment")
    for field, value in (("journey", journey), ("ownership", ownership)):
        if value is not None and value != "未标注":
            known_values = {str(row.get(field) or "未标注") for row in _curated_rows()}
            if value not in known_values:
                raise ValueError(f"unsupported {field}")
    total = records.claim_count(aspect=aspect, sentiment=sentiment, journey=journey,
                                ownership=ownership, population=CURATED)
    page = [_claim_record(row) for row in records.claim_rows(
        aspect=aspect, sentiment=sentiment, journey=journey, ownership=ownership,
        population=CURATED, limit=limit, offset=offset, order="date_asc")]
    warnings = ["curated_evidence_subset_not_all_claims"]
    if temporary_sample():
        warnings.append("temporary_snapshot_placeholder")
    if any(not row.get("url") or not row.get("quote") for row in page):
        warnings.append("some_evidence_missing_quote_or_source")
    if not page:
        warnings.append("no_matching_evidence")
    return {"data": page, "caliber": "筛选精选口径（curated）观点；引文来自观点原文",
            "data_version": snapshot_version(), "snapshot_hash": snapshot_hash(),
            "n": total, "warnings": warnings,
            "truncated": offset + len(page) < total}


_EMBEDDING_MIN_COSINE = 0.30  # 低于该语义相关度的 claim 不进入召回结果


def _recall_terms(query: str) -> list[str]:
    """CJK bigrams + whole short words + latin tokens; mirrors report search."""
    terms: set[str] = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", query.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            terms.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
            if len(chunk) <= 4:
                terms.add(chunk)
        else:
            terms.add(chunk)
    return sorted({term for term in terms if len(term) >= 2})


def search_claims(*, query: str, aspect: str | None = None,
                  sentiment: str | None = None, limit: int = 10) -> dict[str, Any]:
    """按结论在精选观点池中召回 claims（关键词或向量相关度）。

    相关度：配置了 AI_EMBEDDING_MODEL 时用向量余弦（×2），否则用关键词命中
    覆盖（content/quote/title）×2；后端失败自动降级关键词并在 warnings 标注。
    次级加权为亲历与新近度。池内每条 claim 都带可引用 claim_id。
    """
    _require_db()
    cleaned = str(query or "").strip()
    if not 2 <= len(cleaned) <= 200:
        raise ValueError("query must be 2..200 characters")
    if aspect is not None and aspect not in known_aspects():
        raise ValueError("unsupported aspect")
    if sentiment is not None and sentiment not in SENTIMENTS:
        raise ValueError("unsupported sentiment")
    if not 1 <= int(limit) <= 20:
        raise ValueError("limit must be 1..20")
    terms = _recall_terms(cleaned)
    if not terms:
        raise ValueError("query contains no searchable terms")
    pool = _curated_rows()
    if aspect is not None:
        pool = [row for row in pool if row.get("aspect") == aspect]
    if sentiment is not None:
        normalized = "正负混合" if sentiment == "混合" else sentiment
        pool = [row for row in pool if row.get("sentiment") == normalized]
    relevance = "keyword"
    query_vec: list[float] | None = None
    vectors: dict[str, list[float]] = {}
    embedding_attempted = bool(pool) and embeddings.backend_ready()
    if embedding_attempted:
        query_vecs = embeddings.embed_texts([cleaned])
        if query_vecs:
            vectors = embeddings.pool_vectors(
                snapshot_hash(), [row["claim_id"] for row in pool],
                [" ".join(str(row.get(field) or "") for field in ("title", "content"))
                 for row in pool])
            if vectors:
                query_vec = query_vecs[0]
                relevance = "embedding"
    dates = sorted({str(row.get("date") or "") for row in pool} - {""})
    recency = {date: (index / max(1, len(dates) - 1)) * 0.1
               for index, date in enumerate(dates)}
    scored = []
    for row in pool:
        if relevance == "embedding":
            vector = vectors.get(row["claim_id"])
            if vector is None:
                continue
            similarity = embeddings.cosine(query_vec, vector)
            if similarity < _EMBEDDING_MIN_COSINE:
                continue
            coverage = similarity
        else:
            haystack = " ".join(str(row.get(field) or "")
                                for field in ("content", "quote", "title")).lower()
            matched = sum(1 for term in terms if term in haystack)
            if not matched:
                continue
            coverage = matched / len(terms)
        firsthand = 0.1 if row.get("experience") == "明确亲历" else 0.0
        score = round(coverage * 2 + 1.0 + firsthand
                      + recency.get(str(row.get("date")) or "", 0.0), 4)
        scored.append((-score, str(row.get("date") or ""), row["claim_id"], score, row))
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    claims = [{"claim_id": row["claim_id"], "aspect": row.get("aspect"),
               "sentiment": row.get("sentiment"), "tier": CURATED,
               "experience": row.get("experience"), "date": row.get("date"),
               "title": row.get("title"), "url": row.get("url"),
               "content": row.get("content"), "quote": row.get("quote"),
               "score": score}
              for _, _, _, score, row in scored[:int(limit)]]
    score_formula = ("语义相关度×2+亲历+新近度" if relevance == "embedding"
                     else "关键词覆盖×2+亲历+新近度")
    warnings = ["no_matching_claims"] if not scored else ["curated_evidence_subset_not_all_claims"]
    if temporary_sample():
        warnings.append("temporary_snapshot_placeholder")
    if embedding_attempted and relevance == "keyword":
        warnings.append("embedding_unavailable_keyword_fallback")
    return {"query": cleaned, "n_candidates": len(pool), "n_matches": len(scored),
            "claims": claims, "relevance": relevance,
            "caliber": f"精选口径（curated），均通过引文回挂校验；score={score_formula}",
            "data_version": snapshot_version(), "snapshot_hash": snapshot_hash(),
            "warnings": warnings}


def evidence_details(claim_ids: Any) -> dict[str, Any]:
    """按 claim_id 解析证据元数据（报告附录与溯源消费方用）。

    输入去重，输出按 claim_id 升序；quote 截断到 160 字符（附录是索引不是全文）。
    查不到的 ID 以 found=False 如实返回，绝不静默丢弃。
    """
    _require_db()
    if isinstance(claim_ids, str):
        claim_ids = [claim_ids]
    wanted = sorted({str(item).strip() for item in (claim_ids or []) if str(item).strip()})
    if not wanted:
        raise ValueError("claim_ids must contain at least one identifier")
    index = {row["claim_id"]: row for row in records.claim_rows(population=CURATED,
                                                                limit=None)}
    details: list[dict[str, Any]] = []
    for claim_id in wanted:
        row = index.get(claim_id)
        if row is None:
            details.append({"claim_id": claim_id, "found": False})
            continue
        details.append({
            "claim_id": claim_id, "found": True,
            "url": row.get("url"), "date": row.get("published_at"),
            "title": row.get("title"), "aspect": row.get("aspect"),
            "sentiment": row.get("sentiment"), "ownership": row.get("ownership"),
            "experience": row.get("experience"), "journey": row.get("journey"),
            "source_set": CURATED,
            "quote": str(row.get("quote") or "")[:160],
        })
    return {"details": details, "n_requested": len(wanted),
            "n_found": sum(1 for item in details if item["found"]),
            "caliber": "精选口径（curated）；引文截断为 160 字符，全文见原帖与溯源记录",
            "data_version": snapshot_version(), "snapshot_hash": snapshot_hash()}


def health() -> dict[str, Any]:
    try:
        ready = records.available() and bool(snapshot_hash())
    except (OSError, ValueError, KeyError):
        ready = False
    return {"status": "ok" if ready else "unavailable",
            "data_version": snapshot_version() if ready else None}
