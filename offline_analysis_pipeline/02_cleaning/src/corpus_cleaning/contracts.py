# -*- coding: utf-8 -*-
"""清洗规则常量（规则明细同步维护于 docs/data-contract.md，两处一致）。"""
from __future__ import annotations

import re

# ---- 剔除/标注 ----
DELETE_MARKER = "本楼已被删除"
JUNK = re.compile(r"查看详情|我要申诉|加载中|点击展开|展开更多")
# 仅最退化的装饰性符号算纯符号 junk；？！… 等表达性标点保留
JUNK_SYMBOLS = set("*\u2022·.。，、#")

# ---- 净化 ----
EMOJI = re.compile(
    r"[\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\uFE00-\uFE0F\u2190-\u21FF]"
)
URL = re.compile(r"https?://\S+|www\.\S+")
AT = re.compile(r"@[A-Za-z0-9_一-鿿]+")
HASH = re.compile(r"#[^\s#]+#")
HTML_ENT = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d+);", re.IGNORECASE)
# ⚠️ 禁止对输出文本用 NFKC：会把全角标点 ，！？：； 转半角；仅数字 ０-９ 归一
FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# ---- 隐私脱敏（仅 polished 列）----
PHONE = re.compile(r"1[3-9]\d{9}")
QQ = re.compile(r"QQ\s*[号码]{0,2}\s*[:：]?\s*\d{5,11}", re.IGNORECASE)
LONGDIGIT = re.compile(r"\d{7,}")

# ---- 广告识别：联系方式模式 × 促销话术 组合命中才标 advertising ----
AD_CONTACT = re.compile(
    r"1[3-9]\d{9}"
    r"|QQ\s*[号码]{0,2}\s*[:：]?\s*\d{5,11}"
    r"|(?:微信|加\s*[VvＶ]|Ｖ信|V信|wx|vx|威信)\s*[:：号]?\s*[A-Za-z0-9_\-\u4e00-\u9fff]{5,}"
    r"|\d{7,}"
)
AD_PROMO = re.compile(
    r"低价|优惠|折扣|代购|转让|出售|车贷|贷款|月供|分期|返现|特惠|内部价|底价|秒杀|清仓|免定金|提车补贴|激活码"
)
# 辅助信号：外链堆叠（单独不构成 advertising，仅入 reasons）
AD_URL_STACK_MIN = 3

# ---- 水军嫌疑（库内聚合，只标不排）----
SPAM_SAME_AUTHOR_MIN_POSTS = 3     # 同作者 ≥3 帖 norm_key 相同
SPAM_MIN_KEY_LEN = 8               # r1/r2 归一键最小长度（排除超短常见语与已剔除内容）
SPAM_NEW_REG_GAP_DAYS = 30         # 注册→发帖间隔 ≤30 天
SPAM_NEW_REG_MAX_POSTS = 5         # 且 platform_post_count ≤5 视为新号

# ---- 旧实测校验锚点（design 决策5；允许个位数漂移但须逐项解释）----
ANCHORS = {
    "post_deleted": 3,
    "empty_no_media": 21,
    "duplicate_rows": 61,
    "system_junk": 4,
    "gibberish": 1,
    "clean_subset": 9701,
    "text_changed": 667,
    "multimodal_urls_before": 22681,  # 旧管线口径；新库 image+video 段总数为准，漂移须解释
}
