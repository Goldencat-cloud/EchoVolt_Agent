"""语义库上的兼容视图：把 core 表的列名映射成既有查询的列名。

历史查询（任务简报、沙箱数据框）是按旧镜像视图的列名写的。数据源统一到
`semantic.db` 之后，这些查询不必逐个重写——本模块在只读连接上建同名的
TEMP VIEW，只做**列名映射与口径筛人**，不重写任何聚合口径：

- 口径筛选一律引用 `claim_population`（构建期写入的成员表），不在这里重算；
- 聚合口径（`semantic_aspect_metric`）与语义模型的 `experience` 口径同源，
  指标定义仍在 `model.yaml`，这里只是把它按旧列名摊平。

视图是会话级的（TEMP），不会写进语义库，也不会成为第二份持久定义。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..build.paths import DEFAULT_DB_PATH

#: 兼容视图名 → 供"只准碰语义层"检查用的关系白名单。
SEMANTIC_RELATIONS = {
    "semantic_aspect_metric", "semantic_claim_fact",
    "semantic_claim_evidence", "semantic_post_scope", "semantic_snapshot_meta",
}

_VIEWS = {
    "semantic_aspect_metric": """
        SELECT c."aspect" AS aspect,
               COUNT(*) AS claims,
               COUNT(DISTINCT c."post_id") AS posts,
               SUM(CASE WHEN c."sentiment" = '正面' THEN 1 ELSE 0 END) AS positive,
               SUM(CASE WHEN c."sentiment" = '负面' THEN 1 ELSE 0 END) AS negative,
               SUM(CASE WHEN c."sentiment" = '中性' THEN 1 ELSE 0 END) AS neutral,
               SUM(CASE WHEN c."sentiment" NOT IN ('正面', '负面', '中性')
                        THEN 1 ELSE 0 END) AS other,
               COUNT(DISTINCT CASE WHEN c."sentiment" = '负面' THEN c."post_id" END)
                   AS negative_posts,
               1.0 * SUM(CASE WHEN c."sentiment" = '负面' THEN 1 ELSE 0 END) / COUNT(*)
                   AS negative_share,
               '声明级：negative/claims；帖子级：negative_posts/posts' AS caliber_note
        FROM fct_claim c
        JOIN claim_population m ON m.claim_id = c.claim_id
        WHERE m.population = 'experience'
        GROUP BY c."aspect"
    """,
    "semantic_claim_fact": """
        SELECT c."claim_id" AS claim_id, c."post_id" AS post_id, c."aspect" AS aspect,
               c."sentiment" AS sentiment, c."content" AS content,
               c."claim_type" AS claim_type, c."ownership" AS ownership,
               c."experience" AS experience, c."journey" AS journey,
               c."statement" AS statement, p."published_at" AS date,
               p."title" AS title, p."url" AS url, c."evidence_ok" AS evidence_ok,
               'curated' AS source_set
        FROM fct_claim c
        LEFT JOIN dim_post p ON p.post_id = c.post_id
        JOIN claim_population m ON m.claim_id = c.claim_id
        WHERE m.population = 'curated'
    """,
    "semantic_claim_evidence": """
        SELECT c."claim_id" AS claim_id, c."aspect" AS aspect, c."sentiment" AS sentiment,
               c."content" AS content, c."ownership" AS ownership,
               c."experience" AS experience, c."journey" AS journey,
               c."quote" AS quote, p."title" AS title, p."url" AS url,
               p."published_at" AS date
        FROM fct_claim c
        LEFT JOIN dim_post p ON p.post_id = c.post_id
        JOIN claim_population m ON m.claim_id = c.claim_id
        WHERE m.population = 'curated'
          AND c."quote" IS NOT NULL AND c."quote" <> ''
    """,
    "semantic_post_scope": """
        SELECT m."post_id" AS post_id, m."product_id" AS product_id,
               m."raw_name" AS raw_name, m."status" AS scope_status,
               m."resolution_level" AS scope_level,
               p."brand" AS brand, p."series" AS series,
               p."is_analysis_object" AS is_analysis_object
        FROM fct_mention m
        LEFT JOIN dim_product p ON p.node_id = m."product_id"
    """,
    "semantic_snapshot_meta": """
        SELECT 'data_version' AS key,
               (SELECT value FROM meta WHERE key = 'model_version') AS value
        UNION ALL
        SELECT key AS key, value AS value FROM meta WHERE key <> 'model_version'
    """,
}


def db_path() -> Path:
    return Path(DEFAULT_DB_PATH)


DB_PATH = db_path()


def connect(read_only: bool = True) -> sqlite3.Connection:
    """打开语义库并挂上兼容视图；`read_only` 仅为签名兼容而保留。"""
    path = db_path()
    if not path.is_file():
        raise FileNotFoundError(f"语义库不存在：{path}；先执行 python -m semantic.build")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    for name, body in _VIEWS.items():
        con.execute(f'CREATE TEMP VIEW IF NOT EXISTS "{name}" AS {body}')
    return con
