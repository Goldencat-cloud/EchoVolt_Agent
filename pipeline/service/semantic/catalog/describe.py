"""目录：一次调用拿到"能问什么、怎么问、每个数属于哪级口径"。

目录不定义任何东西：指标名单、口径文案、枚举取值全部来自模型与库。这里只做
"把定义摊平"和"把当前库里真实存在的取值补上"，因此模型改了目录自然跟着改。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..build.lineage import read_meta
from ..build.paths import DEFAULT_DB_PATH
from ..compile import QueryError, errors
from ..model import load_model
from ..spec.types import Dimension, SemanticModel, render_caliber


def describe(*, model: SemanticModel | None = None,
             db_path: str | Path | None = None,
             with_values: bool = True) -> dict[str, Any]:
    """Return the catalogue; `with_values=False` gives the definition-only view."""
    model = model or load_model()
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    meta = read_meta(path) if path.is_file() else {}
    if meta:
        _check_artifact(meta, model, path)

    con = _connect(path) if path.is_file() and with_values else None
    try:
        return {
            "model_version": model.model_version,
            "schema_version": model.schema_version,
            "snapshot_hash": meta.get("snapshot_hash"),
            "built_at": meta.get("built_at"),
            "datasets": _datasets(model, con),
            "populations": _populations(model, meta),
            "dimensions": _dimensions(model, con),
            "metrics": _metrics(model),
            "saved_queries": _saved_queries(model),
            "policy": {
                "max_rows": model.policy.max_rows,
                "max_dimensions": model.policy.max_dimensions,
                "thin_sample_threshold": model.policy.thin_sample_threshold,
            },
        }
    finally:
        if con is not None:
            con.close()


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _check_artifact(meta: dict[str, Any], model: SemanticModel, path: Path) -> None:
    built = meta.get("model_version")
    if built and built != model.model_version:
        raise QueryError(
            errors.STALE_ARTIFACT,
            f"语义库由模型 {built} 构建，当前模型为 {model.model_version}",
            hint=f"重新执行 python -m semantic.build --force（{path}）",
            details={"built": built, "model": model.model_version})


def _datasets(model: SemanticModel, con: sqlite3.Connection | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, dataset in model.datasets.items():
        payload[name] = {
            "relation": dataset.relation,
            "grain": dataset.grain,
            "primary_key": list(dataset.primary_key),
            "population": dataset.population or None,
            "description": dataset.description,
            "rows": _scalar(con, f'SELECT COUNT(*) FROM "{dataset.relation}"'),
        }
    return payload


def _populations(model: SemanticModel, meta: dict[str, Any]) -> dict[str, Any]:
    ladder = meta.get("ladder") or {}
    payload: dict[str, Any] = {}
    for name, population in model.populations.items():
        payload[name] = {
            "dataset": population.dataset,
            "source": population.source,
            "parent": population.parent,
            "filter": population.filter,
            "size": ladder.get(name),
            "note": population.note,
        }
    return payload


def _dimensions(model: SemanticModel, con: sqlite3.Connection | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, dimension in model.dimensions.items():
        entry: dict[str, Any] = {
            "dataset": dimension.dataset,
            "column": dimension.column,
            "type": dimension.type,
            "label": dimension.label,
            "null_label": dimension.null_label,
            "description": dimension.description,
        }
        if dimension.enum:
            entry["enum"] = list(dimension.enum)
        if dimension.excluded:
            entry["excluded"] = list(dimension.excluded)
        if dimension.alias:
            entry["alias"] = dict(dimension.alias)
        if dimension.type == "time":
            entry["grain"] = dimension.grain
            entry["coverage"] = _coverage(model, dimension, con)
        elif con is not None and dimension.enum_source == "query":
            values, distinct = _enum_values(model, dimension, con)
            entry["distinct_values"] = distinct
            if distinct <= model.policy.max_rows:
                entry["enum"] = values
            else:
                # 取值空间太大时列清单没有意义（例如观点标识），只给高频值。
                entry["top_values"] = values
                entry["enum_truncated"] = True
        payload[name] = entry
    return payload


def _enum_values(model: SemanticModel, dimension: Dimension,
                 con: sqlite3.Connection) -> tuple[list[str], int]:
    """取值来自当前库而不是手抄；排除值不进枚举，空值也不进。"""
    relation = model.datasets[dimension.dataset].relation
    column = f'"{dimension.column}"'
    where = f"{column} IS NOT NULL"
    params: list[Any] = []
    if dimension.excluded:
        where += f" AND {column} NOT IN ({', '.join('?' * len(dimension.excluded))})"
        params = list(dimension.excluded)
    try:
        distinct = con.execute(
            f'SELECT COUNT(DISTINCT {column}) FROM "{relation}" WHERE {where}',
            params).fetchone()[0]
        rows = con.execute(
            f'SELECT {column}, COUNT(*) FROM "{relation}" WHERE {where} '
            f"GROUP BY 1 ORDER BY 2 DESC, 1 ASC LIMIT ?",
            [*params, model.policy.max_rows]).fetchall()
    except sqlite3.DatabaseError:
        return [], 0
    return [value for value, _count in rows], distinct


def _coverage(model: SemanticModel, dimension: Dimension,
              con: sqlite3.Connection | None) -> list[str] | None:
    if con is not None:
        relation = model.datasets[dimension.dataset].relation
        try:
            low, high = con.execute(
                f'SELECT MIN("{dimension.column}"), MAX("{dimension.column}") '
                f'FROM "{relation}"').fetchone()
        except sqlite3.DatabaseError:
            low = high = None
        if low and high:
            return [low, high]
    return list(dimension.coverage) if dimension.coverage else None


def _metrics(model: SemanticModel) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, metric in model.metrics.items():
        population = model.populations[metric.population]
        entry: dict[str, Any] = {
            "label": metric.label,
            "type": metric.type,
            "dataset": metric.dataset,
            "population": metric.population,
            "grain": metric.grain,
            "additive": metric.additive,
            "allowed_dimensions": list(metric.allowed_dimensions),
            "caliber": render_caliber(metric, population),
            "synonyms": list(metric.synonyms),
            "description": metric.description,
        }
        if metric.numerator:
            entry["numerator"] = metric.numerator
            entry["denominator"] = metric.denominator
        payload[name] = entry
    return payload


def _saved_queries(model: SemanticModel) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, query in model.saved_queries.items():
        payload[name] = {
            "summary": query.summary,
            "kind": query.kind,
            "metrics": list(query.metrics),
            "dimensions": list(query.dimensions),
            "filters": dict(query.filters),
            "population": query.population,
            "order": [dict(item) for item in query.order],
            "limit": query.limit,
            "params": {key: dict(value) for key, value in query.params.items()},
        }
    return payload


def _scalar(con: sqlite3.Connection | None, sql: str) -> int | None:
    if con is None:
        return None
    try:
        return con.execute(sql).fetchone()[0]
    except sqlite3.DatabaseError:
        return None


def dumps(catalogue: dict[str, Any]) -> str:
    return json.dumps(catalogue, ensure_ascii=False, indent=2)
