"""Deterministic task-brief generation for the deep-analysis agent (auto-030 D13).

Replaces the JSON-dump opening message with a structured brief:

  1. 研究请求      — resolved brand scope / time window / comparison target
  2. 数据覆盖声明  — snapshot version, brand list, date range, caliber partitions
  3. 数据目录      — per-frame schema with per-column enums (the values the agent
                     previously had to guess from 3 sample rows)
  4. 预置基准      — server-precomputed baseline statistics

Everything here is server-computed from the frozen snapshot; no model calls.
The brief carries data only (D-CTX3): instructions stay in the system prompt
and the engine appends a <=5-line action block. Trim order when over budget:
free-text sample values -> baseline rows -> enum top-N; the coverage
declaration, brand list and date range are never trimmed.
"""
from __future__ import annotations

import re
import os
import sqlite3
from typing import Any

import config
from semantic.adapters import compat_views as db_mirror
from research import catalog as research_catalog

_VERSION_RE = re.compile(r"V\d+(?:\.\d+)?")

# auto-031 2.1：计划 schema v2 的 visualization 意图（非法值由计划校验器拒绝）
VISUALIZATION_TYPES = {"bar", "line", "pie", "table"}

# Static column semantics per semantic view (the layer contract; enums are dynamic).
_FRAME_HEADERS: dict[str, str] = {
    "metrics": "全量声明级指标",
    "claims": "精选观点事实（core/potential 子集）",
    "evidence": "精选观点证据（仅含 quote 非空行）",
    "post_scope": "帖子→产品范围映射（范围元数据，不含内容）",
}
_FRAME_VIEWS: dict[str, str] = {
    "metrics": "semantic_aspect_metric",
    "claims": "semantic_claim_fact",
    "evidence": "semantic_claim_evidence",
    "post_scope": "semantic_post_scope",
}
_FRAME_COLUMNS: dict[str, list[tuple[str, str, str]]] = {
    "metrics": [
        ("aspect", "str", "议题名，精确取值见下"),
        ("claims/posts/positive/negative/neutral/other", "int", "声明级计数"),
        ("negative_posts/posts", "int", "帖子级计数"),
        ("negative_share", "float", "negative/claims，0-1"),
        ("caliber_note", "str", "口径说明（固定文案）"),
    ],
    "claims": [
        ("claim_id", "str", "20 位十六进制，报告引用必须携带"),
        ("post_id", "str", "可联结 frames.post_scope"),
        ("aspect", "str", "取值见下（精选子集计数）"),
        ("sentiment", "str", "取值见下"),
        ("content/statement", "str", "长文本，不经本简报，经工具获取"),
        ("claim_type/ownership/journey", "str", "取值见下"),
        ("experience", "str", "自由文本，示例值见下"),
        ("date", "str", "日期时间，范围见覆盖声明"),
        ("title/url", "str", "来源帖标题与链接"),
        ("evidence_ok/source_set", "int/str", "证据质量标记"),
    ],
    "evidence": [
        ("claim_id/aspect/sentiment/ownership/experience/journey/date/title/url", "—", "与 claims 同构"),
        ("quote", "str", "用户原话，报告引用时必须可回溯 claim_id"),
    ],
    "post_scope": [
        ("post_id", "str", "联结键"),
        ("product_id/raw_name", "str", "产品标识与原始名称"),
        ("scope_status/scope_level", "str", "范围标记，语义见下"),
        ("brand/series", "str", "品牌与车系，取值见下"),
    ],
}


def _connect(con: sqlite3.Connection | None) -> sqlite3.Connection:
    return con or db_mirror.connect()


def _version_token(meta: dict[str, str]) -> tuple[str, bool]:
    raw = meta.get("data_version", "")
    match = _VERSION_RE.search(raw)
    token = match.group(0) if match else raw[:12]
    temporary = "占位" in raw or "临时" in raw
    return token, temporary


def snapshot_coverage(con: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Coverage facts shared by the brief and the form-validation endpoints."""
    own = con is None
    con = _connect(con)
    try:
        meta = {r["key"]: r["value"] for r in
                con.execute("SELECT key, value FROM semantic_snapshot_meta")}
        version, temporary = _version_token(meta)
        brands = [tuple(r) for r in con.execute(
            "SELECT brand, series, COUNT(*) FROM semantic_post_scope "
            "WHERE scope_status = 'mapped' AND brand IS NOT NULL "
            "AND is_analysis_object = 1 "
            "GROUP BY brand, series ORDER BY COUNT(*) DESC")]
        date_row = con.execute(
            "SELECT MIN(date), MAX(date) FROM semantic_claim_fact").fetchone()
        scope_status = {r[0]: r[1] for r in con.execute(
            "SELECT scope_status, COUNT(*) FROM semantic_post_scope GROUP BY 1")}
        return {"version": version, "temporary": temporary,
                "snapshot_hash": meta.get("snapshot_hash", ""),
                "built_at": meta.get("built_at", ""),
                "brands": brands, "date_min": date_row[0], "date_max": date_row[1],
                "scope_status": scope_status}
    finally:
        if own:
            con.close()


def _brand_names(brands: list[tuple]) -> list[str]:
    return list(dict.fromkeys(b[0] for b in brands))


def outline_projection(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """auto-031 2.2：workstreams → 大纲条目（子问题 + 可视化描述 + 顺序）。

    大纲是执行步骤的投影，不是独立文档（design D3）：大纲卡片渲染本函数的
    输出，用户编辑作用于 workstreams 后重投影——由构造保证两者一致。
    """
    items: list[dict[str, Any]] = []
    for order, stream in enumerate((plan or {}).get("workstreams") or [], start=1):
        visualization = stream.get("visualization") if isinstance(stream, dict) else None
        viz_desc = None
        if isinstance(visualization, dict):
            viz_desc = {"type": visualization.get("type"),
                        "title": visualization.get("title") or stream.get("question")}
        items.append({"order": order, "id": (stream or {}).get("id"),
                      "question": (stream or {}).get("question"),
                      "aspect": (stream or {}).get("aspect"),
                      "method": (stream or {}).get("method"),
                      "requires_evidence": (stream or {}).get("requires_evidence"),
                      "visualization": viz_desc})
    return items


def _shift_months_back(date_str: str, months: int) -> str:
    """date_max 回溯 N 个月的月初（确定性，YYYY-MM-01）；解析失败返回原值。"""
    match = re.match(r"^(\d{4})-(\d{2})", date_str or "")
    if not match:
        return date_str or ""
    year, month = int(match.group(1)), int(match.group(2))
    total = (year * 12 + (month - 1)) - months
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def form_options(con: sqlite3.Connection | None = None) -> dict[str, Any]:
    """auto-031 1.1：深度分析表单选项目录，与简报覆盖声明同源。

    auto-032 5.1：选项按聚合原语能力声明生成——`date_range_filter` 开启才返回
    时间范围切片；`brand_compare` 关闭时返回结构不含对比选项字段（引擎不支持的
    能力不在 UI 承诺）。
    分析对象 = resolve_brand_scope 的开放主体（当前仅 SU7，多选能力壳）；
    时间范围 = 从快照 date_max 回溯的近 1/3/6 月 + 全部，均校验落在覆盖区间内。
    """
    capabilities = research_catalog.primitive_capabilities()
    coverage = snapshot_coverage(con)
    scope = resolve_brand_scope(None, coverage["brands"])
    date_min = str(coverage["date_min"] or "")[:10]
    date_max = str(coverage["date_max"] or "")[:10]
    windows: list[dict[str, str]] = []
    if capabilities.get("date_range_filter"):
        for months, label in ((1, "近 1 月"), (3, "近 3 月"), (6, "近 6 月")):
            start = _shift_months_back(date_max, months)
            if start >= date_min:
                windows.append({"key": f"last_{months}m", "label": label,
                                "start": start, "end": date_max})
        windows.append({"key": "all", "label": "全部", "start": date_min, "end": date_max})
    subject = scope.get("brand")
    series = config.SUBJECT_SERIES
    options: dict[str, Any] = {
        "subjects": [{"value": f"{subject}/{series}" if series else subject,
                      "label": f"{subject} {series}" if series else str(subject),
                      "open": True}],
        "coverage": {"version": coverage["version"], "temporary": coverage["temporary"],
                     "date_min": date_min, "date_max": date_max,
                     "brand_scope_note": scope.get("note", "")},
    }
    if windows:
        options["time_windows"] = windows
    if capabilities.get("brand_compare"):
        options["compare"] = {"enabled": True}
    return options

_WINDOW_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*$|^\s*(\d{4}-\d{2}-\d{2})\s*$")


def validate_brief(brief: Any, con: sqlite3.Connection | None = None
                   ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Server-side form validation for `brief{topic, brand?, time_window?, compare?}`
    (4.1/D11). Same data source as the task brief (snapshot_coverage +
    resolve_brand_scope) so form options, brief and gate can never drift.

    Returns (clean_brief, None) or (None, rejection) where rejection carries the
    allowed brand list and time window for the 400 response body.
    """
    if brief is None:
        return None, None  # 旧请求无 brief：保持兼容，全部走默认主体/全区间
    if not isinstance(brief, dict):
        return None, {"error": "invalid_brief", "message": "brief 须为 JSON 对象"}
    coverage = snapshot_coverage(con)
    brand_names = _brand_names(coverage["brands"])
    allowed_window = [str(coverage["date_min"] or "")[:10],
                      str(coverage["date_max"] or "")[:10]]
    base = {"allowed_brands": brand_names, "allowed_time_window": allowed_window}

    topic = brief.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return None, {**base, "error": "invalid_brief", "message": "brief.topic 必填"}

    window_raw = brief.get("time_window")
    window_clean: str | None = None
    if window_raw is not None:
        if not isinstance(window_raw, str):
            return None, {**base, "error": "invalid_time_window",
                          "message": "time_window 须为 \"YYYY-MM-DD ~ YYYY-MM-DD\" 字符串"}
        match = _WINDOW_RE.match(window_raw)
        if not match:
            return None, {**base, "error": "invalid_time_window",
                          "message": "time_window 格式须为 \"YYYY-MM-DD ~ YYYY-MM-DD\"（或单日）"}
        start = (match.group(1) or match.group(3))[:10]
        end = (match.group(2) or match.group(3))[:10]
        if start > end:
            return None, {**base, "error": "invalid_time_window",
                          "message": "time_window 起点晚于终点"}
        if start < allowed_window[0] or end > allowed_window[1]:
            return None, {**base, "error": "time_window_out_of_range",
                          "message": f"时间窗口超出数据覆盖范围（{allowed_window[0]} ~ {allowed_window[1]}）"}
        window_clean = f"{start} ~ {end}"

    brand_raw = brief.get("brand")
    scope = resolve_brand_scope(brand_raw if isinstance(brand_raw, str) else None,
                                coverage["brands"])
    if brand_raw is not None and not scope.get("ok"):
        return None, {**base, "error": "brand_not_available",
                      "message": scope.get("note", "指定品牌不可用")}

    compare_raw = brief.get("compare")
    if compare_raw is not None and not isinstance(compare_raw, str):
        return None, {**base, "error": "invalid_brief", "message": "compare 须为字符串"}

    clean = {"topic": topic.strip()[:200],
             "brand": scope.get("brand"),
             "time_window": window_clean,
             "compare": (compare_raw or "").strip()[:200] or None}
    return clean, None


def resolve_brand_scope(brief_brand: str | None,
                        brands: list[tuple],
                        multi_enabled: bool | None = None) -> dict[str, Any]:
    """Brand ladder (D11, Owner 裁定 2026-10-27：当前仅开放 SU7 主体).

    With ``BRAND_MULTI_ENABLED=False`` (current) the subject brand is fixed:
    unspecified -> default subject; other brands -> rejected with an
    open-scope hint (co-mention context only). Flip the flag to enable the
    multi-brand clarify branch: validate -> clarify-when-multi ->
    default-when-single. Pure function over the extracted brand list so the
    form endpoint (4.1) and the brief generator share one implementation.
    """
    multi = config.BRAND_MULTI_ENABLED if multi_enabled is None else multi_enabled
    names = _brand_names(brands)
    series_by_brand: dict[str, list[str]] = {}
    for brand, series, _count in brands:
        if series and series not in series_by_brand.setdefault(brand, []):
            series_by_brand[brand].append(series)
    listing = "、".join(
        f"{name}（{'/'.join(series_by_brand[name])}）" if series_by_brand.get(name)
        else name for name in names)

    # Subject brand: config-declared, validated against the snapshot; falls
    # back to the most-mentioned brand when the declared one is absent.
    subject = config.SUBJECT_BRAND
    if subject not in names and brands:
        subject = names[0]
    subject_series = (series_by_brand.get(subject) or [None])[0]
    subject_label = f"{subject}/{subject_series}" if subject_series else subject

    if brief_brand:
        candidate = brief_brand.strip()
        if candidate == subject or candidate == subject_label or \
                candidate.startswith(subject + "/") and \
                candidate.split("/", 1)[1] in series_by_brand.get(subject, []):
            return {"ok": True, "brand": subject,
                    "note": f"用户指定：{candidate}（当前开放主体）",
                    "needs_clarification": False}
        if not multi:
            return {"ok": False, "brand": None,
                    "note": f"当前仅开放 {subject_label} 主题分析；"
                            f"快照中其他品牌为帖子共现对比信息。可用：{subject_label}",
                    "needs_clarification": False}
        if candidate in names:
            return {"ok": True, "brand": candidate, "note": f"用户指定：{candidate}",
                    "needs_clarification": False}
        matched = [name for name in names if candidate.startswith(name + "/")
                   and candidate.split("/", 1)[1] in series_by_brand.get(name, [])]
        if matched:
            return {"ok": True, "brand": matched[0], "note": f"用户指定：{candidate}",
                    "needs_clarification": False}
        return {"ok": False, "brand": None,
                "note": f"指定品牌不在当前快照品牌清单内；可用：{listing}",
                "needs_clarification": False}
    if not multi:
        return {"ok": True, "brand": subject,
                "note": f"当前阶段固定分析主体：{subject_label}"
                        f"（快照中其他品牌为帖子共现对比信息，请在报告口径中写明主体范围）",
                "needs_clarification": False}
    if len(names) == 1:
        return {"ok": True, "brand": names[0],
                "note": f"当前快照唯一品牌，已默认：{names[0]}（请在报告口径中写明）",
                "needs_clarification": False}
    return {"ok": True, "brand": None,
            "note": f"用户未指定品牌（快照覆盖 {len(names)} 个：{listing}）——待澄清",
            "needs_clarification": True}


def _enum_line(con: sqlite3.Connection, table: str, column: str,
               top_n: int | None = None, where: str = "",
               value_column: str | None = None) -> str:
    value = value_column or "COUNT(*)"
    sql = (f"SELECT {column}, {value} FROM {table} WHERE {column} IS NOT NULL "
           f"{where}GROUP BY {column} ORDER BY 2 DESC")
    rows = con.execute(sql).fetchall()
    if top_n:
        rows = rows[:top_n]
    return " / ".join(f"{row[0]}({row[1]})" for row in rows)


def _sample_values(con: sqlite3.Connection, count: int) -> str:
    if count <= 0:
        return "（已裁剪）"
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT experience FROM semantic_claim_fact "
        "WHERE experience IS NOT NULL AND experience <> '' LIMIT ?", (count,))]
    return " / ".join(rows) if rows else "（无）"


def _baseline_table(baseline: dict[str, Any], rows_limit: int) -> str:
    rows = (baseline.get("rows") or [])[:rows_limit]
    if not rows:
        return "（本次未预生成基准行）"
    lines = ["| aspect | negative_share | claims | negative |",
             "|---|---|---|---|"]
    for row in rows:
        lines.append("| {aspect} | {share} | {claims} | {negative} |".format(
            aspect=row.get("aspect"), share=row.get("negative_share"),
            claims=row.get("claims"), negative=row.get("negative")))
    return "\n".join(lines)


def build_task_brief(question: str, aspect: str | None, baseline: dict[str, Any],
                     brief: dict[str, Any] | None = None,
                     con: sqlite3.Connection | None = None) -> str:
    """Render the opening task brief. Data only; no instructions (D-CTX3)."""
    brief = brief or {}
    own = con is None
    con = _connect(con)
    try:
        coverage = snapshot_coverage(con)
        brand_scope = resolve_brand_scope(brief.get("brand"), coverage["brands"])
        brand_names = _brand_names(coverage["brands"])
        time_window = brief.get("time_window")
        time_line = (f"{time_window}（用户指定）" if time_window
                     else f"未指定（默认全区间 {coverage['date_min']} ~ {coverage['date_max']}）")
        compare = brief.get("compare")
        compare_line = compare if compare else "无"
        focus = brief.get("focus")
        audience = brief.get("audience")
        spec_line = (f"- 交付规格：重点={focus or '未指定'}；受众={audience or '业务负责人与研究人员'}")

        def render(sample_n: int, enum_n: int | None, baseline_n: int) -> str:
            parts: list[str] = ["# 任务简报", "", "## 研究请求",
                                f"- 主题：{question}",
                                f"- 品牌范围：{brand_scope['note']}",
                                f"- 时间窗口：{time_line}",
                                f"- 对比对象：{compare_line}",
                                spec_line,
                                "", "## 数据覆盖声明（服务端确定性提取，勿再验证）"]
            decl = [f"- 数据版本：{coverage['version']}"
                    + ("（临时样本）" if coverage["temporary"] else "")
                    + f"（hash: {coverage['snapshot_hash']}，构建于 {coverage['built_at']}）；"
                      "报告页脚须原样写出该版本号（如「数据版本："
                    + f"{coverage['version']}」）",
                    f"- 品牌清单（scope_status=in_scope，按提及量排序）："
                    f"{len(brand_names)} 个 —— " + "、".join(brand_names)
                    + (f"；分析主体：{brand_scope['brand']}"
                       f"（其余品牌为帖子共现对比信息）" if brand_scope["brand"] else ""),
                    f"- 日期范围：{coverage['date_min']} ~ {coverage['date_max']}"
                    f"（claims.date，格式 YYYY-MM-DD HH:MM）",
                    "- 口径分区：metrics = 全量声明级；claims/evidence = core/potential "
                    "精选子集（不代表全部用户声音）；journey/ownership/experience/time "
                    "维度仅描述精选子集",
                    "- 预置基准：已登记溯源账本（kind=baseline），数字可直接写入报告正文，"
                    "无需重跑同款统计"]
            parts += decl + ["", "## 数据目录"]
            counts = {t: con.execute(f"SELECT COUNT(*) FROM {_FRAME_VIEWS[t]}").fetchone()[0]
                      for t in _FRAME_COLUMNS}
            for frame in ("metrics", "claims", "evidence", "post_scope"):
                parts += [f"### frames.{frame} —— {_FRAME_HEADERS[frame]}"
                          f"（{counts[frame]} 行）", ""]
                for cols, ctype, note in _FRAME_COLUMNS[frame]:
                    parts.append(f"- `{cols}`（{ctype}）：{note}")
                parts.append("")
            parts += [
                "aspect 取值（全量口径，必须精确匹配；括号内为该议题声明数）：" + _enum_line(
                    con, "semantic_aspect_metric", "aspect", enum_n,
                    value_column="claims"),
                "claims.aspect（精选子集）：" + _enum_line(
                    con, "semantic_claim_fact", "aspect", enum_n),
                "sentiment 取值：" + _enum_line(con, "semantic_claim_fact", "sentiment"),
                "journey 取值：" + _enum_line(con, "semantic_claim_fact", "journey"),
                "ownership 取值：" + _enum_line(con, "semantic_claim_fact", "ownership"),
                "claim_type 取值：" + _enum_line(con, "semantic_claim_fact", "claim_type"),
                f"experience 示例值：{_sample_values(con, sample_n)}",
                "post_scope.scope_status：" + " / ".join(
                    f"{k}={v}" for k, v in sorted(coverage["scope_status"].items())),
                f"post_scope.brand/series（in_scope）："
                + "、".join(f"{b}/{s}({c})" for b, s, c in coverage["brands"]),
                "", "### meta —— dict",
                f"data_version={coverage['version']}, "
                f"snapshot_hash={coverage['snapshot_hash']}",
                "", f"## 预置基准（{baseline.get('caliber') or '口径见各行数据'}）",
                _baseline_table(baseline, baseline_n), ""]
            return "\n".join(parts)

        text = render(config.BRIEF_SAMPLE_VALUES, config.BRIEF_ENUM_TOP_N,
                      config.BASELINE_TOP_ROWS)
        # Trim order: sample values -> baseline rows -> enum top-N. Never the
        # coverage declaration, brand list or date range (design D13).
        if len(text) > config.BRIEF_MAX_CHARS:
            text = render(1, config.BRIEF_ENUM_TOP_N, max(8, config.BASELINE_TOP_ROWS // 2))
        if len(text) > config.BRIEF_MAX_CHARS:
            text = render(0, 10, 5)
        return text
    finally:
        if own:
            con.close()
