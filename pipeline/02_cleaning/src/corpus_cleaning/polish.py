# -*- coding: utf-8 -*-
"""文本净化：norm_key 归一、polished_text 深度净化、polished_multimodal 平行清洗。

迁移自旧管线 deep_clean.py（clean_text/clean_multimodal），命名按 design 决策3 调整：
采集层已有 posts.clean_text（基本规范化），清洗层深度净化输出定名 polished_*。
"""
from __future__ import annotations

import json
import re
import unicodedata

from . import contracts as C


def normalize_base(s: str) -> str:
    """归一基座：去零宽字符、折叠空白、去首尾空白（对齐旧管线 text_content 规范化口径，
    作为 norm_key 与 text_changed 的比较基座；不改变净化输出本身）。"""
    if not s:
        return ""
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_key(s: str) -> str:
    """去重键：NFKC 全→半角 + ASCII 小写 + 连续空白压单空格。仅作键，不用于输出。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def _decode_entity(m: re.Match) -> str:
    e = m.group(1).lower()
    if e.startswith("#"):
        try:
            return chr(int(e[1:]))
        except ValueError:
            return m.group(0)
    return {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " "}.get(e, m.group(0))


def mask_phone(m: re.Match) -> str:
    g = m.group(0)
    return g[:3] + "****" + g[-4:]


def polish_text(s: str) -> str:
    """深度净化：实体解码、全角数字归一、剥离 @/#/URL、emoji 剔除、手机号/QQ/≥7位数字打码、折叠空白。

    保留全角标点（禁用 NFKC 处理输出）；emoji 不设独立列。
    """
    if not s:
        return ""
    s = C.HTML_ENT.sub(_decode_entity, s)
    s = s.translate(C.FW_DIGITS)
    s = C.URL.sub("", s)
    s = C.AT.sub("", s)
    s = C.HASH.sub("", s)
    s = C.PHONE.sub(mask_phone, s)
    s = C.QQ.sub("QQ****", s)
    s = C.LONGDIGIT.sub("****", s)
    s = C.EMOJI.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def polish_multimodal(segments_json: str) -> tuple[str, int, int]:
    """基于 content_segments_json 的平行清洗（保序）。

    text 段应用与 polish_text 同款净化；image/video 段 value 原样保留（SHALL NOT 剥离 URL）。
    返回 (polished_multimodal_json, 媒体段数_清洗前, 媒体段数_清洗后)。
    """
    if not segments_json or not segments_json.strip():
        return "", 0, 0
    try:
        obj = json.loads(segments_json)
    except (json.JSONDecodeError, TypeError):
        return segments_json, 0, 0
    if not isinstance(obj, list):
        return segments_json, 0, 0
    out: list = []
    media_before = media_after = 0
    for item in obj:
        if isinstance(item, dict) and item.get("kind") == "text":
            out.append({"kind": "text", "value": polish_text(item.get("value", ""))})
        else:
            media_before += 1
            media_after += 1
            out.append(item)  # 媒体段原样保留
    return json.dumps(out, ensure_ascii=False), media_before, media_after
