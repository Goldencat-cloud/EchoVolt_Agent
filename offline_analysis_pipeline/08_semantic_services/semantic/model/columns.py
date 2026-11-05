"""从模型推导列的用途：视图要暴露哪些列、谓词引用了哪些列。

列集合只能由模型声明推出，不能在视图里写 `SELECT *`：一旦 `*`，core 表加一列
就会自动出现在对外关系里，内部字段（`post_uid`、`evidence_json`）会变成接口。
"""

from __future__ import annotations

import re

from ..spec.types import SemanticModel

_LITERAL = re.compile(r"'(?:[^']|'')*'")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# 布尔连接词与判定词不是列名；表达式只允许列名、常量、比较与白名单运算。
_KEYWORDS = frozenset({
    "and", "or", "not", "in", "is", "null", "true", "false",
    "between", "like", "case", "when", "then", "else", "end",
})


def referenced_columns(expression: str | None) -> list[str]:
    """按出现顺序返回表达式里引用的列名；字符串字面量先被抹掉。"""
    if not expression:
        return []
    tokens = _IDENT.findall(_LITERAL.sub(" ", expression))
    seen: list[str] = []
    for token in tokens:
        if token.lower() in _KEYWORDS or token in seen:
            continue
        seen.append(token)
    return seen


def qualify_predicate(expression: str, alias: str) -> str:
    """把谓词里的列名限定到指定别名，避免多表连接后列名歧义。

    只重写标识符，字符串字面量原样保留；关键字的判定与 `referenced_columns` 共用
    同一张表，两处口径不会分叉。
    """
    pattern = re.compile(r"('(?:[^']|'')*')|([A-Za-z_][A-Za-z0-9_]*)")

    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return match.group(1)
        token = match.group(2)
        if token.lower() in _KEYWORDS:
            return token
        return f'{alias}."{token}"'

    return pattern.sub(replace, expression)


def carries_scope(model: SemanticModel, dataset_name: str, population) -> bool:
    """事实表带口径所属数据集的主键，就能套用该口径。

    口径按主子键向下传播：`claim_product` 的每一行都指回一条观点，因此
    `experience` / `curated` 这类观点口径可以直接套在它上面，而不必复制阶梯定义。
    """
    scope = model.datasets[population.dataset]
    if len(scope.primary_key) != 1:
        return False
    return scope.primary_key[0] in dataset_columns(model, dataset_name)


def dataset_columns(model: SemanticModel, dataset_name: str) -> list[str]:
    """一个数据集必须对外暴露的列：主键、维度、关系端点、指标与谓词引用的列。"""
    dataset = model.datasets[dataset_name]
    columns: list[str] = []

    def add(name: str | None) -> None:
        if name and name not in columns:
            columns.append(name)

    for key in dataset.primary_key:
        add(key)
    for dimension in model.dimensions.values():
        if dimension.dataset == dataset_name:
            for column in referenced_columns(dimension.column):
                add(column)
    for relation in model.relationships:
        if relation.from_dataset == dataset_name:
            add(relation.from_field)
        if relation.to_dataset == dataset_name:
            add(relation.to_field)
    for metric in model.metrics.values():
        if metric.dataset != dataset_name:
            continue
        add(metric.field)
        for column in referenced_columns(metric.filter):
            add(column)
    for population in model.populations.values():
        if population.dataset != dataset_name:
            continue
        for column in referenced_columns(population.filter):
            add(column)
    return columns
