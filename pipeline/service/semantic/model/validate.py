"""Cross-reference checks for an assembled semantic model.

Shape is already verified by ``schema``; this module answers the questions that
need the whole document at once: does every reference resolve, do populations
form an acyclic ladder, is a metric consistent with the dataset it lives on, and
can a metric actually be sliced by each dimension it claims to allow.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

from ..spec import errors
from ..spec.types import GRAINS, SemanticModel
from .columns import carries_scope

ENUM_SOURCES = frozenset({"query", "static"})


def _reachable(model: SemanticModel, start: str, target: str) -> bool:
    """True when two datasets are connected by declared relationships.

    Reachability is symmetric here: the compiler decides join order from
    cardinality, so "can I get there at all" is the model-level question.
    """
    if start == target:
        return True
    neighbours: dict[str, set[str]] = {}
    for relation in model.relationships:
        neighbours.setdefault(relation.from_dataset, set()).add(relation.to_dataset)
        neighbours.setdefault(relation.to_dataset, set()).add(relation.from_dataset)
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for nxt in neighbours.get(current, ()):  # type: ignore[union-attr]
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def check_model(model: SemanticModel) -> None:
    _check_datasets(model)
    _check_relationships(model)
    _check_populations(model)
    _check_dimensions(model)
    _check_metrics(model)
    _check_saved_queries(model)


def _check_datasets(model: SemanticModel) -> None:
    for name, dataset in model.datasets.items():
        if dataset.population and dataset.population not in model.populations:
            raise errors.ModelError(
                f"默认口径 '{dataset.population}' 未定义", where=f"datasets.{name}")


def _check_relationships(model: SemanticModel) -> None:
    for relation in model.relationships:
        for side, dataset in (("from", relation.from_dataset), ("to", relation.to_dataset)):
            if dataset not in model.datasets:
                raise errors.ModelError(
                    f"关系引用了未定义的数据集 '{dataset}'", where=f"relationships.{relation.name}.{side}")


def _check_populations(model: SemanticModel) -> None:
    for name, population in model.populations.items():
        where = f"populations.{name}"
        if population.dataset not in model.datasets:
            raise errors.ModelError(
                f"引用了未定义的数据集 '{population.dataset}'", where=where)
        if population.parent is None:
            continue
        parent = model.populations.get(population.parent)
        if parent is None:
            raise errors.ModelError(f"父口径 '{population.parent}' 未定义", where=where)
        if parent.dataset != population.dataset:
            raise errors.ModelError(
                f"父口径位于数据集 '{parent.dataset}'，与当前数据集 '{population.dataset}' 不一致",
                where=where)
        # Walk to the root; a repeated node means the ladder has a cycle.
        seen = {name}
        cursor = parent
        while cursor is not None:
            if cursor.name in seen:
                raise errors.ModelError("口径阶梯存在循环引用", where=where)
            seen.add(cursor.name)
            cursor = model.populations.get(cursor.parent) if cursor.parent else None


def _check_dimensions(model: SemanticModel) -> None:
    for name, dimension in model.dimensions.items():
        where = f"dimensions.{name}"
        if dimension.dataset not in model.datasets:
            raise errors.ModelError(
                f"引用了未定义的数据集 '{dimension.dataset}'", where=where)
        if dimension.enum_source not in ENUM_SOURCES:
            raise errors.ModelError(
                f"枚举来源必须是 {sorted(ENUM_SOURCES)} 之一", where=where)
        if dimension.enum_source == "static" and not dimension.enum:
            raise errors.ModelError("静态枚举必须给出取值列表", where=where)
        for alias, target in dimension.alias.items():
            if dimension.enum and target not in dimension.enum:
                raise errors.ModelError(
                    f"别名 '{alias}' 指向的规范值 '{target}' 不在枚举中", where=where)
        for excluded in dimension.excluded:
            if dimension.enum and excluded not in dimension.enum:
                raise errors.ModelError(
                    f"排除值 '{excluded}' 不在枚举中", where=where)


def _check_metrics(model: SemanticModel) -> None:
    for name, metric in model.metrics.items():
        where = f"metrics.{name}"
        dataset = model.datasets.get(metric.dataset)
        if dataset is None:
            raise errors.ModelError(
                f"引用了未定义的数据集 '{metric.dataset}'", where=where)
        population = model.populations.get(metric.population)
        if population is None:
            raise errors.ModelError(
                f"引用了未定义的口径 '{metric.population}'", where=where)
        if not carries_scope(model, metric.dataset, population):
            raise errors.ModelError(
                f"口径 '{population.name}' 属于数据集 '{population.dataset}'，"
                f"而指标数据集 '{metric.dataset}' 不含其主键，无法套用该口径",
                where=where)

        _check_grain(model, metric, dataset.grain, where)
        if metric.type == "ratio":
            _check_ratio(model, metric, where)
        elif metric.type == "derived":
            _check_derived(model, metric, where)
        elif metric.type == "simple" and metric.agg == "count_distinct" and not metric.field:
            raise errors.ModelError("count_distinct 指标必须声明 field", where=where)

        for dimension_name in metric.allowed_dimensions:
            dimension = model.dimensions.get(dimension_name)
            if dimension is None:
                raise errors.ModelError(
                    f"允许维度 '{dimension_name}' 未定义", where=where)
            if not _reachable(model, metric.dataset, dimension.dataset):
                raise errors.ModelError(
                    f"允许维度 '{dimension_name}' 位于数据集 '{dimension.dataset}'，"
                    f"与 '{metric.dataset}' 之间没有声明的关系路径",
                    where=where)


def _check_grain(model: SemanticModel, metric, dataset_grain: str, where: str) -> None:
    if metric.grain not in GRAINS:
        raise errors.ModelError(f"未知统计单位 '{metric.grain}'", where=where)
    if metric.agg == "count_distinct":
        # Promoting to another unit is allowed, but only by counting distinct
        # members of that unit; it must be declared, never implied.
        return
    if metric.grain != dataset_grain:
        raise errors.ModelError(
            f"统计单位 '{metric.grain}' 与数据集粒度 '{dataset_grain}' 不一致；"
            f"跨单位统计须使用 count_distinct 并声明 field",
            where=where)


def _check_ratio(model: SemanticModel, metric, where: str) -> None:
    if metric.additive:
        raise errors.ModelError("比率型指标不可声明为可加", where=where)
    parts = {}
    for role in ("numerator", "denominator"):
        ref = getattr(metric, role)
        part = model.metrics.get(ref)
        if part is None:
            raise errors.ModelError(f"{role} 引用了未定义的指标 '{ref}'", where=where)
        parts[role] = part
    for role, part in parts.items():
        if part.dataset != metric.dataset:
            raise errors.ModelError(
                f"{role} '{part.name}' 位于数据集 '{part.dataset}'，与 '{metric.dataset}' 不一致",
                where=where)
        if part.population != metric.population:
            raise errors.ModelError(
                f"{role} '{part.name}' 的口径为 '{part.population}'，"
                f"与比率口径 '{metric.population}' 不一致（跨口径比率不允许）",
                where=where)
    if parts["numerator"].grain != parts["denominator"].grain:
        raise errors.ModelError(
            f"分子（{parts['numerator'].grain}）与分母（{parts['denominator'].grain}）"
            f"统计单位不同，不能相除",
            where=where)
    if metric.grain != parts["numerator"].grain:
        raise errors.ModelError("比率的统计单位必须与分子分母一致", where=where)


def _check_derived(model: SemanticModel, metric, where: str) -> None:
    referenced = {name for name in model.metrics if name in (metric.expression or "")}
    if not referenced:
        raise errors.ModelError("派生指标必须引用至少一个已定义指标", where=where)
    for ref in referenced:
        part = model.metrics[ref]
        if part.population != metric.population:
            raise errors.ModelError(
                f"派生指标引用了口径不同的指标 '{ref}'", where=where)


def _check_saved_queries(model: SemanticModel) -> None:
    for name, query in model.saved_queries.items():
        where = f"saved_queries.{name}"
        for metric_name in query.metrics:
            if metric_name not in model.metrics:
                raise errors.ModelError(f"引用了未定义的指标 '{metric_name}'", where=where)
            metric = model.metrics[metric_name]
            # 命名查询在编译期会被指标的可切分维度约束；这里先拦一次，
            # 免得"定义通过、调用即报错"。
            for dimension_name in tuple(query.dimensions):
                if dimension_name not in metric.allowed_dimensions:
                    raise errors.ModelError(
                        f"维度 '{dimension_name}' 不在指标 '{metric_name}' 的 allowed_dimensions 内",
                        where=where)
            for filter_name in tuple(query.filters):
                if filter_name not in metric.allowed_dimensions:
                    raise errors.ModelError(
                        f"过滤维度 '{filter_name}' 不在指标 '{metric_name}' 的 allowed_dimensions 内",
                        where=where)
        for dimension_name in query.dimensions:
            if dimension_name not in model.dimensions:
                raise errors.ModelError(f"引用了未定义的维度 '{dimension_name}'", where=where)
        if query.population and query.population not in model.populations:
            raise errors.ModelError(
                f"引用了未定义的口径 '{query.population}'", where=where)
        if len(query.dimensions) > model.policy.max_dimensions:
            raise errors.ModelError(
                f"维度数超过策略上限 {model.policy.max_dimensions}", where=where)
        if query.limit is not None and query.limit > model.policy.max_rows:
            raise errors.ModelError(
                f"行数上限超过策略值 {model.policy.max_rows}", where=where)
        _check_parameter_references(model, query, where)
        for order_item in query.order:
            field = order_item.get("field") or order_item.get("metric")
            if field and field not in model.metrics and field not in model.dimensions:
                raise errors.ModelError(f"排序字段 '{field}' 未定义", where=where)


def _check_parameter_references(model: SemanticModel, query, where: str) -> None:
    used: set[str] = set()
    for value in query.filters.values():
        if isinstance(value, str) and value.startswith("$"):
            used.add(value[1:])
    for item in query.order:
        value = item.get("field") or item.get("metric")
        if isinstance(value, str) and value.startswith("$"):
            used.add(value[1:])
    missing = sorted(name for name in used if name not in query.params)
    if missing:
        raise errors.ModelError(f"引用了未声明的参数：{missing}", where=where)
    for param_name, spec in query.params.items():
        if not isinstance(spec, dict) or "type" not in spec:
            raise errors.ModelError(f"参数 '{param_name}' 缺少 type", where=where)
