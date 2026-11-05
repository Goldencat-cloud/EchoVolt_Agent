"""Structural checks for the raw model mapping.

This module answers "is this document shaped like a model?". Cross-reference
questions ("does this metric point at a dataset that exists?") belong to
``semantic.model.validate``. Keeping them apart means a malformed YAML reports a
shape problem instead of a confusing lookup error.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..spec import errors
from ..spec.types import (
    AGGREGATIONS,
    CARDINALITIES,
    DIMENSION_TYPES,
    GRAINS,
    METRIC_TYPES,
    POPULATION_SOURCES,
)

TOP_LEVEL_KEYS = {
    "model_version",
    "schema",
    "snapshot",
    "datasets",
    "relationships",
    "populations",
    "dimensions",
    "metrics",
    "saved_queries",
    "policies",
}
TOP_LEVEL_REQUIRED = ("model_version", "schema", "datasets", "populations", "dimensions",
                      "metrics", "saved_queries", "policies")

TIME_GRAINS = frozenset({"day", "week", "month", "quarter", "year"})
SAVED_QUERY_KINDS = frozenset({"query", "meta"})
# 桥接粒度：一行由两个实体共同确定，因此允许复合主键。
BRIDGE_GRAINS = frozenset({"mention", "claim_product"})

# Only identifiers, literals, comparisons and a fixed operator set may appear in
# a model expression. The model is never allowed to carry SQL statements: the
# compiler assembles them, so nothing a model author writes reaches an
# identifier position in a statement.
_FORBIDDEN_SQL = re.compile(
    r"(;|--|/\*|\*/|\b(select|insert|update|delete|drop|alter|attach|detach|pragma"
    r"|union|create|replace|vacuum|trigger)\b)",
    re.IGNORECASE,
)
_QUOTED_LITERAL = re.compile(r"'(?:[^']|'')*'")
# 单引号保留在允许集合里：字面量被替换为 '' 占位后仍需通过字符检查。
_ALLOWED_BODY = re.compile(r"^[A-Za-z0-9_\s.,()'<>=!+\-*/%|]+$")
MAX_EXPRESSION_LENGTH = 300


def _require(mapping: Mapping[str, Any], keys: tuple[str, ...], where: str) -> None:
    for key in keys:
        if key not in mapping or mapping[key] in (None, "", [], {}):
            raise errors.ModelError(f"缺少必填字段 '{key}'", where=where)


def _as_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise errors.ModelError("应为映射（键值对）", where=where)
    return value


def _as_str_list(value: Any, where: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise errors.ModelError("应为字符串或字符串列表", where=where)
    return list(value)


def check_expression(expression: str, where: str) -> None:
    """Reject anything that is not a safe, single-clause predicate or column ref."""
    if not isinstance(expression, str):
        raise errors.ModelError("表达式必须是字符串", where=where)
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise errors.ModelError(
            f"表达式超过 {MAX_EXPRESSION_LENGTH} 字符，应拆分为模型字段", where=where)
    body = _QUOTED_LITERAL.sub("''", expression)
    # 先判语句特征再判字符集：这样才能报出真正的问题（写入了 SQL），
    # 而不是笼统的"含非法字符"。
    found = _FORBIDDEN_SQL.search(body)
    if found:
        raise errors.ModelError(
            f"表达式不得包含 SQL 关键字或语句分隔符（发现 '{found.group(0)}'）", where=where)
    if not _ALLOWED_BODY.match(body):
        raise errors.ModelError("表达式只允许列名、常量、比较与白名单运算", where=where)


def check_structure(raw: Any) -> None:
    """Validate the shape of a loaded model document. Raises on the first problem."""
    raw = _as_mapping(raw, "model")
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise errors.ModelError(f"未知的顶层字段：{sorted(unknown)}", where="model")
    _require(raw, TOP_LEVEL_REQUIRED, "model")

    _check_datasets(raw["datasets"])
    _check_relationships(raw.get("relationships") or [])
    _check_populations(raw["populations"])
    _check_dimensions(raw["dimensions"])
    _check_metrics(raw["metrics"])
    _check_saved_queries(raw["saved_queries"])
    _check_policy(raw["policies"])
    _check_snapshot(raw.get("snapshot") or {})


def _check_datasets(datasets: Any) -> None:
    datasets = _as_mapping(datasets, "datasets")
    for name, entry in datasets.items():
        where = f"datasets.{name}"
        entry = _as_mapping(entry, where)
        _require(entry, ("relation", "source", "grain", "primary_key", "description"), where)

        grain = entry.get("grain")
        if isinstance(grain, (list, tuple)):
            raise errors.ModelError(
                "数据集只能声明单一粒度；含多种粒度时须拆成多个数据集", where=where)
        if grain not in GRAINS:
            raise errors.ModelError(f"未知粒度 '{grain}'；允许：{sorted(GRAINS)}", where=where)

        primary_key = _as_str_list(entry.get("primary_key"), f"{where}.primary_key")
        if not primary_key:
            raise errors.ModelError("主键不能为空", where=where)
        if len(primary_key) > 1 and grain not in BRIDGE_GRAINS:
            raise errors.ModelError(
                f"只有桥接粒度（{sorted(BRIDGE_GRAINS)}）允许复合主键；其余数据集须为单一粒度",
                where=where)

        for field_name in ("relation", "source", "description"):
            if not isinstance(entry.get(field_name), str):
                raise errors.ModelError(f"字段 '{field_name}' 必须是字符串", where=where)


def _check_relationships(relationships: Any) -> None:
    if not isinstance(relationships, (list, tuple)):
        raise errors.ModelError("relationships 必须是列表", where="relationships")
    for index, entry in enumerate(relationships):
        where = f"relationships[{index}]"
        entry = _as_mapping(entry, where)
        _require(entry, ("name", "from", "to", "cardinality"), where)
        cardinality = entry.get("cardinality")
        if cardinality not in CARDINALITIES:
            raise errors.ModelError(
                f"未知基数 '{cardinality}'；允许：{sorted(CARDINALITIES)}", where=where)
        for side in ("from", "to"):
            _require(_as_mapping(entry[side], f"{where}.{side}"), ("dataset", "field"),
                     f"{where}.{side}")


def _check_populations(populations: Any) -> None:
    populations = _as_mapping(populations, "populations")
    if not populations:
        raise errors.ModelError("至少需要一个口径级", where="populations")
    for name, entry in populations.items():
        where = f"populations.{name}"
        entry = _as_mapping(entry, where)
        _require(entry, ("dataset", "source"), where)
        if entry.get("source") not in POPULATION_SOURCES:
            raise errors.ModelError(
                f"口径来源必须是 {sorted(POPULATION_SOURCES)} 之一", where=where)
        predicate = entry.get("filter")
        if predicate is not None:
            check_expression(predicate, f"{where}.filter")


def _check_dimensions(dimensions: Any) -> None:
    dimensions = _as_mapping(dimensions, "dimensions")
    for name, entry in dimensions.items():
        where = f"dimensions.{name}"
        entry = _as_mapping(entry, where)
        _require(entry, ("dataset", "column", "type", "label"), where)
        dim_type = entry.get("type")
        if dim_type not in DIMENSION_TYPES:
            raise errors.ModelError(
                f"未知维度类型 '{dim_type}'；允许：{sorted(DIMENSION_TYPES)}", where=where)
        check_expression(str(entry.get("column")), f"{where}.column")
        if dim_type == "time":
            grain = entry.get("grain")
            if grain not in TIME_GRAINS:
                raise errors.ModelError(
                    f"时间维度必须声明粒度（{sorted(TIME_GRAINS)}）", where=where)
            coverage = entry.get("coverage")
            if coverage is not None:
                if (not isinstance(coverage, (list, tuple)) or len(coverage) != 2
                        or not all(isinstance(item, str) for item in coverage)):
                    raise errors.ModelError("coverage 必须形如 [起始, 结束]", where=where)
        alias = entry.get("alias")
        if alias is not None:
            alias = _as_mapping(alias, f"{where}.alias")
            for source, target in alias.items():
                if not isinstance(source, str) or not isinstance(target, str):
                    raise errors.ModelError("别名映射必须是字符串到字符串", where=where)
        enum = entry.get("enum")
        if enum is not None:
            _as_str_list(enum, f"{where}.enum")


def _check_metrics(metrics: Any) -> None:
    metrics = _as_mapping(metrics, "metrics")
    if not metrics:
        raise errors.ModelError("至少需要一个指标", where="metrics")
    for name, entry in metrics.items():
        where = f"metrics.{name}"
        entry = _as_mapping(entry, where)
        _require(entry,
                 ("label", "type", "dataset", "population", "grain", "additive",
                  "allowed_dimensions"),
                 where)
        metric_type = entry.get("type")
        if metric_type not in METRIC_TYPES:
            raise errors.ModelError(
                f"未知指标类型 '{metric_type}'；允许：{sorted(METRIC_TYPES)}", where=where)
        if not isinstance(entry.get("additive"), bool):
            raise errors.ModelError("additive 必须是布尔值", where=where)
        if entry.get("grain") not in GRAINS:
            raise errors.ModelError(f"未知统计单位 '{entry.get('grain')}'", where=where)
        dims = entry.get("allowed_dimensions")
        if not isinstance(dims, (list, tuple)):
            raise errors.ModelError("allowed_dimensions 必须是列表", where=where)
        if metric_type == "simple" and entry.get("agg") not in AGGREGATIONS:
            raise errors.ModelError(
                f"简单指标必须声明 agg（{sorted(AGGREGATIONS)}）", where=where)
        if metric_type == "ratio":
            _require(entry, ("numerator", "denominator"), where)
        if metric_type == "derived":
            _require(entry, ("expression",), where)
            check_expression(str(entry["expression"]), f"{where}.expression")
        if entry.get("filter") is not None:
            check_expression(str(entry["filter"]), f"{where}.filter")


def _check_saved_queries(queries: Any) -> None:
    queries = _as_mapping(queries, "saved_queries")
    for name, entry in queries.items():
        where = f"saved_queries.{name}"
        entry = _as_mapping(entry, where)
        _require(entry, ("summary",), where)
        kind = entry.get("kind", "query")
        if kind not in SAVED_QUERY_KINDS:
            raise errors.ModelError(f"未知命名查询类型 '{kind}'", where=where)
        if kind == "query" and not entry.get("metrics"):
            raise errors.ModelError("命名查询必须声明 metrics（meta 类型除外）", where=where)
        for field_name in ("metrics", "dimensions"):
            value = entry.get(field_name)
            if value is not None:
                _as_str_list(value, f"{where}.{field_name}")


def _check_policy(policy: Any) -> None:
    policy = _as_mapping(policy, "policies")
    _require(policy, ("max_rows", "max_dimensions", "thin_sample_threshold"), "policies")
    for key in ("max_rows", "max_dimensions", "thin_sample_threshold"):
        value = policy.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise errors.ModelError(f"'{key}' 必须是整数", where="policies")
        if key != "thin_sample_threshold" and value <= 0:
            raise errors.ModelError(f"'{key}' 必须大于 0", where="policies")
    forbid = policy.get("forbid")
    if forbid is not None:
        _as_str_list(forbid, "policies.forbid")


def _check_snapshot(snapshot: Any) -> None:
    snapshot = _as_mapping(snapshot, "snapshot")
    paths = snapshot.get("paths")
    if paths is None:
        return
    paths = _as_mapping(paths, "snapshot.paths")
    for key, value in paths.items():
        if not isinstance(value, str) or not value:
            raise errors.ModelError(f"路径 '{key}' 必须是非空字符串", where="snapshot.paths")
