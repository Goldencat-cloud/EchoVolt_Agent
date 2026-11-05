"""Staging:源产物原样落到表里，不做业务判断。

这一层只解决"把文件读进库"。它不判断一条观点属于哪个口径、也不连接维度——
那些是 core 层的事。分层的好处是上游格式变了只改这里，业务定义变了只改模型。
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from ..spec.types import SemanticModel
from .paths import source_path

SCHEMA = """
CREATE TABLE stg_claim(
  post_uid TEXT NOT NULL, claim_seq INTEGER NOT NULL,
  aspect TEXT, sentiment TEXT, claim_type TEXT, statement TEXT,
  experience TEXT, journey TEXT, content TEXT, quote TEXT,
  evidence_json TEXT, confidence REAL, comparison_json TEXT, target_products_json TEXT,
  PRIMARY KEY(post_uid, claim_seq));

CREATE TABLE stg_post(
  post_uid TEXT PRIMARY KEY, ownership_status TEXT, post_topic TEXT, post_summary TEXT);

CREATE TABLE stg_mention(
  post_uid TEXT NOT NULL, local_product_id TEXT NOT NULL, raw_name TEXT,
  node_id TEXT, brand TEXT, series TEXT, specid TEXT,
  resolution_level TEXT, status TEXT, review_required INTEGER,
  PRIMARY KEY(post_uid, local_product_id));

CREATE TABLE stg_taxonomy(
  node_id TEXT PRIMARY KEY, parent_id TEXT, label TEXT, level TEXT,
  direct_mentions INTEGER, rollup_mentions INTEGER, rollup_posts INTEGER);
"""


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def create(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def load(con: sqlite3.Connection, model: SemanticModel) -> dict[str, int]:
    """Load all staging tables; returns the row count actually written."""
    counts: dict[str, int] = {
        "stg_claim": _load_claims(con, source_path(model, "extraction")),
        "stg_post": _load_posts(con, source_path(model, "extraction")),
        "stg_mention": _load_mentions(con, source_path(model, "mentions")),
        "stg_taxonomy": _load_taxonomy(con, source_path(model, "taxonomy")),
    }
    con.commit()
    return counts


def _load_posts(con: sqlite3.Connection, path: Path) -> int:
    """发言级上下文（拥有状态等）；观点级判断不能替代它。"""
    rows = [(post.get("post_id"),
             (post.get("user_context") or {}).get("ownership_status"),
             post.get("post_topic"), post.get("post_summary"))
            for post in _jsonl(path)]
    con.executemany("INSERT INTO stg_post VALUES(?,?,?,?)", rows)
    return len(rows)


def _load_claims(con: sqlite3.Connection, path: Path) -> int:
    rows: list[tuple] = []
    for post in _jsonl(path):
        uid = post.get("post_id")
        for seq, claim in enumerate(post.get("claims") or [], start=1):
            evidence = claim.get("evidence") or []
            quote = "\n".join(str(item.get("quote", "")) for item in evidence if item.get("quote"))
            comparison = claim.get("comparison")
            rows.append((
                uid, seq,
                claim.get("aspect"), claim.get("sentiment"), claim.get("claim_type"),
                claim.get("statement_type"), claim.get("experience_basis"),
                claim.get("journey_stage"), claim.get("content"), quote,
                json.dumps(evidence, ensure_ascii=False),
                claim.get("confidence"),
                json.dumps(comparison, ensure_ascii=False) if comparison else None,
                json.dumps(claim.get("target_products") or [], ensure_ascii=False),
            ))
    con.executemany("INSERT INTO stg_claim VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _load_mentions(con: sqlite3.Connection, path: Path) -> int:
    rows = [(m.get("post_id"), m.get("local_product_id"), m.get("raw_name"),
             m.get("node_id"), m.get("brand"), m.get("series"), m.get("specid"),
             m.get("resolution_level"), m.get("status"),
             1 if m.get("review_required") else 0)
            for m in _jsonl(path)]
    con.executemany("INSERT INTO stg_mention VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _load_taxonomy(con: sqlite3.Connection, path: Path) -> int:
    nodes = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(nodes, list):
        raise ValueError("taxonomy.json 应为节点列表")
    rows = [(node.get("id"), node.get("parent_id"), node.get("label"), node.get("level"),
             node.get("direct_mentions"), node.get("rollup_mentions"), node.get("rollup_posts"))
            for node in nodes]
    con.executemany("INSERT INTO stg_taxonomy VALUES(?,?,?,?,?,?,?)", rows)
    return len(rows)
