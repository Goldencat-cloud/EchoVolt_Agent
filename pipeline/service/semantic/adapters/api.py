"""对外接口层：四个入口 + 一个统一信封，调用方不必了解内部模块。

错误码来自编译/执行层，这里不重新解释；任何一次调用都返回可 JSON 序列化的结果，
绝不抛异常——工具调用抛异常会直接中断 agent 图。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from ..build.ddl import MEMBERSHIP_VIEW
from ..build.paths import DEFAULT_DB_PATH
from ..catalog import describe
from ..compile import QueryError, compile_query, errors
from ..execute import execute, execute_saved
from ..model import load_model
from ..spec.types import QuerySpec

# 语义层方法名：计划里声明它，执行时走本引擎而不是镜像 SQL。
METHOD = "semantic_aggregate"
ACTIONS = ("catalogue", "query", "saved")

_QUERY_KEYS = frozenset({"metrics", "dimensions", "filters", "order", "limit",
                         "population", "time"})
_SAVED_KEYS = frozenset({"name", "params"})


def available(db_path: str | Path | None = None) -> bool:
    """语义库是否存在：不存在时上层不应注册任何新工具。"""
    return (Path(db_path) if db_path else DEFAULT_DB_PATH).is_file()


def relations(model=None) -> set[str]:
    """引擎可能生成的语义关系名，供"只准碰语义层"的静态检查使用。"""
    model = model or load_model()
    return {dataset.relation for dataset in model.datasets.values()} | {MEMBERSHIP_VIEW}


def dispatch(action: str, payload: Mapping[str, Any] | None = None, *,
             model=None, db_path=None) -> dict[str, Any]:
    payload = dict(payload or {})
    try:
        if action == "catalogue":
            _reject_unknown(payload, frozenset(), action)
            data = describe(model=model, db_path=db_path)
        elif action == "query":
            _reject_unknown(payload, _QUERY_KEYS, action)
            data = query(payload, model=model, db_path=db_path)
        elif action == "saved":
            _reject_unknown(payload, _SAVED_KEYS, action)
            data = saved(payload.get("name"), payload.get("params"),
                         model=model, db_path=db_path)
        else:
            raise QueryError(errors.UNKNOWN_FIELD, f"未知动作 '{action}'",
                             hint=f"可用动作：{list(ACTIONS)}")
    except QueryError as exc:
        return {"ok": False, "action": action, "error": exc.as_dict()}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "action": action,
                "error": {"code": "BAD_REQUEST", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 - 接口层不得把异常抛给调用方
        return {"ok": False, "action": action,
                "error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}}
    return {"ok": True, "action": action, "data": data}


def catalogue(*, with_values: bool = True, model=None, db_path=None) -> dict[str, Any]:
    return describe(model=model, db_path=db_path, with_values=bool(with_values))


def query(payload: Mapping[str, Any], *, model=None, db_path=None) -> dict[str, Any]:
    return execute(_spec(payload), model=model, db_path=db_path)


def saved(name: Any, params: Any = None, *, model=None, db_path=None) -> dict[str, Any]:
    if not isinstance(name, str) or not name:
        raise QueryError(errors.UNKNOWN_FIELD, "缺少命名查询名 name")
    if params is not None and not isinstance(params, Mapping):
        raise QueryError(errors.MISSING_PARAM, "params 必须是对象")
    return execute_saved(name, params or {}, model=model, db_path=db_path)


def validate(payload: Mapping[str, Any], *, model=None) -> dict[str, Any]:
    """只编译不执行：口径/维度/指标越界在提交计划时就暴露。

    执行期才拒绝的代价很高——计划一经批准不可变更，一个不可满足的查询会让
    整个任务失败。编译不碰数据库，所以可以在计划校验里直接调用。
    """
    try:
        compile_query(_spec(payload), model or load_model())
    except QueryError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": {"code": "BAD_REQUEST", "message": str(exc)}}
    return {"ok": True}


def query_result(payload: Mapping[str, Any], *, model=None, db_path=None) -> dict[str, Any]:
    """按分析方法（method）的形状返回，供计划/复核/门禁直接使用。"""
    model = model or load_model()
    spec = _spec(payload)
    started = time.perf_counter()
    envelope = execute(spec, model=model, db_path=db_path, include_sql=True)
    elapsed = int((time.perf_counter() - started) * 1000)
    calibers = sorted({item["caliber"] for item in envelope["metrics"]})
    return {
        "method": METHOD,
        "params": dict(payload),
        "sql": envelope["sql"],
        "columns": envelope["columns"],
        "rows": envelope["rows"],
        "row_count": envelope["row_count"],
        # 前缀是给复核与报告用的：模型口径与快照口径不同源，必须一眼可辨。
        "caliber": "模型口径：" + "；".join(calibers),
        "population": envelope["population"],
        "grain": envelope["grain"],
        "query_id": envelope["query_id"],
        "model_version": envelope["model_version"],
        "snapshot_hash": envelope["snapshot_hash"],
        "coverage": envelope["coverage"],
        "elapsed_ms": elapsed,
    }


def _spec(payload: Mapping[str, Any]) -> QuerySpec:
    metrics = payload.get("metrics")
    if not isinstance(metrics, (list, tuple)) or not metrics:
        raise QueryError(errors.UNKNOWN_METRIC, "metrics 必须是非空数组",
                         hint="先调用目录取可用指标")
    dimensions = payload.get("dimensions") or ()
    if not isinstance(dimensions, (list, tuple)):
        raise QueryError(errors.UNKNOWN_DIMENSION, "dimensions 必须是数组")
    filters = payload.get("filters") or {}
    if not isinstance(filters, Mapping):
        raise QueryError(errors.UNRESOLVED_FILTER, "filters 必须是对象")
    order = payload.get("order") or ()
    if not isinstance(order, (list, tuple)):
        raise QueryError(errors.UNKNOWN_FIELD, "order 必须是数组")
    limit = payload.get("limit")
    if limit is not None and not isinstance(limit, int):
        raise QueryError(errors.LIMIT_EXCEEDED, "limit 必须是整数")
    population = payload.get("population")
    if population is not None and not isinstance(population, str):
        raise QueryError(errors.UNKNOWN_POPULATION, "population 必须是字符串")
    window = payload.get("time")
    if window is not None and not isinstance(window, Mapping):
        raise QueryError(errors.UNKNOWN_FIELD, 'time 必须是对象，如 {"start":"2026-01"}')
    return QuerySpec(
        metrics=tuple(metrics), dimensions=tuple(dimensions), filters=dict(filters),
        order=tuple(dict(item) for item in order),
        limit=limit if limit is not None else 100,
        population=population,
        time=dict(window) if window else None,
    )


def _reject_unknown(payload: Mapping[str, Any], allowed: frozenset[str], action: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise QueryError(errors.UNKNOWN_FIELD, f"{action} 不接受参数 {unknown}",
                         hint=f"允许：{sorted(allowed)}")


def tool_specs() -> list[dict[str, Any]]:
    """给上层注册用的契约描述；文档只写在这里，不在各入口各抄一份。"""
    return [
        {"name": "semantic_catalogue",
         "description": "列出可用指标、维度、口径与命名查询（含中文名与可切分维度）。",
         "input": {"type": "object", "properties": {}}},
        {"name": "semantic_query",
         "description": "按语义模型查询指标：metrics 必填，可选 dimensions/filters/time/order/limit/population。",
         "input": {"type": "object", "required": ["metrics"], "properties": {
             "metrics": {"type": "array", "items": {"type": "string"}},
             "dimensions": {"type": "array", "items": {"type": "string"}},
             "filters": {"type": "object"}, "time": {"type": "object"},
             "order": {"type": "array"}, "limit": {"type": "integer"},
             "population": {"type": "string"}}}},
        {"name": "semantic_saved",
         "description": "按名称执行命名查询，参数由目录给出（如 aspect）。",
         "input": {"type": "object", "required": ["name"], "properties": {
             "name": {"type": "string"}, "params": {"type": "object"}}}},
    ]
