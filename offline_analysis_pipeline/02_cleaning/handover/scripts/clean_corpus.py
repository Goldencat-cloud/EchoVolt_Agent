"""数据清洗管线 A1：将汽车之家小米 SU7 原始论坛评论数据清洗为可追溯语料。

输入：data/processed/汽车之家_小米SU7_论坛帖子数据.xlsx
输出：data/processed/汽车之家_小米SU7_清洗语料.csv（utf-8-sig）
     列含 post_id/title/source_url/text_content/multimodal_content/created_at/
     views/replies/image_count/images/video_ids/tags/author_*/owner_segment。

设计依据：openspec/changes/data-cleaning-pipeline 的 proposal / specs / design / tasks。
核心约束（B5 可追溯）：保留 post_id（派生自帖子链接），每行可回查原文；
multimodal_content 以 JSON 保留全文图文/视频有序分段，供下游还原"文字↔媒体"对应关系。
纯图片/纯视频帖保留，无文本正文则 text_content 留空。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pandas as pd

# 爬虫爬取日：帖子相对时间（"N天前"）按此反推用于交叉校验。
CRAWL_DATE = datetime(2026, 10, 3)

INPUT_PATH = "data/processed/汽车之家_小米SU7_论坛帖子数据.xlsx"
OUTPUT_PATH = "data/processed/汽车之家_小米SU7_清洗语料.csv"

DELETE_MARKER = "本楼已被删除"
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
WS = re.compile(r"\s+")
THREAD_ID = re.compile(r"/thread/([0-9a-fA-F]+)/")
CN_INT = re.compile(r"(\d+(?:\.\d+)?)\s*(万|亿)?")
RELATIVE = re.compile(r"(\d+)\s*(秒|分钟|分|小时|天|日|周|个月|月|年)")

# 与作者信息 JSON 完全重复、需在输出中丢弃的独立作者列（含列表页变体）。
REDUNDANT_AUTHOR_COLS = [
    "作者昵称", "作者帖子数", "作者热门帖数", "作者回复数", "作者注册时间",
    "作者来自", "作者爱车", "作者主页", "作者热门帖链接",
    "作者昵称_列表页", "作者主页_列表页",
]
# 已被解析后字段替代、丢弃的原始列。
DROP_RAW_COLS = [
    "帖子相对时间", "正文", "全文", "图片链接", "视频ID", "作者信息",
    "是否匹配正文",
] + REDUNDANT_AUTHOR_COLS


def normalize_text(s: str) -> str:
    """去零宽字符、折叠空白、strip；保留 emoji。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = ZERO_WIDTH.sub("", str(s))
    s = WS.sub(" ", s).strip()
    return s


def parse_cn_int(s) -> int | None:
    """剥离中文单位（浏览/回帖/张/万/亿）提取整数。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    m = CN_INT.search(str(s))
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        num *= 1e4
    elif unit == "亿":
        num *= 1e8
    return int(num)


def parse_content(s) -> tuple[str, list[dict]]:
    """解析 [[\"text\", \"...\"]] 返回 (拼接文本, 有序分段 blocks)。blocks 保留原始顺序，供下游还原"文字↔图片/视频"对应关系。失败/空返回 ("", [])。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return "", []
    try:
        arr = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return "", []
    if not isinstance(arr, list):
        return "", []
    text_parts: list[str] = []
    blocks: list[dict] = []
    for seg in arr:
        if not (isinstance(seg, list) and len(seg) > 1):
            continue
        t, v = seg[0], seg[1]
        blocks.append({"type": t, "v": v})
        if t == "text":
            text_parts.append(v)
    return "".join(text_parts), blocks


def parse_url_list(s, filter_substr: str | None = None) -> list[str] | None:
    """解析 JSON 字符串数组；返回 None 表示解析失败（供 parse_error 标记）。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return []
    try:
        arr = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(arr, list):
        return []
    out = [u for u in arr if isinstance(u, str)]
    if filter_substr:
        out = [u for u in out if filter_substr not in u]
    return out


def parse_author(s) -> dict:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {"_parse_error": True}


def parse_relative(s) -> datetime | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip()
    if "刚刚" in s:
        return CRAWL_DATE
    m = RELATIVE.search(s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "秒":
        delta = timedelta(seconds=n)
    elif unit in ("分钟", "分"):
        delta = timedelta(minutes=n)
    elif unit == "小时":
        delta = timedelta(hours=n)
    elif unit in ("天", "日"):
        delta = timedelta(days=n)
    elif unit == "周":
        delta = timedelta(weeks=n)
    elif unit in ("个月", "月"):
        delta = timedelta(days=n * 30)
    elif unit == "年":
        delta = timedelta(days=n * 365)
    else:
        return None
    return CRAWL_DATE - delta


def strip_url_suffix(url: str) -> str:
    """去掉 #pvareaid... 之类的追踪参数，便于比较同一用户主页。"""
    return url.split("#")[0] if url else url


def main() -> None:
    raw = pd.read_excel(INPUT_PATH, dtype=str)
    total = len(raw)
    log = {"total": total}

    # ---- 2.1 内容字段：权威 text_content + 保序 multimodal_content；正文冗余不输出 ----
    parsed = raw["全文"].apply(parse_content)
    raw["_content"] = parsed.apply(lambda p: p[0])
    raw["_blocks"] = parsed.apply(lambda p: p[1])
    raw["_snippet"] = raw["正文"].apply(
        lambda x: normalize_text(x) if not (x is None or (isinstance(x, float) and pd.isna(x))) else ""
    )

    # ---- 2.2 图片 / 视频 ----
    raw["_images"] = raw["图片链接"].apply(lambda x: parse_url_list(x, filter_substr="smiles"))
    raw["_videos"] = raw["视频ID"].apply(lambda x: parse_url_list(x))
    raw["_img_parse_err"] = raw["_images"].isna()
    raw["_vid_parse_err"] = raw["_videos"].isna()
    raw["_images"] = raw["_images"].apply(lambda v: v if v is not None else [])
    raw["_videos"] = raw["_videos"].apply(lambda v: v if v is not None else [])

    # ---- 2.3 作者信息解析 + 一致性断言 ----
    raw["_author"] = raw["作者信息"].apply(parse_author)
    raw["_auth_parse_err"] = raw["_author"].apply(lambda d: bool(d.get("_parse_error")))

    def auth_field(row, key, src_col=None):
        val = row["_author"].get(key)
        return val

    raw["author_nick"] = raw["_author"].apply(lambda d: d.get("昵称", ""))
    raw["author_home"] = raw["_author"].apply(lambda d: d.get("主页", ""))
    raw["author_post_count"] = raw["_author"].apply(lambda d: parse_cn_int(d.get("帖子数")))
    raw["author_hot_post_count"] = raw["_author"].apply(lambda d: parse_cn_int(d.get("热门帖数")))
    raw["author_reply_count"] = raw["_author"].apply(lambda d: parse_cn_int(d.get("回复数")))
    raw["author_reg_date"] = raw["_author"].apply(lambda d: d.get("注册时间", ""))
    raw["author_location"] = raw["_author"].apply(lambda d: d.get("来自", ""))
    raw["author_car"] = raw["_author"].apply(lambda d: d.get("爱车", ""))

    # 一致性断言：解析字段与原独立作者列 0 处不一致。
    # 数值字段两侧都用 parse_cn_int 解析后按整数比较，避免 pandas 将含 None 的
    # 数值列统一为 float64（186 -> 186.0）造成的字符串比较误判。
    # URL 字段去掉追踪后缀后比较；空串与 NaN 视为同一空值。
    # 作者热门帖链接未纳入输出，按 task 5.2 一并丢弃。
    def _empty(v):
        return v is None or (isinstance(v, float) and pd.isna(v))

    mismatches = 0
    num_pairs = [("帖子数", "作者帖子数"), ("热门帖数", "作者热门帖数"), ("回复数", "作者回复数")]
    for key, col in num_pairs:
        a = raw["_author"].apply(lambda d: parse_cn_int(d.get(key)))
        b = raw[col].apply(parse_cn_int)
        mismatches += int((a.fillna(-1).astype("int64") != b.fillna(-1).astype("int64")).sum())

    str_pairs = [
        ("昵称", "作者昵称"),
        ("主页", "作者主页", strip_url_suffix),
        ("注册时间", "作者注册时间"),
        ("来自", "作者来自"),
        ("爱车", "作者爱车"),
    ]
    for item in str_pairs:
        key, col = item[0], item[1]
        fn = item[2] if len(item) > 2 else (lambda x: x)
        a = raw["_author"].apply(lambda d: "" if d.get(key) is None else fn(d.get(key)))
        b = raw[col].apply(lambda v: "" if _empty(v) else fn(v))
        mismatches += int((a.astype(str) != b.astype(str)).sum())
    assert mismatches == 0, f"作者信息解析与原列不一致 {mismatches} 处"
    log["author_mismatches"] = mismatches

    # ---- 3.1 数字字段 ----
    # image_count 以 multimodal_content 中的 img 段数量为准（可追溯的权威图文序列）；
    # "列表图片数"为列表页抓取字段，大量缺失，不可作为图片数来源。
    raw["image_count"] = raw["_blocks"].apply(
        lambda b: sum(1 for x in b if isinstance(x, dict) and x.get("type") == "img")
    )

    # ---- 3.2 时间字段 + 相对时间交叉校验 ----
    raw["created_at"] = pd.to_datetime(raw["发布时间"], errors="coerce")
    created_fail = int(raw["created_at"].isna().sum())
    log["created_at_parse_fail"] = created_fail

    raw["_rel_expected"] = raw["帖子相对时间"].apply(parse_relative)
    rel_mismatch = int(
        ((raw["_rel_expected"].notna()) & (raw["created_at"].notna())
         & ((raw["_rel_expected"].dt.date - raw["created_at"].dt.date).abs()
            > timedelta(days=2))).sum()
    )
    log["relative_time_mismatch"] = rel_mismatch

    # ---- 4.1 文本规范化 ----
    raw["text_content"] = raw["_content"].apply(normalize_text)
    raw["title"] = raw["帖子标题"].apply(normalize_text)
    zero_width_fixed = int((raw["_content"].str.contains(ZERO_WIDTH, na=False)
                            | raw["正文"].fillna("").str.contains(ZERO_WIDTH, na=False)).sum())
    log["zero_width_fixed"] = zero_width_fixed

    # ---- 5.1 标记 ----
    raw["owner_segment"] = raw.apply(
        lambda r: "owner" if "小米SU7" in str(r["author_car"])
        else ("other" if str(r["author_car"]).strip() else "unknown"),
        axis=1,
    )

    # 作者来自 拆省/市
    def split_location(loc):
        loc = str(loc).strip()
        if not loc:
            return "", ""
        parts = loc.split()
        return parts[0], " ".join(parts[1:])

    raw["author_province"] = raw["author_location"].apply(lambda l: split_location(l)[0])
    raw["author_city"] = raw["author_location"].apply(lambda l: split_location(l)[1])

    # ---- 6.1 post_id ----
    def derive_post_id(url):
        if url is None or (isinstance(url, float) and pd.isna(url)):
            return ""
        m = THREAD_ID.search(str(url))
        return m.group(1) if m else str(url)

    raw["post_id"] = raw["帖子链接"].apply(derive_post_id)

    # ---- 4.2 噪声剔除：仅剔除删除帖与"无文本且无媒体"的空行；纯媒体帖保留（text_content 留空） ----
    del_mask = (raw["_content"].fillna("").str.contains(DELETE_MARKER)
                | raw["_snippet"].str.contains(DELETE_MARKER, na=False))
    no_text = (raw["_content"].fillna("").str.len() == 0) & (raw["_snippet"].str.len() == 0)
    no_media = (raw["_images"].str.len() == 0) & (raw["_videos"].str.len() == 0)
    empty_mask = no_text & no_media
    remove_mask = del_mask | empty_mask
    log["removed_deleted"] = int(del_mask.sum())
    log["removed_empty_no_media"] = int(empty_mask.sum())
    log["removed_total"] = int(remove_mask.sum())

    clean = raw.loc[~remove_mask].copy()

    # ---- 5.2 / 6.2 组装输出列 ----
    clean["images"] = clean["_images"].apply(json.dumps)
    clean["video_ids"] = clean["_videos"].apply(json.dumps)
    clean["multimodal_content"] = clean["_blocks"].apply(
        lambda b: json.dumps(b, ensure_ascii=False)
    )
    clean["tags"] = clean["帖子标签"].fillna("")
    clean["source_url"] = clean["帖子链接"]
    clean["created_at"] = clean["created_at"].apply(
        lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(x) else ""
    )

    out_cols = [
        "post_id", "title", "source_url", "text_content", "multimodal_content",
        "created_at", "views", "replies", "image_count", "images", "video_ids",
        "tags", "author_nick", "author_home", "author_post_count",
        "author_hot_post_count", "author_reply_count", "author_reg_date",
        "author_location", "author_province", "author_city", "author_car",
        "owner_segment",
    ]
    out = clean[out_cols]
    out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    log["output_rows"] = len(out)
    log["post_id_unique"] = int(out["post_id"].is_unique)
    log["owner_rows"] = int((out["owner_segment"] == "owner").sum())

    print("=== 清洗日志 ===")
    for k, v in log.items():
        print(f"  {k}: {v}")
    print(f"输出已写入: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
