# -*- coding: utf-8 -*-
"""标注判定：删除帖/空媒体剔除、废串/纯符号、广告、车主分群、去重分组。"""
from __future__ import annotations

import json
import re

from . import contracts as C
from .polish import norm_key

CJK_ALNUM = re.compile(r"[A-Za-z0-9一-鿿]")


def parse_segments(segments_json: str) -> list[dict]:
    """解析 content_segments_json；非法/空返回 []。段字段为 kind/value/locator。"""
    if not segments_json or not segments_json.strip():
        return []
    try:
        obj = json.loads(segments_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return obj if isinstance(obj, list) else []


def has_media(segments: list[dict]) -> bool:
    return any(isinstance(seg, dict) and seg.get("kind") in ("image", "video") for seg in segments)


def count_media(segments: list[dict]) -> int:
    return sum(1 for seg in segments if isinstance(seg, dict) and seg.get("kind") in ("image", "video"))


def classify_excluded(base: str, body_raw: str, clean_text: str, media: bool) -> tuple[str, dict]:
    """剔除级判定，返回 (excluded, reasons)。优先级：post_deleted > empty_no_media >
    system_junk > gibberish > advertising。空文本纯媒体帖不剔除（excluded=''）。

    base 为归一基座（去零宽+折叠空白）；body_raw/clean_text 仅用于删除标记双保险匹配。
    Owner 指示（design 决策4）：不做疑似删除标注，不设 post_removed 类别。
    """
    reasons: dict = {}
    if (C.DELETE_MARKER in base or C.DELETE_MARKER in body_raw
            or C.DELETE_MARKER in (clean_text or "")):
        return "post_deleted", {"marker": C.DELETE_MARKER}
    if base == "" and not media:
        return "empty_no_media", {}
    if base == "":
        return "", {}  # 空文本=纯媒体帖，保留
    if C.JUNK.search(base):
        return "system_junk", {"junk_pattern": C.JUNK.pattern}
    # gibberish：纯 emoji 不标；去 emoji/空白后无汉字字母数字且余量全为装饰符号才标
    t = C.EMOJI.sub("", base)
    t = re.sub(r"\s", "", t)
    if t != "" and not CJK_ALNUM.search(t):
        remnant = CJK_ALNUM.sub("", t)
        if remnant and all(ch in C.JUNK_SYMBOLS for ch in remnant):
            return "gibberish", {"remnant": remnant[:20]}
    ad, ad_reasons = classify_advertising(base)
    if ad:
        return "advertising", ad_reasons
    return "", reasons


def classify_advertising(body: str) -> tuple[bool, dict]:
    """广告判定：联系方式模式 × 促销话术 组合命中才标（避免"这车广告打得好"误伤）；
    外链堆叠（≥3 URL）为辅助信号，单独不构成 advertising。"""
    reasons: dict = {}
    contact = C.AD_CONTACT.search(body)
    promo = C.AD_PROMO.search(body)
    urls = len(C.URL.findall(body))
    if contact:
        reasons["contact_pattern"] = contact.group(0)[:20]
    if promo:
        reasons["promo_keyword"] = promo.group(0)
    if urls >= C.AD_URL_STACK_MIN:
        reasons["url_stack"] = urls
    hit = bool(contact and promo)
    return hit, reasons


def dedup(rows: list[tuple[str, str]]) -> tuple[dict[str, int], dict[str, bool], int]:
    """对 (post_id, norm_key) 序列（rowid 序）分组。同组首条 is_duplicate=False；
    空 norm_key 不参与（dedup_group_id=0）。返回 (group_by_post, dup_by_post, 组数)。
    参与范围：excluded 不为 post_deleted/empty_no_media 的行（对齐旧管线：先剔除后去重）。"""
    groups: dict[str, int] = {}
    group_by_post: dict[str, int] = {}
    dup_by_post: dict[str, bool] = {}
    gid = 0
    for pid, key in rows:
        if not key:
            group_by_post[pid] = 0
            dup_by_post[pid] = False
            continue
        if key in groups:
            group_by_post[pid] = groups[key]
            dup_by_post[pid] = True
        else:
            groups[key] = gid
            group_by_post[pid] = gid
            dup_by_post[pid] = False
            gid += 1
    return group_by_post, dup_by_post, gid
