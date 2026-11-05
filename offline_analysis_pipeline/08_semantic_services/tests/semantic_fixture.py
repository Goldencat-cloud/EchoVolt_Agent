"""共享的语义层测试夹具：手搭一个几十行的库，不依赖真实快照。

`test_semantic_execute` 与 `test_semantic_catalog` 共用它，这样"能不能查"和
"目录描述得对不对"面对的是同一份数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from semantic.build import core, ddl

POSTS = [
    ("p1", "a1", "当前拥有"),
    ("p2", "a2", "明确未拥有"),
]

# claim_id, post_id, aspect, sentiment, claim_type, experience, journey
CLAIMS = [
    ("c1", "p1", "外观与内饰", "负面", "产品体验与评价", "明确亲历", "拥有与日常使用"),
    ("c2", "p1", "外观与内饰", "正面", "产品体验与评价", "明确亲历", "拥有与日常使用"),
    ("c3", "p2", "充电与补能", "负面", "产品体验与评价", "明确未拥有", "购车前"),
    ("c4", "p2", "政策与市场", "中性", "产品体验与评价", "明确未拥有", "购车前"),
    ("c5", "p2", None, "中性", "产品体验与评价", "明确未拥有", "购车前"),
    ("c6", "p1", "空间与舒适性", "负面", "产品体验与评价", "明确亲历", "维修与售后"),
]

CURATED = {"c1", "c2", "c3"}

PRODUCTS = ("prodA", "prodB")

# 多归属：c1 同时提到 prodA 与 prodB，其余各一条。
CLAIM_PRODUCTS = [
    ("c1", "prodA"), ("c1", "prodB"), ("c2", "prodA"),
    ("c3", "prodA"), ("c6", "prodA"),
]


def build_fixture(path: Path, model) -> None:
    con = sqlite3.connect(path)
    try:
        core.create(con)
        con.executemany(
            "INSERT INTO dim_post VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(post_id, uid, None, None, "2026-01-01", "2026-01", uid, uid, ownership,
              "clean", 0, 0, 0) for post_id, uid, ownership in POSTS])
        con.executemany(
            "INSERT INTO fct_claim VALUES(" + ",".join("?" * 22) + ")",
            [(claim_id, post_id, "u" + post_id, 0, "2026-01", aspect, sentiment,
              claim_type, "陈述", experience, journey,
              dict((p, o) for p, _u, o in POSTS)[post_id],
              "正文", "引文", "[]", 1.0, None, 1, 1, 0, 0, 1)
             for claim_id, post_id, aspect, sentiment, claim_type, experience, journey
             in CLAIMS])
        members = [(claim_id, "extracted") for claim_id, *_ in CLAIMS]
        members += [(claim_id, "experience") for claim_id, *_ in CLAIMS]
        members += [(claim_id, "curated") for claim_id in sorted(CURATED)]
        con.executemany("INSERT INTO claim_population VALUES(?,?)", members)
        con.executemany(
            "INSERT INTO dim_product VALUES(?,?,?,?,?,?,?,?)",
            [(node_id, None, node_id, "series", "品牌", node_id, None, 0)
             for node_id in PRODUCTS])
        con.execute(
            "INSERT INTO fct_claim_product SELECT c.claim_id, c.post_id, m.product_id, NULL, "
            "c.month, c.aspect, c.sentiment, c.claim_type, c.experience, c.journey, "
            "c.ownership, c.has_su7_target, c.su7_is_main_target, c.competing_main, "
            "c.is_comparison, c.evidence_ok FROM fct_claim c JOIN ("
            + " UNION ALL ".join(f"SELECT '{claim_id}' AS claim_id, '{product_id}' AS product_id"
                                 for claim_id, product_id in CLAIM_PRODUCTS)
            + ") m ON m.claim_id = c.claim_id")
        ddl.create_views(con, model)
        con.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        con.executemany("INSERT INTO meta VALUES(?,?)", [
            ("model_version", model.model_version),
            ("snapshot_hash", "fixture"),
            ("built_at", "2026-11-03T00:00:00+00:00"),
            ("ladder", '{"extracted": 6, "experience": 6, "curated": 3}'),
        ])
        con.commit()
    finally:
        con.close()
