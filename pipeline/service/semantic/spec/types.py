"""Immutable domain objects for the semantic layer.

Nothing here reads files, opens a database or renders SQL: these types describe
meaning only, so they can be built, compared and tested without any I/O. Every
collection is frozen, so a loaded model cannot drift while queries run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

GRAINS = frozenset({"claim", "claim_product", "post", "mention", "product_node",
                    "user", "snapshot_meta"})
CARDINALITIES = frozenset({"one_to_one", "one_to_many", "many_to_one", "many_to_many"})
METRIC_TYPES = frozenset({"simple", "ratio", "derived"})
DIMENSION_TYPES = frozenset({"categorical", "time", "entity"})
POPULATION_SOURCES = frozenset({"rule", "frozen"})
AGGREGATIONS = frozenset({"count", "count_distinct", "sum"})

# 统计单位的对外说法；口径文案由它生成，避免手写措辞与实现脱节。
UNIT_LABELS: dict[str, str] = {
    "claim": "观点条数",
    "claim_product": "观点×车型条数",
    "post": "帖子数",
    "mention": "提及条数",
    "product_node": "产品节点数",
    "user": "用户数",
    "snapshot_meta": "元信息项",
}


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


def freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a read-only view so loaded definitions cannot be mutated in place."""
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class Population:
    """One rung of the sample ladder.

    ``source`` records how membership is decided: ``rule`` means the filter is
    re-evaluated at build time, ``frozen`` means membership was imported and
    cannot be recomputed locally. Hiding that difference would silently turn an
    unknown into a zero.
    """

    name: str
    dataset: str
    source: str
    filter: str | None = None
    parent: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Dataset:
    """A business object the agent may see, at one fixed grain."""

    name: str
    relation: str
    source: str
    grain: str
    primary_key: tuple[str, ...]
    entity: tuple[str, ...]
    population: str
    description: str


@dataclass(frozen=True, slots=True)
class Relationship:
    """A declared join path with its cardinality (never inferred at runtime)."""

    name: str
    from_dataset: str
    from_field: str
    to_dataset: str
    to_field: str
    cardinality: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Dimension:
    """A way to slice a metric, plus how its values are obtained."""

    name: str
    dataset: str
    column: str
    type: str
    label: str
    enum: tuple[str, ...] = ()
    enum_source: str = "query"
    alias: Mapping[str, str] = field(default_factory=_empty_mapping)
    excluded: tuple[str, ...] = ()
    null_label: str | None = None
    grain: str | None = None
    coverage: tuple[str, str] | None = None
    requires: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class Metric:
    """A business measure or ratio, with the scope it is valid in."""

    name: str
    label: str
    type: str
    dataset: str
    population: str
    grain: str
    additive: bool
    allowed_dimensions: tuple[str, ...]
    agg: str | None = None
    field: str | None = None
    filter: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    expression: str | None = None
    synonyms: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class SavedQuery:
    """A named query: the query protocol with fixed arguments.

    Saved queries exist for compatibility and for plans that reference a
    well-known analysis. They must not carry their own computation.
    """

    name: str
    summary: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    filters: Mapping[str, Any]
    population: str | None
    order: tuple[Mapping[str, Any], ...]
    limit: int | None
    params: Mapping[str, Any]
    kind: str = "query"


@dataclass(frozen=True, slots=True)
class Policy:
    """Hard limits applied to every query."""

    max_rows: int
    max_dimensions: int
    thin_sample_threshold: int
    forbid: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotSpec:
    """Where the data comes from; digests are pinned by the build."""

    paths: Mapping[str, str]
    sha256: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class QuerySpec:
    """A request in the single query protocol."""

    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=_empty_mapping)
    time: Mapping[str, Any] | None = None
    order: tuple[Mapping[str, Any], ...] = ()
    limit: int = 100
    population: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticModel:
    """The whole definition: nothing outside this object is authoritative."""

    model_version: str
    schema_version: str
    snapshot: SnapshotSpec
    datasets: Mapping[str, Dataset]
    relationships: tuple[Relationship, ...]
    populations: Mapping[str, Population]
    dimensions: Mapping[str, Dimension]
    metrics: Mapping[str, Metric]
    saved_queries: Mapping[str, SavedQuery]
    policy: Policy

    def dataset_for(self, metric_name: str) -> Dataset:
        return self.datasets[self.metrics[metric_name].dataset]

    def population_of(self, name: str) -> Population:
        return self.populations[name]


def render_caliber(metric: Metric, population: Population) -> str:
    """Build the human-readable caliber from structured fields.

    Hand-written caliber text is what lets a definition and its wording drift
    apart; this function keeps the wording a pure function of the definition.
    """
    unit = UNIT_LABELS.get(metric.grain, metric.grain)
    if metric.type == "ratio":
        body = f"{metric.numerator} ÷ {metric.denominator}（比率）"
    elif metric.type == "simple":
        field = metric.field or "*"
        body = f"{metric.agg}({field})"
    else:
        body = metric.expression or "派生指标"
    parts = [f"{body}，统计单位：{unit}"]
    scope = f"口径 {population.name}"
    if population.source == "frozen":
        scope += "（冻结成员，不可由规则重算）"
    parts.append(scope)
    if not metric.additive:
        parts.append("不可跨分组相加")
    return "；".join(parts)
