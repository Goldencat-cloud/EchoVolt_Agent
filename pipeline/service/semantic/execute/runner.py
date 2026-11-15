"""执行与结果信封。

每个结果都必须带走口径、覆盖、模型版本与快照哈希：报告门禁要能追溯每个数字，
而口径文案由模型字段生成，不允许在这里手写。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ..build.paths import DEFAULT_DB_PATH
from ..compile import QueryError, compile_query, errors
from ..model import load_model
from ..spec.types import QuerySpec, SemanticModel, render_caliber


def execute(spec: QuerySpec, *, model: SemanticModel | None = None,
            db_path: str | Path | None = None,
            include_sql: bool = False) -> dict[str, Any]:
    """Run one query and return rows plus the metadata needed to trust them.

    `include_sql` 只给内部复核用（verifier 需要重跑同一条语句），不返回给模型。
    """
    model = model or load_model()
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    sql, params, plan = compile_query(spec, model)

    con = _connect(path)
    try:
        meta = _read_meta(con)
        _check_artifact(meta, model, path)
        cursor = con.execute(sql, params)
        columns = [item[0] for item in cursor.description]
        rows = [dict(row) for row in cursor]
    finally:
        con.close()
    _apply_null_labels(plan, rows)
    envelope = _envelope(model, plan, sql, params, rows, meta)
    if include_sql:
        envelope["sql"] = sql
        envelope["columns"] = columns
    return envelope


def _apply_null_labels(plan, rows: list[dict[str, Any]]) -> None:
    """空值按维度声明的叫法显示；把它留成 None 会让"未标注"看起来像缺数据。"""
    for row in rows:
        for item in plan.dimensions:
            if item.null_label and row.get(item.name) is None:
                row[item.name] = item.null_label


def execute_saved(name: str, params: Mapping[str, Any] | None = None, *,
                  model: SemanticModel | None = None,
                  db_path: str | Path | None = None) -> dict[str, Any]:
    """展开一个命名查询再执行；命名查询本身不携带计算逻辑。"""
    model = model or load_model()
    saved = model.saved_queries.get(name)
    if saved is None:
        raise QueryError(errors.UNKNOWN_FIELD, f"未定义的命名查询 '{name}'",
                         hint=f"可用：{sorted(model.saved_queries)}")
    params = dict(params or {})
    if saved.kind == "meta":
        return _snapshot_overview(model, db_path)

    filters: dict[str, Any] = {}
    for key, value in saved.filters.items():
        if isinstance(value, str) and value.startswith("$"):
            param = value[1:]
            if param not in params:
                raise QueryError(errors.MISSING_PARAM, f"命名查询 '{name}' 缺少参数 '{param}'")
            filters[key] = params[param]
        else:
            filters[key] = value

    spec = QuerySpec(
        metrics=tuple(saved.metrics),
        dimensions=tuple(saved.dimensions),
        filters=filters,
        order=tuple(dict(item) for item in saved.order),
        limit=saved.limit or 100,
        population=saved.population,
    )
    return execute(spec, model=model, db_path=db_path)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise QueryError(errors.UNSUPPORTED,
                         f"语义库不存在：{path}", hint="先执行 python -m semantic.build")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _check_artifact(meta: Mapping[str, Any], model: SemanticModel, path: Path) -> None:
    """产物必须是用当前模型构建的；版本对不上就等于拿旧口径回答新问题。"""
    built = meta.get("model_version")
    if built and built != model.model_version:
        raise QueryError(
            errors.STALE_ARTIFACT,
            f"语义库由模型 {built} 构建，当前模型为 {model.model_version}",
            hint=f"重新执行 python -m semantic.build --force（{path}）",
            details={"built": built, "model": model.model_version})


def _read_meta(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        raw = dict(con.execute("SELECT key, value FROM meta"))
    except sqlite3.DatabaseError:
        return {}
    parsed: dict[str, Any] = {}
    for key, value in raw.items():
        try:
            parsed[key] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed[key] = value
    return parsed


def _envelope(model: SemanticModel, plan, sql: str, params: list[Any],
              rows: list[dict[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    population = model.populations[plan.population]
    metrics = []
    for item in plan.metrics:
        metric = model.metrics[item.name]
        metrics.append({
            "name": metric.name,
            "label": metric.label,
            "type": metric.type,
            "population": metric.population,
            "population_note": population.note,
            "grain": metric.grain,
            "additive": metric.additive,
            "caliber": render_caliber(metric, population),
        })
    return {
        "query_id": _query_id(sql, params, meta),
        "model_version": meta.get("model_version", model.model_version),
        "snapshot_hash": meta.get("snapshot_hash"),
        "built_at": meta.get("built_at"),
        "population": plan.population,
        "grain": plan.grain,
        "metrics": metrics,
        "rows": rows,
        "row_count": len(rows),
        "limit": plan.limit,
        "coverage": _coverage(model, plan, rows),
    }


def _coverage(model: SemanticModel, plan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """薄样本分组只做标记，不删行：删掉会让"没有数据"和"样本太少"看起来一样。"""
    threshold = model.policy.thin_sample_threshold
    thin: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        for item in plan.metrics:
            metric = model.metrics[item.name]
            if metric.type != "simple" or not metric.additive:
                continue
            value = row.get(metric.name)
            if isinstance(value, (int, float)) and 0 < value < threshold:
                thin.append({"row": index, "metric": metric.name, "value": value})
    return {"thin_sample_threshold": threshold, "thin_buckets": thin}


def _query_id(sql: str, params: list[Any], meta: Mapping[str, Any]) -> str:
    payload = "|".join([
        str(meta.get("model_version", "")),
        str(meta.get("snapshot_hash", "")),
        sql,
        json.dumps(params, ensure_ascii=False, default=str),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _snapshot_overview(model: SemanticModel, db_path: str | Path | None) -> dict[str, Any]:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    con = _connect(path)
    try:
        meta = _read_meta(con)
        _check_artifact(meta, model, path)
    finally:
        con.close()
    return {
        "kind": "meta",
        "model_version": meta.get("model_version", model.model_version),
        "snapshot_hash": meta.get("snapshot_hash"),
        "built_at": meta.get("built_at"),
        "ladder": meta.get("ladder") or {},
        "staging_counts": meta.get("staging_counts") or {},
        "core_counts": {key: value for key, value in (meta.get("core_counts") or {}).items()
                        if key != "ladder"},
        "coverage": {"thin_sample_threshold": model.policy.thin_sample_threshold},
    }
