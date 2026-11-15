"""语义视图：由模型生成，而不是再手写第二份定义。

一个数据集只生成一张视图，且**不带口径过滤**：同一份事实要能按 extracted /
su7_primary / curated 等不同口径查询，口径由查询期用成员表决定。把某一级口径写死
进视图，等于让其余级别无法被查询。

视图只暴露 `model.columns.dataset_columns` 推出的列，避免把 `post_uid`、
`evidence_json` 这类内部字段变成对外接口。
"""

from __future__ import annotations

import sqlite3

from ..model.columns import dataset_columns
from ..spec import errors
from ..spec.types import SemanticModel

MARKER = "-- generated from semantic/model.yaml by build/ddl.py"
MEMBERSHIP_SOURCE = "claim_population"
MEMBERSHIP_VIEW = "semantic_population"


def create_views(con: sqlite3.Connection, model: SemanticModel) -> dict[str, int]:
    """Drop and recreate every dataset view; return relation → column count."""
    created: dict[str, int] = {}
    for name, dataset in model.datasets.items():
        columns = dataset_columns(model, name)
        if not columns:
            raise errors.ModelError(
                "数据集没有任何对外列，无法生成视图", where=f"datasets.{name}")
        con.execute(f'DROP VIEW IF EXISTS "{dataset.relation}"')
        body = ", ".join(f'"{column}"' for column in columns)
        con.execute(
            f'CREATE VIEW "{dataset.relation}" AS SELECT {body} FROM "{dataset.source}"')
        created[dataset.relation] = len(columns)

    # 口径成员也以视图形式对外，让生成的查询只引用 semantic_* 关系，
    # 便于"只准碰语义层"的静态检查（verifier.assert_semantic_only）成立。
    con.execute(f'DROP VIEW IF EXISTS "{MEMBERSHIP_VIEW}"')
    con.execute(f'CREATE VIEW "{MEMBERSHIP_VIEW}" AS '
                f'SELECT claim_id, population FROM "{MEMBERSHIP_SOURCE}"')
    created[MEMBERSHIP_VIEW] = 2
    return created
