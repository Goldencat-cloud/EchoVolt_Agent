"""Turn a YAML model document into immutable domain objects.

Loading is the only place that knows about YAML; everything downstream works on
the objects from ``semantic.spec``. A document that fails either check never
reaches the compiler, so a bad definition cannot become a bad number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .. import MODEL_SCHEMA_VERSION
from ..spec import errors
from ..spec.types import (
    Dataset,
    Dimension,
    Metric,
    Policy,
    Population,
    Relationship,
    SavedQuery,
    SemanticModel,
    SnapshotSpec,
    freeze_mapping,
)
from .schema import check_structure
from .validate import check_model

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "model.yaml"


def load_model(path: str | Path | None = None) -> SemanticModel:
    """Load, check and validate the model at ``path``."""
    target = Path(path) if path is not None else DEFAULT_MODEL_PATH
    if not target.is_file():
        raise errors.ModelError(f"模型文件不存在：{target}")
    text = target.read_text(encoding="utf-8")
    return load_model_text(text)


def load_model_text(text: str) -> SemanticModel:
    """Load a model from YAML text (used by tests and the build step)."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - YAML 语法错误由解析器给出
        raise errors.ModelError(f"模型不是合法 YAML：{exc}") from exc
    return build_model(raw)


def build_model(raw: Any) -> SemanticModel:
    """Assemble and validate a model from an already-parsed document."""
    check_structure(raw)
    model = _assemble(raw)
    check_model(model)
    return model


def _assemble(raw: Mapping[str, Any]) -> SemanticModel:
    schema_version = str(raw.get("schema") or MODEL_SCHEMA_VERSION)
    if schema_version != MODEL_SCHEMA_VERSION:
        raise errors.ModelError(
            f"模型 schema 为 '{schema_version}'，当前支持的版本是 '{MODEL_SCHEMA_VERSION}'",
            where="schema")

    return SemanticModel(
        model_version=str(raw["model_version"]),
        schema_version=schema_version,
        snapshot=_snapshot(raw.get("snapshot") or {}),
        datasets=freeze_mapping(
            {name: _dataset(name, entry) for name, entry in raw["datasets"].items()}),
        relationships=tuple(
            _relationship(index, entry)
            for index, entry in enumerate(raw.get("relationships") or [])),
        populations=freeze_mapping(
            {name: _population(name, entry) for name, entry in raw["populations"].items()}),
        dimensions=freeze_mapping(
            {name: _dimension(name, entry) for name, entry in raw["dimensions"].items()}),
        metrics=freeze_mapping(
            {name: _metric(name, entry) for name, entry in raw["metrics"].items()}),
        saved_queries=freeze_mapping(
            {name: _saved_query(name, entry) for name, entry in raw["saved_queries"].items()}),
        policy=_policy(raw["policies"]),
    )


def _as_tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _dataset(name: str, entry: Mapping[str, Any]) -> Dataset:
    return Dataset(
        name=name,
        relation=str(entry["relation"]),
        source=str(entry["source"]),
        grain=str(entry["grain"]),
        primary_key=_as_tuple(entry["primary_key"]),
        entity=_as_tuple(entry.get("entity")),
        population=str(entry.get("population") or ""),
        description=str(entry["description"]),
    )


def _relationship(index: int, entry: Mapping[str, Any]) -> Relationship:
    return Relationship(
        name=str(entry.get("name") or f"rel_{index}"),
        from_dataset=str(entry["from"]["dataset"]),
        from_field=str(entry["from"]["field"]),
        to_dataset=str(entry["to"]["dataset"]),
        to_field=str(entry["to"]["field"]),
        cardinality=str(entry["cardinality"]),
        note=entry.get("note"),
    )


def _population(name: str, entry: Mapping[str, Any]) -> Population:
    return Population(
        name=name,
        dataset=str(entry["dataset"]),
        source=str(entry["source"]),
        filter=entry.get("filter"),
        parent=entry.get("parent"),
        note=entry.get("note"),
    )


def _dimension(name: str, entry: Mapping[str, Any]) -> Dimension:
    coverage = entry.get("coverage")
    return Dimension(
        name=name,
        dataset=str(entry["dataset"]),
        column=str(entry["column"]),
        type=str(entry["type"]),
        label=str(entry["label"]),
        enum=_as_tuple(entry.get("enum")),
        enum_source=str(entry.get("enum_source") or "query"),
        alias=freeze_mapping(entry.get("alias")),
        excluded=_as_tuple(entry.get("excluded")),
        null_label=entry.get("null_label"),
        grain=entry.get("grain"),
        coverage=(str(coverage[0]), str(coverage[1])) if coverage else None,
        requires=_as_tuple(entry.get("requires")),
        description=str(entry.get("description") or ""),
    )


def _metric(name: str, entry: Mapping[str, Any]) -> Metric:
    return Metric(
        name=name,
        label=str(entry["label"]),
        type=str(entry["type"]),
        dataset=str(entry["dataset"]),
        population=str(entry["population"]),
        grain=str(entry["grain"]),
        additive=bool(entry["additive"]),
        allowed_dimensions=_as_tuple(entry["allowed_dimensions"]),
        agg=entry.get("agg"),
        field=entry.get("field"),
        filter=entry.get("filter"),
        numerator=entry.get("numerator"),
        denominator=entry.get("denominator"),
        expression=entry.get("expression"),
        synonyms=_as_tuple(entry.get("synonyms")),
        description=str(entry.get("description") or ""),
    )


def _saved_query(name: str, entry: Mapping[str, Any]) -> SavedQuery:
    order = tuple(freeze_mapping(item) for item in (entry.get("order") or []))
    return SavedQuery(
        name=name,
        summary=str(entry["summary"]),
        metrics=_as_tuple(entry.get("metrics")),
        dimensions=_as_tuple(entry.get("dimensions")),
        filters=freeze_mapping(entry.get("filters")),
        population=entry.get("population"),
        order=order,
        limit=entry.get("limit"),
        params=freeze_mapping(entry.get("params")),
        kind=str(entry.get("kind") or "query"),
    )


def _policy(entry: Mapping[str, Any]) -> Policy:
    return Policy(
        max_rows=int(entry["max_rows"]),
        max_dimensions=int(entry["max_dimensions"]),
        thin_sample_threshold=int(entry["thin_sample_threshold"]),
        forbid=_as_tuple(entry.get("forbid")),
    )


def _snapshot(entry: Mapping[str, Any]) -> SnapshotSpec:
    return SnapshotSpec(
        paths=freeze_mapping(entry.get("paths")),
        sha256=freeze_mapping(entry.get("sha256")),
    )


def summarise(model: SemanticModel) -> dict[str, Any]:
    """A compact, JSON-friendly view used by the CLI and by tests."""
    return {
        "model_version": model.model_version,
        "schema_version": model.schema_version,
        "datasets": {name: {"grain": item.grain, "relation": item.relation}
                     for name, item in model.datasets.items()},
        "relationships": [f"{item.from_dataset}->{item.to_dataset} ({item.cardinality})"
                          for item in model.relationships],
        "populations": {name: {"dataset": item.dataset, "source": item.source,
                               "parent": item.parent}
                        for name, item in model.populations.items()},
        "dimensions": {name: item.type for name, item in model.dimensions.items()},
        "metrics": {name: {"type": item.type, "population": item.population,
                           "grain": item.grain, "additive": item.additive}
                    for name, item in model.metrics.items()},
        "saved_queries": sorted(model.saved_queries),
        "policy": {"max_rows": model.policy.max_rows,
                   "max_dimensions": model.policy.max_dimensions,
                   "thin_sample_threshold": model.policy.thin_sample_threshold},
    }
