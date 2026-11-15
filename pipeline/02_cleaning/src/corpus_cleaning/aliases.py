# -*- coding: utf-8 -*-
"""产品别名映射（design 决策8）。四类来源：official/variant/community/competitor。

规范链：每个别名解析到显式的 品牌/车系/配置 三级 canonical（名称+ID），LLM 抽取的
产品提及可经 alias_norm 回溯到规范名。方向性约束（Owner 2026-10-22 指示）：只向上
归一（细→粗）——车系名/品牌名/无配置语境短语只到 series 级；仅别名自身含完整配置
语义（官方 spec 全名，或仅剥年款前缀）时才到 spec 级；community 候选一律 series 级。
"""
from __future__ import annotations

import re
from collections import Counter

from .polish import norm_key

# 剥配置语义的词元（variant 机械生成用；剥离后 canonical 上移到 series 级）
CONFIG_TOKENS = ["后驱", "四驱", "长续航", "超长续航", "高阶智驾", "智驾", "标准", "创始", "猜想图", "pro", "max", "l", "版"]
# series 短名组合后缀（社区常见写法生成；生成有无空格两种形态）
SERIES_COMBO_SUFFIXES = ["标准版", "标准", "pro版", "max版", "pro", "max"]
BRAND_PREFIX = "小米"
YEAR_PREFIX = re.compile(r"^\d{4}款\s*")
# 语料候选词：拉丁数字串 / 汉字开头的混合串（2-16 长度）
CANDIDATE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,15}|[一-鿿][一-鿿0-9A-Za-z]{1,15}")
COMMUNITY_MIN_FREQ = 5
COMMUNITY_MAX_EDIT_DISTANCE = 2
COMMUNITY_MAX_CANDIDATES = 50


def _is_plausible_candidate(token: str) -> bool:
    """通用词过滤：候选须含数字、或以汉字开头、或长度≥4（排除 HUD/SUV/bug/SU 等）。"""
    t = token.strip()
    if not t:
        return False
    if any(ch.isdigit() for ch in t):
        return True
    if re.search(r"[一-鿿]", t):
        return True
    return len(t) >= 4


# 竞品人工种子：(归一别名输入, 品牌, 车系)。status=pending，人工确认后才被抽取消费。
COMPETITOR_SEEDS: list[tuple[str, str, str]] = [
    ("model 3", "特斯拉", "Model 3"),
    ("model y", "特斯拉", "Model Y"),
    ("极氪001", "极氪", "极氪001"),
    ("极氪007", "极氪", "极氪007"),
    ("小鹏p7", "小鹏", "小鹏P7"),
    ("蔚来et5", "蔚来", "蔚来ET5"),
    ("智界s7", "智界", "智界S7"),
    ("极越07", "极越", "极越07"),
    ("汉ev", "比亚迪", "汉EV"),
    ("yu7", "小米", "小米YU7"),
]


def edit_distance(a: str, b: str, cap: int = COMMUNITY_MAX_EDIT_DISTANCE) -> int:
    """短串编辑距离（Levenshtein，带剪枝上限）。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _strip_tokens(s: str, tokens: list[str]) -> str:
    out = s
    changed = True
    ordered = sorted(tokens, key=len, reverse=True)  # 长词元优先，避免"长续航"误剥"超长续航"
    while changed:
        changed = False
        for t in ordered:
            if t.isascii():
                new = re.sub(re.escape(t), "", out, flags=re.IGNORECASE)
            else:
                new = out.replace(t, "")
            if new != out:
                out = new.strip()
                changed = True
    return out.strip()


def _row(alias_display: str, alias_type: str, source: str, status: str,
         created_at: str, canon: dict, match_method: str = "exact") -> dict:
    """构造别名行。canon 为规范链：brand_name/series_name/series_id/spec_id/spec_name。

    spec 级行必须带完整三级链；series 级行 spec 两字段为空；竞品行仅名称（库内无 id）。
    """
    sid, spid = canon.get("series_id"), canon.get("spec_id")
    if alias_type in ("official", "variant"):
        assert spid is None or sid is not None, "spec 级必须带所属车系 id"
        assert status == "confirmed", "official/variant 机械生成即为 confirmed"
        assert canon.get("brand_name") and canon.get("series_name"), "official/variant 须带品牌/车系规范名"
        assert spid is None or canon.get("spec_name"), "spec 级必须带规范配置名"
    return {
        "alias_norm": norm_key(alias_display),
        "alias_display": alias_display,
        "alias_type": alias_type,
        "source": source,
        "status": status,
        "match_method": match_method,
        "canonical_brand_name": canon.get("brand_name"),
        "canonical_series_name": canon.get("series_name"),
        "canonical_series_id": sid,
        "canonical_spec_id": spid,
        "canonical_spec_name": canon.get("spec_name"),
        "created_at": created_at,
    }


def build_official_variant(specs: list[dict], created_at: str) -> list[dict]:
    """official/variant 机械生成。specs 行含 spec_id/series_id/spec_name/series_name/brand_name。

    - official：spec 全名→spec 级（含完整链）；series_name/brand_name→series 级（brand 仅单 series 时登记）。
    - variant：剥年款前缀→spec 级（年款不改变粒度）；剥年款+配置词元→series 级（粒度上移）。
    """
    rows: list[dict] = []
    series_of_brand: dict[str, set[str]] = {}
    for s in specs:
        series_of_brand.setdefault(s["brand_name"], set()).add(s["series_id"])
    single_series_brands = {b for b, ids in series_of_brand.items() if len(ids) == 1}

    for s in specs:
        spec_canon = {"brand_name": s["brand_name"], "series_name": s["series_name"],
                      "series_id": s["series_id"], "spec_id": s["spec_id"], "spec_name": s["spec_name"]}
        series_canon = {"brand_name": s["brand_name"], "series_name": s["series_name"],
                        "series_id": s["series_id"]}
        # official
        rows.append(_row(s["spec_name"], "official", "product_specs", "confirmed", created_at, spec_canon))
        rows.append(_row(s["series_name"], "official", "product_specs", "confirmed", created_at, series_canon))
        if s["brand_name"] in single_series_brands:
            rows.append(_row(s["brand_name"], "official", "product_specs", "confirmed", created_at, series_canon))
        # variant：仅剥年款 → 仍 spec 级
        stripped_year = YEAR_PREFIX.sub("", s["spec_name"]).strip()
        if stripped_year and norm_key(stripped_year) != norm_key(s["spec_name"]):
            rows.append(_row(stripped_year, "variant", "rule_strip_year", "confirmed", created_at, spec_canon))
        # variant：剥年款 + 配置词元 → 上移 series 级
        stripped_cfg = _strip_tokens(stripped_year, CONFIG_TOKENS).strip()
        if stripped_cfg and norm_key(stripped_cfg) != norm_key(stripped_year):
            rows.append(_row(stripped_cfg, "variant", "rule_strip_config", "confirmed", created_at, series_canon))

    # series 短名与社区组合写法（series 级，向上归一）
    series_names = {s["series_id"]: (s["series_name"], s["brand_name"]) for s in specs}
    for sid, (sname, bname) in series_names.items():
        short = sname
        if sname.startswith(BRAND_PREFIX):
            short = sname[len(BRAND_PREFIX):].strip()
            rows.append(_row(short, "variant", "rule_strip_brand", "confirmed", created_at,
                             {"brand_name": bname, "series_name": sname, "series_id": sid}))
        for suffix in SERIES_COMBO_SUFFIXES:
            for disp in (f"{short}{suffix}", f"{short} {suffix}"):
                rows.append(_row(disp, "variant", "rule_series_combo", "confirmed", created_at,
                                 {"brand_name": bname, "series_name": sname, "series_id": sid}))
    return rows


def mine_community(specs: list[dict], corpus_texts: list[str], created_at: str,
                   existing_norms: frozenset[str] | set[str] = frozenset()) -> tuple[list[dict], dict]:
    """语料挖掘 community 候选 + 覆盖统计。

    - 覆盖：语料词元（去空格归一）命中既有 alias → 记入 stats.matched；
    - 候选：词元 freq≥5、与既有 alias 去空格编辑距离 ≤2、不是既有 alias、非切词碎片
      → status=pending，match_method='fuzzy'，规范链提案到 series 级（人工确认才生效）。
    """
    known: dict[str, dict] = {}
    for s in specs:
        for disp, sid, spid in (
            (s["spec_name"], None, s["spec_id"]),
            (YEAR_PREFIX.sub("", s["spec_name"]).strip(), None, s["spec_id"]),
            (s["series_name"], s["series_id"], None),
        ):
            if disp:
                known[norm_key(disp).replace(" ", "")] = {"series_id": sid, "spec_id": spid}
        short = s["series_name"][len(BRAND_PREFIX):].strip() if s["series_name"].startswith(BRAND_PREFIX) else s["series_name"]
        for suffix in [""] + SERIES_COMBO_SUFFIXES:
            for disp in (f"{short}{suffix}", f"{short} {suffix}"):
                if disp.strip():
                    known[norm_key(disp).replace(" ", "")] = {"series_id": s["series_id"], "spec_id": None}

    freq: Counter[str] = Counter()
    for text in corpus_texts:
        if not text:
            continue
        for m in CANDIDATE_TOKEN.finditer(text):
            freq[m.group(0)] += 1

    matched = Counter()
    candidates: list[dict] = []
    for token, n in freq.most_common():
        key = norm_key(token).replace(" ", "")
        if key in known:
            matched[key] += n
            continue
        if norm_key(token) in existing_norms:
            continue  # 已存在于别名表（official/variant/竞品种子等），不重复出候选
        if not _is_plausible_candidate(token):
            continue
        # 切词碎片过滤：候选与已知别名互为包含（"买SU7"/"米SU7"/"小米SU7上市"）不是拼写变体
        if any((k in key) or (key in k) for k in known if len(k) >= 3):
            continue
        if n < COMMUNITY_MIN_FREQ or len(candidates) >= COMMUNITY_MAX_CANDIDATES:
            continue
        best = None
        best_d = COMMUNITY_MAX_EDIT_DISTANCE + 1
        for k, info in known.items():
            d = edit_distance(key, k)
            if d < best_d:
                best, best_d = info, d
        if best is not None:
            # 模糊候选不预设归属（编辑距离 ≤2 的词可能是其他车型，如 M7/L7）：
            # canonical 留空，status=pending，人工确认时填写品牌/车系（或 rejected）。
            candidates.append(_row(token, "community", "corpus_mining", "pending", created_at,
                                   {}, match_method="fuzzy"))
    stats = {
        "known_alias_count": len(known),
        "matched_total_occurrences": int(sum(matched.values())),
        "matched_distinct": len(matched),
        "pending_candidates": len(candidates),
    }
    return candidates, stats


def competitor_rows(created_at: str) -> list[dict]:
    """竞品人工种子：带品牌/车系规范名，status=pending，人工确认后重跑不覆盖。
    竞品在库内无 series/spec 实体，id 类字段为 NULL，规范名为纯文本（"品牌 车系"）。
    alias_norm 取语料写法（如"model 3"），display 为规范名（"特斯拉 Model 3"）。"""
    rows = []
    for alias, brand, series in COMPETITOR_SEEDS:
        disp = series if series.startswith(brand) else f"{brand} {series}"
        r = _row(alias, "competitor", "manual_seed", "pending", created_at,
                 {"brand_name": brand, "series_name": series}, match_method="seed")
        r["alias_display"] = disp
        rows.append(r)
    return rows


def load_corpus_texts(posts: list[dict]) -> list[str]:
    return [f"{p.get('title') or ''} {p.get('body_text') or ''}" for p in posts]
