"""查询 → 执行计划。

计划阶段只回答四个问题：能不能答、在哪一级粒度聚合、要连哪些维度、连上去会不会
放大行数。SQL 由 `sqlgen` 渲染，这里不拼字符串，也不碰数据库。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from ..model.columns import carries_scope, dataset_columns, referenced_columns
from ..spec.types import Dimension, Metric, QuerySpec, SemanticModel
from . import errors

BASE_ALIAS = "t0"
SAFE_FORWARD = frozenset({"many_to_one", "one_to_one"})
SAFE_BACKWARD = frozenset({"one_to_many", "one_to_one"})
DEFAULT_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ColumnRef:
    alias: str
    column: str


@dataclass(frozen=True, slots=True)
class JoinStep:
    dataset: str
    alias: str
    relation: str
    left: ColumnRef
    right: ColumnRef


@dataclass(frozen=True, slots=True)
class DimensionItem:
    name: str
    ref: ColumnRef
    null_label: str | None = None


@dataclass(frozen=True, slots=True)
class FilterItem:
    name: str
    ref: ColumnRef
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class MetricItem:
    name: str
    type: str
    agg: str | None
    field: ColumnRef | None
    filter: str | None
    parts: tuple["MetricItem", ...] = ()


@dataclass(frozen=True, slots=True)
class OrderItem:
    field: str
    direction: str


@dataclass(frozen=True, slots=True)
class Plan:
    base_dataset: str
    base_relation: str
    grain: str
    population: str
    membership: ColumnRef
    dimensions: tuple[DimensionItem, ...]
    metrics: tuple[MetricItem, ...]
    joins: tuple[JoinStep, ...]
    filters: tuple[FilterItem, ...]
    exclusions: tuple[FilterItem, ...]
    time_ref: ColumnRef | None
    time_range: tuple[str, str] | None
    order: tuple[OrderItem, ...]
    limit: int


def plan(spec: QuerySpec, model: SemanticModel) -> Plan:
    """Validate the request against the model and produce a plan."""
    metrics = _metrics(spec, model)
    base = metrics[0].dataset
    if any(metric.dataset != base for metric in metrics):
        raise errors.QueryError(
            errors.MIXED_DATASETS,
            f"一次查询只能落在同一个数据集，收到 {sorted({m.dataset for m in metrics})}")
    population = _population(spec, metrics, model, base)
    _check_limits(spec, model)

    aliases: dict[str, str] = {base: BASE_ALIAS}
    joins: list[JoinStep] = []
    dimensions = tuple(
        DimensionItem(name, _ref(model, name, base, aliases, joins),
                      model.dimensions[name].null_label)
        for name in _check_dimensions(spec, metrics, model))
    filters = tuple(
        FilterItem(name, _ref(model, name, base, aliases, joins),
                   _values(model.dimensions[name], value))
        for name, value in _check_filters(spec, metrics, model))
    exclusions = _exclusions(spec, model, base, aliases, joins)
    time_ref, time_range = _time(spec, model, base, aliases)
    order = _order(spec, dimensions, metrics, model)

    base_dataset = model.datasets[base]
    scope = model.datasets[population.dataset]
    return Plan(
        base_dataset=base,
        base_relation=base_dataset.relation,
        grain=metrics[0].grain,
        population=population.name,
        membership=ColumnRef(BASE_ALIAS, scope.primary_key[0]),
        dimensions=dimensions,
        metrics=tuple(_metric_item(metric, model, base) for metric in metrics),
        joins=tuple(joins),
        filters=filters,
        exclusions=exclusions,
        time_ref=time_ref,
        time_range=time_range,
        order=order,
        limit=spec.limit if spec.limit is not None else DEFAULT_LIMIT,
    )


def _metrics(spec: QuerySpec, model: SemanticModel) -> list[Metric]:
    names = list(spec.metrics)
    if not names:
        raise errors.QueryError(errors.UNKNOWN_METRIC, "至少需要一个指标")
    missing = [name for name in names if name not in model.metrics]
    if missing:
        raise errors.QueryError(
            errors.UNKNOWN_METRIC, f"未定义的指标：{missing}",
            hint=f"可用指标：{sorted(model.metrics)}", details={"metrics": sorted(model.metrics)})
    return [model.metrics[name] for name in names]


def _population(spec: QuerySpec, metrics: list[Metric], model: SemanticModel,
                base: str):
    name = spec.population or metrics[0].population
    if name not in model.populations:
        raise errors.QueryError(
            errors.UNKNOWN_POPULATION, f"未定义的口径 '{name}'",
            hint=f"可用口径：{sorted(model.populations)}")
    population = model.populations[name]
    if not carries_scope(model, base, population):
        raise errors.QueryError(
            errors.POPULATION_MISMATCH,
            f"口径 '{name}' 属于数据集 '{population.dataset}'，"
            f"而 '{base}' 不含其主键，无法套用该口径")
    if population.source != "rule":
        # 冻结成员由导入决定，成员表里没有它，也就无法按谓词重算出来。
        raise errors.QueryError(
            errors.UNSUPPORTED, f"口径 '{name}' 是冻结成员，无法由规则重算")
    declared = {metric.population for metric in metrics}
    if declared != {name}:
        # 列出每个指标各自的登记口径：只说"口径不一致"，模型只能反复试错
        # （E2E 2026-11-03：同一草案改了 3 次才通过计划校验）。
        per_metric = "、".join(f"{metric.name}={metric.population}" for metric in metrics)
        raise errors.QueryError(
            errors.POPULATION_MISMATCH,
            f"所选指标登记口径不一致：{per_metric}；本次请求口径为 '{name}'",
            hint="同一查询内的指标必须同口径；跨口径请拆成两个查询，各自声明 population")
    return population


def _check_limits(spec: QuerySpec, model: SemanticModel) -> None:
    limit = DEFAULT_LIMIT if spec.limit is None else spec.limit
    if limit > model.policy.max_rows:
        raise errors.QueryError(
            errors.LIMIT_EXCEEDED,
            f"limit {limit} 超过策略上限 {model.policy.max_rows}")
    if limit < 1:
        raise errors.QueryError(errors.LIMIT_EXCEEDED, "limit 必须大于 0")


def _check_dimensions(spec: QuerySpec, metrics: list[Metric], model: SemanticModel) -> list[str]:
    names = list(spec.dimensions)
    if len(names) > model.policy.max_dimensions:
        raise errors.QueryError(
            errors.TOO_MANY_DIMENSIONS,
            f"维度数 {len(names)} 超过策略上限 {model.policy.max_dimensions}")
    missing = [name for name in names if name not in model.dimensions]
    if missing:
        raise errors.QueryError(
            errors.UNKNOWN_DIMENSION, f"未定义的维度：{missing}",
            hint=f"可用维度：{sorted(model.dimensions)}")
    for name in names:
        _allow(name, metrics, model)
    return names


def _check_filters(spec: QuerySpec, metrics: list[Metric],
                   model: SemanticModel) -> list[tuple[str, Any]]:
    missing = [name for name in spec.filters if name not in model.dimensions]
    if missing:
        raise errors.QueryError(
            errors.UNKNOWN_DIMENSION, f"过滤条件引用了未定义的维度：{missing}",
            hint=f"可用维度：{sorted(model.dimensions)}")
    for name in spec.filters:
        _allow(name, metrics, model)
    return list(spec.filters.items())


def _allow(name: str, metrics: list[Metric], model: SemanticModel) -> Dimension:
    dimension = model.dimensions[name]
    for metric in metrics:
        if name not in metric.allowed_dimensions:
            raise errors.QueryError(
                errors.DIMENSION_NOT_ALLOWED,
                f"维度 '{name}' 不能用于指标 '{metric.name}'",
                hint=f"'{metric.name}' 允许的维度：{list(metric.allowed_dimensions)}",
                details={"metric": metric.name, "dimension": name,
                         "allowed": list(metric.allowed_dimensions)})
    return dimension


def _ref(model: SemanticModel, name: str, base: str, aliases: dict[str, str],
         joins: list[JoinStep]) -> ColumnRef:
    dimension = model.dimensions[name]
    if dimension.dataset == base:
        return ColumnRef(aliases[base], dimension.column)
    alias = _ensure(model, dimension.dataset, base, aliases, joins)
    return ColumnRef(alias, dimension.column)


def _ensure(model: SemanticModel, target: str, base: str, aliases: dict[str, str],
            joins: list[JoinStep]) -> str:
    """把 target 数据集挂到计划上；路径上任一步会放大行数就拒绝。"""
    if target in aliases:
        return aliases[target]
    path = _path(model, base, target)
    if path is None:
        raise errors.QueryError(
            errors.UNSUPPORTED, f"数据集 '{target}' 与 '{base}' 之间没有声明的关系路径")
    for step in path:
        if step["to"] in aliases:
            continue
        if not step["safe"]:
            relation = step["relation"]
            raise errors.QueryError(
                errors.FANOUT_RISK,
                f"经 '{relation.name}' 连接 '{step['to']}' 会放大行数"
                f"（{relation.cardinality}，{'正向' if step['forward'] else '反向'}）",
                hint="须先聚合或先降到该关系的粒度；本版本只支持多对一/一对一方向",
                details={"relationship": relation.name, "dataset": step["to"]})
        alias = f"t{len(aliases)}"
        aliases[step["to"]] = alias
        joins.append(JoinStep(
            dataset=step["to"], alias=alias,
            relation=model.datasets[step["to"]].relation,
            left=ColumnRef(aliases[step["from"]], step["left_field"]),
            right=ColumnRef(alias, step["right_field"])))
    return aliases[target]


def _path(model: SemanticModel, start: str, target: str) -> list[dict] | None:
    """最短关系路径；方向与基数一起记录，因为"能不能连"和"连了会不会放大"是两件事。"""
    if start == target:
        return []
    queue: deque[tuple[str, list[dict]]] = deque([(start, [])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        for relation in model.relationships:
            for step in _steps(node, relation):
                if step["to"] in seen:
                    continue
                if step["to"] == target:
                    return path + [step]
                seen.add(step["to"])
                queue.append((step["to"], path + [step]))
    return None


def _steps(node: str, relation) -> list[dict]:
    steps = []
    if relation.from_dataset == node:
        steps.append({
            "from": node, "to": relation.to_dataset, "forward": True,
            "left_field": relation.from_field, "right_field": relation.to_field,
            "safe": relation.cardinality in SAFE_FORWARD, "relation": relation})
    if relation.to_dataset == node:
        steps.append({
            "from": node, "to": relation.from_dataset, "forward": False,
            "left_field": relation.to_field, "right_field": relation.from_field,
            "safe": relation.cardinality in SAFE_BACKWARD, "relation": relation})
    return steps


def _time(spec: QuerySpec, model: SemanticModel, base: str,
          aliases: dict[str, str]) -> tuple[ColumnRef | None, tuple[str, str] | None]:
    window = spec.time or {}
    extra = set(window) - {"start", "end"}
    if extra:
        raise errors.QueryError(errors.UNKNOWN_FIELD, f"time 不支持字段 {sorted(extra)}")
    if not window:
        return None, None
    candidates = [item for item in model.dimensions.values()
                  if item.dataset == base and item.type == "time"]
    if not candidates:
        raise errors.QueryError(
            errors.UNSUPPORTED, f"数据集 '{base}' 没有时间维度，无法按时间过滤")
    dimension = candidates[0]
    start, end = window.get("start"), window.get("end")
    if dimension.coverage and start and end:
        low, high = dimension.coverage
        if str(start) < low or str(end) > high:
            raise errors.QueryError(
                errors.OUT_OF_COVERAGE,
                f"时间区间 {start}–{end} 超出覆盖 {low}–{high}",
                details={"coverage": list(dimension.coverage)})
    if not start and not end:
        return ColumnRef(aliases[base], dimension.column), None
    return ColumnRef(aliases[base], dimension.column), (str(start or ""), str(end or ""))


def _values(dimension: Dimension, raw: Any) -> tuple[Any, ...]:
    if isinstance(raw, (list, tuple, set, frozenset)):
        values = tuple(raw)
    else:
        values = (raw,)
    if not values:
        raise errors.QueryError(
            errors.UNRESOLVED_FILTER, f"维度 '{dimension.name}' 的过滤值为空")
    # 别名表把旧接口的叫法归一到规范值，比较发生在绑定参数之前。
    return tuple(dimension.alias.get(value, value) if isinstance(value, str) else value
                 for value in values)


def _exclusions(spec: QuerySpec, model: SemanticModel, base: str,
                aliases: dict[str, str], joins: list[JoinStep]) -> tuple[FilterItem, ...]:
    """维度声明排除的取值，在它参与本次查询时生效（分组或过滤）。"""
    names: list[str] = []
    for name in list(spec.dimensions) + list(spec.filters):
        if name not in names:
            names.append(name)
    items: list[FilterItem] = []
    for name in names:
        dimension = model.dimensions[name]
        if not dimension.excluded:
            continue
        items.append(FilterItem(
            name, _ref(model, name, base, aliases, joins), tuple(dimension.excluded)))
    return tuple(items)


def _order(spec: QuerySpec, dimensions: tuple[DimensionItem, ...],
           metrics: list[Metric], model: SemanticModel) -> tuple[OrderItem, ...]:
    available = {item.name for item in dimensions} | {metric.name for metric in metrics}
    items: list[OrderItem] = []
    for raw in spec.order:
        field = raw.get("field") or raw.get("metric")
        if not field:
            raise errors.QueryError(errors.UNKNOWN_FIELD, "排序缺少 field")
        if field not in available:
            raise errors.QueryError(
                errors.UNKNOWN_FIELD,
                f"排序字段 '{field}' 未出现在本次查询的指标与维度中",
                hint=f"可用字段：{sorted(available)}")
        direction = str(raw.get("dir") or raw.get("direction") or "asc").lower()
        if direction not in {"asc", "desc"}:
            raise errors.QueryError(errors.UNKNOWN_FIELD, f"未知排序方向 '{direction}'")
        items.append(OrderItem(field, direction))
    return tuple(items)


def _metric_item(metric: Metric, model: SemanticModel, base: str) -> MetricItem:
    if metric.type == "ratio":
        parts = []
        for role in ("numerator", "denominator"):
            ref = getattr(metric, role)
            part = model.metrics.get(ref or "")
            if part is None:
                raise errors.QueryError(
                    errors.UNKNOWN_METRIC, f"比率 '{metric.name}' 的 {role} '{ref}' 未定义")
            parts.append(_metric_item(part, model, base))
        return MetricItem(metric.name, "ratio", None, None, None, tuple(parts))

    _check_filter(metric, model, base)
    field = ColumnRef(BASE_ALIAS, metric.field) if metric.field else None
    if metric.agg == "count_distinct" and field is None:
        raise errors.QueryError(
            errors.UNSUPPORTED, f"指标 '{metric.name}' 是 count_distinct 但未声明 field")
    return MetricItem(metric.name, "simple", metric.agg, field, metric.filter)


def _check_filter(metric: Metric, model: SemanticModel, base: str) -> None:
    """谓词只能引用本数据集已暴露的列，否则渲染出的 SQL 会在运行期才失败。"""
    available = set(dataset_columns(model, base))
    unknown = [column for column in referenced_columns(metric.filter)
               if column not in available]
    if unknown:
        raise errors.QueryError(
            errors.UNRESOLVED_FILTER,
            f"指标 '{metric.name}' 的谓词引用了数据集 '{base}' 上没有的列：{unknown}",
            hint=f"可用列：{sorted(available)}")
