"""计划 → SQL。

纯函数：不读文件、不连库，输入计划输出语句与绑定参数，因此可以使用例逐字比对。
聚合发生在连接之后的分组里，但连接本身只走"多对一/一对一"方向（由 planner
保证），所以每条事实行在连接后仍然只有一行，不会放大。
"""

from __future__ import annotations

from typing import Any

from ..model.columns import qualify_predicate
from .planner import BASE_ALIAS, ColumnRef, MetricItem, Plan

MEMBERSHIP_TABLE = "semantic_population"


def render(plan: Plan) -> tuple[str, list[Any]]:
    params: list[Any] = []
    select = [f'{_column(item.ref)} AS "{item.name}"' for item in plan.dimensions]
    select += [f'{_metric(item)} AS "{item.name}"' for item in plan.metrics]

    sql = [f"SELECT {', '.join(select)}", f'FROM "{plan.base_relation}" AS {BASE_ALIAS}']
    for join in plan.joins:
        sql.append(
            f'LEFT JOIN "{join.relation}" AS {join.alias} '
            f"ON {_column(join.right)} = {_column(join.left)}")

    where = [
        f'{_column(plan.membership)} IN '
        f"(SELECT claim_id FROM {MEMBERSHIP_TABLE} WHERE population = ?)"
    ]
    params.append(plan.population)
    for item in plan.exclusions:
        # NULL 安全：`col NOT IN (...)` 会把空值一起判成 UNKNOWN 而丢掉，
        # 但模型声明的是"空值记作未标注"，不是"空值不存在"。
        placeholders = ", ".join("?" * len(item.values))
        where.append(f'({_column(item.ref)} IS NULL OR {_column(item.ref)} NOT IN ({placeholders}))')
        params.extend(item.values)
    for item in plan.filters:
        placeholders = ", ".join("?" * len(item.values))
        where.append(f'{_column(item.ref)} IN ({placeholders})')
        params.extend(item.values)
    if plan.time_ref is not None and plan.time_range is not None:
        start, end = plan.time_range
        if start:
            where.append(f'{_column(plan.time_ref)} >= ?')
            params.append(start)
        if end:
            where.append(f'{_column(plan.time_ref)} <= ?')
            params.append(end)
    sql.append("WHERE " + " AND ".join(where))

    if plan.dimensions:
        sql.append("GROUP BY " + ", ".join(_column(item.ref) for item in plan.dimensions))
    if plan.order:
        sql.append("ORDER BY " + ", ".join(
            f'"{item.field}" {item.direction.upper()}' for item in plan.order))
    sql.append("LIMIT ?")
    params.append(plan.limit)
    return "\n".join(sql), params


def _column(ref: ColumnRef) -> str:
    return f'{ref.alias}."{ref.column}"'


def _metric(item: MetricItem) -> str:
    if item.type == "ratio":
        numerator = _metric(item.parts[0])
        denominator = _metric(item.parts[1])
        # NULLIF：分母为 0 时返回 NULL，而不是让整条结论变成一个假的 0%。
        return f"(1.0 * {numerator} / NULLIF({denominator}, 0))"
    predicate = qualify_predicate(item.filter, BASE_ALIAS) if item.filter else None
    if item.agg == "count_distinct":
        field = _column(item.field) if item.field else "*"
        if predicate:
            return f"COUNT(DISTINCT CASE WHEN {predicate} THEN {field} END)"
        return f"COUNT(DISTINCT {field})"
    if predicate:
        return f"COUNT(CASE WHEN {predicate} THEN 1 END)"
    return "COUNT(*)"
