"""Query compilation: request → plan → SQL. Nothing here touches a database."""

from __future__ import annotations

from typing import Any

from ..spec.types import QuerySpec, SemanticModel
from .errors import (
    DIMENSION_NOT_ALLOWED,
    FANOUT_RISK,
    LIMIT_EXCEEDED,
    MISSING_PARAM,
    MIXED_DATASETS,
    OUT_OF_COVERAGE,
    POPULATION_MISMATCH,
    TOO_MANY_DIMENSIONS,
    UNKNOWN_DIMENSION,
    UNKNOWN_FIELD,
    UNKNOWN_METRIC,
    UNKNOWN_POPULATION,
    UNRESOLVED_FILTER,
    UNSUPPORTED,
    QueryError,
)
from .planner import Plan, plan
from .sqlgen import render


def compile_query(spec: QuerySpec, model: SemanticModel) -> tuple[str, list[Any], Plan]:
    """Plan and render in one step, keeping the plan for the response envelope."""
    compiled = plan(spec, model)
    sql, params = render(compiled)
    return sql, params, compiled


__all__ = [
    "DIMENSION_NOT_ALLOWED",
    "FANOUT_RISK",
    "LIMIT_EXCEEDED",
    "MISSING_PARAM",
    "MIXED_DATASETS",
    "OUT_OF_COVERAGE",
    "POPULATION_MISMATCH",
    "Plan",
    "QueryError",
    "TOO_MANY_DIMENSIONS",
    "UNKNOWN_DIMENSION",
    "UNKNOWN_FIELD",
    "UNKNOWN_METRIC",
    "UNKNOWN_POPULATION",
    "UNRESOLVED_FILTER",
    "UNSUPPORTED",
    "compile_query",
    "plan",
    "render",
]
