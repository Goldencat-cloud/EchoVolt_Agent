# -*- coding: utf-8 -*-
"""水军嫌疑：规则法 + 库内聚合（design 决策7）。只标不排——spam_suspect 不影响子集。

规则（明细同步于 docs/data-contract.md）：
  r1_same_author_repeat : 同作者 ≥3 帖 norm_key 相同（协同模板）
  r2_cross_author_key   : 同一 norm_key 出现在 ≥2 个作者名下（跨账号共享模板）
  r3_new_account_burst  : 注册→发帖 ≤30 天 且 platform_post_count ≤5（新号爆发）
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from . import contracts as C

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = str(s).strip()[:19]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def compute_spam(rows: list[dict]) -> dict[str, dict]:
    """输入行字段：post_id, author_id, norm_key, excluded, published_at,
    registered_at_raw, platform_post_count。返回 post_id → {"spam_suspect": 0/1,
    "spam_reasons": {...}}。

    r1/r2 仅对未剔除行（excluded=''）且 norm_key 长度 ≥8 生效——超短键
    （"小米su7"、"不值"等常见短句）与已剔除内容（废串/删除标记）不构成协同模板依据。
    """
    reasons: dict[str, dict] = defaultdict(dict)

    # r1/r2：按 norm_key 聚合（空键/短键/已剔除行跳过）
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("norm_key") and len(r["norm_key"]) >= C.SPAM_MIN_KEY_LEN and r.get("excluded") == "":
            by_key[r["norm_key"]].append(r)
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        authors = {r["author_id"] for r in group}
        if len(authors) >= 2:  # r2 跨账号
            for r in group:
                reasons[r["post_id"]]["r2_cross_author_key"] = {
                    "norm_key_sample": key[:40],
                    "author_count": len(authors),
                    "post_ids": [x["post_id"] for x in group],
                }
        # r1 同作者多帖：按作者再聚合
        by_author: dict[str, list[dict]] = defaultdict(list)
        for r in group:
            by_author[r["author_id"]].append(r)
        for aid, arows in by_author.items():
            if len(arows) >= C.SPAM_SAME_AUTHOR_MIN_POSTS:
                for r in arows:
                    reasons[r["post_id"]]["r1_same_author_repeat"] = {
                        "author_id": aid,
                        "repeat_posts": len(arows),
                        "post_ids": [x["post_id"] for x in arows],
                    }

    # r3：新号爆发
    for r in rows:
        reg = _parse_date(r.get("registered_at_raw"))
        pub = _parse_date(r.get("published_at"))
        cnt = r.get("platform_post_count")
        if reg is None or pub is None or cnt is None:
            continue
        gap = (pub - reg).days
        if 0 <= gap <= C.SPAM_NEW_REG_GAP_DAYS and cnt <= C.SPAM_NEW_REG_MAX_POSTS:
            reasons[r["post_id"]]["r3_new_account_burst"] = {
                "registered_at": reg.isoformat(),
                "published_at": pub.isoformat(),
                "gap_days": gap,
                "platform_post_count": cnt,
            }

    return {
        pid: {"spam_suspect": 1 if why else 0, "spam_reasons": why}
        for pid, why in reasons.items()
    }


def reasons_to_json(reasons: dict) -> str:
    return json.dumps(reasons, ensure_ascii=False, sort_keys=True)
