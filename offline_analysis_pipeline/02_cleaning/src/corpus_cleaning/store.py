# -*- coding: utf-8 -*-
"""stock 库连接与标注落库。

只读边界：业务表（posts/users/product_specs/product_parameters/source_snapshots/
collection_*）一律不写；写操作仅限 cleaning_annotations、product_aliases 与
v_clean_subset 视图。全部写入单事务，同 cleaning_version 重跑幂等（整表替换）。
"""
from __future__ import annotations

import sqlite3

DDL_ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS cleaning_annotations (
  post_id TEXT PRIMARY KEY REFERENCES posts(post_id),
  cleaning_version TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  excluded TEXT NOT NULL DEFAULT '',
  norm_key TEXT,
  dedup_group_id INTEGER NOT NULL DEFAULT 0,
  is_duplicate INTEGER NOT NULL DEFAULT 0,
  polished_text TEXT,
  polished_multimodal TEXT,
  text_changed INTEGER NOT NULL DEFAULT 0,
  spam_suspect INTEGER NOT NULL DEFAULT 0,
  spam_reasons_json TEXT NOT NULL DEFAULT '{}'
)
"""

DDL_ALIASES = """
CREATE TABLE IF NOT EXISTS product_aliases (
  alias_norm TEXT PRIMARY KEY,
  alias_display TEXT NOT NULL,
  alias_type TEXT NOT NULL CHECK (alias_type IN ('official','variant','community','competitor')),
  source TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('confirmed','pending','rejected')),
  match_method TEXT NOT NULL DEFAULT 'exact',
  canonical_brand_name TEXT,
  canonical_series_name TEXT,
  canonical_series_id TEXT,
  canonical_spec_id TEXT,
  canonical_spec_name TEXT,
  created_at TEXT NOT NULL
)
"""

VIEW_ALIAS_RESOLVED = """
CREATE VIEW IF NOT EXISTS v_alias_resolved AS
SELECT alias_display AS 原始写法, status AS 状态, match_method AS 匹配方式,
       alias_type AS 类型, canonical_brand_name AS 规范品牌,
       canonical_series_name AS 规范车系, canonical_series_id AS 车系ID,
       canonical_spec_name AS 规范配置, canonical_spec_id AS 配置ID
FROM product_aliases ORDER BY status, alias_type, alias_display
"""

VIEW_CLEAN_SUBSET = """
CREATE VIEW IF NOT EXISTS v_clean_subset AS
SELECT p.post_id, p.title, p.source_url, p.published_at, p.view_count, p.reply_count,
       p.tags_json, p.body_text, p.clean_text AS raw_clean_text,
       a.polished_text, a.polished_multimodal, a.spam_suspect
FROM posts p
JOIN cleaning_annotations a ON a.post_id = p.post_id
WHERE a.excluded = '' AND a.is_duplicate = 0 AND a.polished_text IS NOT NULL
  AND a.polished_text != ''
"""

INSERT_ANNOTATION = """
INSERT INTO cleaning_annotations (
  post_id, cleaning_version, generated_at, excluded, norm_key, dedup_group_id,
  is_duplicate, polished_text, polished_multimodal, text_changed,
  spam_suspect, spam_reasons_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_ALIAS = """
INSERT INTO product_aliases (
  alias_norm, alias_display, alias_type, source, status, match_method,
  canonical_brand_name, canonical_series_name, canonical_series_id,
  canonical_spec_id, canonical_spec_name, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def connect(db_path: str) -> sqlite3.Connection:
    """打开 stock 库连接（需写标注表，不用 URI readonly；业务表由管线纪律与测试保证不写）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(DDL_ANNOTATIONS)
    conn.execute(DDL_ALIASES)
    conn.execute("DROP VIEW IF EXISTS v_clean_subset")
    conn.execute(VIEW_CLEAN_SUBSET)
    conn.execute("DROP VIEW IF EXISTS v_alias_resolved")
    conn.execute(VIEW_ALIAS_RESOLVED)


def write_annotations(conn: sqlite3.Connection, version: str, generated_at: str, rows: list[dict]) -> int:
    """整表替换写入（post_id 主键，同版本重跑幂等）。返回写入行数。"""
    cur = conn.cursor()
    cur.execute("DELETE FROM cleaning_annotations")
    payload = [
        (r["post_id"], version, generated_at, r["excluded"], r["norm_key"], r["dedup_group_id"],
         int(r["is_duplicate"]), r["polished_text"], r["polished_multimodal"], int(r["text_changed"]),
         int(r["spam_suspect"]), r["spam_reasons_json"])
        for r in rows
    ]
    cur.executemany(INSERT_ANNOTATION, payload)
    return cur.rowcount


def write_aliases(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    """别名写入。official/variant 永不删除（INSERT OR IGNORE，保人工拒绝记录）；
    community/competitor 仅整批替换 status=pending 行（人工 confirm/reject 永不覆盖）。"""
    cur = conn.cursor()
    cur.execute("DELETE FROM product_aliases WHERE alias_type='community' AND status='pending'")
    cur.execute("DELETE FROM product_aliases WHERE alias_type='competitor' AND status='pending'")
    seen: set[str] = set()
    inserted = ignored = 0
    for r in rows:
        if r["alias_norm"] in seen:
            continue
        seen.add(r["alias_norm"])
        try:
            cur.execute(INSERT_ALIAS, (
                r["alias_norm"], r["alias_display"], r["alias_type"], r["source"], r["status"],
                r["match_method"], r["canonical_brand_name"], r["canonical_series_name"],
                r["canonical_series_id"], r["canonical_spec_id"], r["canonical_spec_name"],
                r["created_at"]))
        except sqlite3.IntegrityError:
            ignored += 1  # 既有行（含人工已确认/拒绝）不被覆盖
            continue
        inserted += cur.rowcount
    return {"inserted": inserted, "ignored_existing": ignored}
