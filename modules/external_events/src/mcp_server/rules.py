"""启发式可信度分级与价值过滤规则（v2，task 2.1/2.8）。

跨域泛用原则：
- T1 = 政府域名后缀（可配置）∪ 显式官方域名 ∪ 自学习（域名含产品 ASCII token）；
- T2 = 通用权威综合媒体清单（跨行业，可配置）；T3 = 其余；
- 品牌/产品词从输入参数派生（brand_tokens），不依赖行业词表；
- 黑名单为极小通用集。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent / "source_rules.json"

_DEFAULTS: dict = {
    "tld_t1_domains": [], "t2_domains": [], "blacklist_domains": [],
    "ugc_domains": [],
    "confidence": {"tier_base": {"T1": 90, "T2": 70, "T3": 40},
                   "ugc_penalty": 40, "official_bonus": 10,
                   "has_date_bonus": 10, "min_event_authority": 50},
    "cluster": {"cos_threshold": 0.55, "date_window_days": 3},
    "subtype_hints": [],
}


def load_rules(path: Path | None = None) -> dict:
    p = path or RULES_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return merged


def brand_tokens(brand: str, product: str) -> list[str]:
    """品牌/产品词表从输入参数派生（跨域泛用的关键）。"""
    toks = {t.strip() for t in (brand, product, f"{brand}{product}") if t and t.strip()}
    return sorted(toks, key=len, reverse=True)


def _suffix_match(domain: str, entries: list[str]) -> bool:
    d = domain.lower().lstrip(".")
    return any(d == e.lower() or d.endswith("." + e.lower()) for e in entries)


def learn_official(domain: str, product: str) -> bool:
    """自学习：结果域名包含产品的 ASCII token（如 SU7）→ 视作品牌官方域。"""
    m = re.search(r"[A-Za-z0-9]{2,}", product or "")
    if not m:
        return False
    return m.group(0).lower() in domain.lower()


def tier_of(domain: str, rules: dict, official: frozenset[str] = frozenset()) -> str:
    d = domain.lower()
    if _suffix_match(d, rules["tld_t1_domains"]) or d in official or d.lstrip(".") in official:
        return "T1"
    if _suffix_match(d, rules["t2_domains"]):
        return "T2"
    return "T3"


def noise_reason(title: str, content: str, domain: str, rules: dict,
                 tokens: list[str], strict: bool) -> str | None:
    """noise 判定：黑名单恒生效；strict 主题要求标题/摘要含品牌或产品词。"""
    if _suffix_match(domain.lower(), rules["blacklist_domains"]):
        return "blacklist_domain"
    if strict:
        text = f"{title} {content}".lower()
        if not any(t.lower() in text for t in tokens):
            return "off_topic"
    return None


def subtype_of(title: str, rules: dict) -> str:
    """回退模式的通用 subtype 关键词映射。"""
    t = title.lower()
    for kw, sub in rules.get("subtype_hints", []):
        if kw.lower() in t:
            return sub
    return "other"


def is_ugc(domain: str, rules: dict) -> bool:
    """UGC 自媒体平台（软文/洗稿高发区）：置信度重罚，不可单独支撑事件。"""
    return _suffix_match(domain.lower(), rules.get("ugc_domains", []))


def confidence_of(domain: str, tier: str, rules: dict,
                  official: frozenset[str] = frozenset(), has_date: bool = True) -> int:
    """来源置信度打分（0-100，权威性核查制度）。

    base 按分级（T1=90/T2=70/T3=40）；UGC 平台重罚；官方域名加成；
    有可溯源日期加成。事件不得仅由低置信来源支撑（min_event_authority）。
    """
    c = rules.get("confidence", {})
    score = c.get("tier_base", {}).get(tier, 40)
    if is_ugc(domain, rules):
        score -= c.get("ugc_penalty", 40)
    d = domain.lower().lstrip(".")
    if d in official or _suffix_match(d, rules["tld_t1_domains"]):
        score += c.get("official_bonus", 10)
    if has_date:
        score += c.get("has_date_bonus", 10)
    return max(0, min(100, int(score)))
