"""Predefined analysis methods executed as parameterised queries over the semantic layer.

Each method declares its parameters and caliber. Only whitelisted methods can be
executed — the agent and its tools pick from this catalogue, never invent SQL.

auto-042：`run_aggregate`（auto-032 的受限聚合原语）已随语义层迁移退役，
本目录只剩 `semantic_aggregate`；旧原语的校验与执行路径一并删除，避免留下
不可达分支和第二套取数口径。
"""
from __future__ import annotations

from typing import Any

from semantic.adapters import compat_views as db_mirror

# 语义层方法：指标与维度由 semantic/model.yaml 定义，由新引擎执行（不是镜像 SQL）。
SEMANTIC_METHOD = "semantic_aggregate"
SEMANTIC_CALIBER = ("模型口径：指标、维度与允许切分来自模型；口径文案随结果返回。"
                     "与全量快照口径（声明级/精选子集）不同源，不得混用于同一结论")

METHODS: dict[str, dict[str, Any]] = {
    SEMANTIC_METHOD: {
        "summary": ("语义层聚合：metrics/dimensions/filters 由 semantic/model.yaml 定义，"
                    "取值越界即拒绝；一次可算多个指标与比率，口径文案随结果返回"),
        "semantic": True,
        "params": {
            "metrics": {"type": "string_list", "required": True},
            "dimensions": {"type": "string_list"},
            "filters": {"type": "object"},
            "time": {"type": "object"},
            "order": {"type": "array"},
            "population": {"type": "string"},
            "limit": {"type": "int", "default": 20, "max": 200},
        },
        "caliber": SEMANTIC_CALIBER,
    },
}


def catalogue() -> list[dict[str, Any]]:
    """Planner-facing catalogue (no SQL exposed)."""
    out = []
    for name, spec in METHODS.items():
        params = {}
        for pname, pspec in spec["params"].items():
            params[pname] = {"type": pspec["type"],
                             "required": bool(pspec.get("required")),
                             "default": pspec.get("default"),
                             "max": pspec.get("max")}
        out.append({"method": name, "summary": spec["summary"], "params": params,
                    "caliber": spec["caliber"]})
    return out


def aspects() -> list[str]:
    con = db_mirror.connect()
    try:
        return [r["aspect"] for r in con.execute("SELECT aspect FROM semantic_aspect_metric ORDER BY aspect")]
    finally:
        con.close()


def validate_params(method: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check parameters against the method spec; returns (clean_params, errors)."""
    spec = METHODS.get(method)
    if spec is None:
        return {}, [f"unknown method: {method}"]
    errors: list[str] = []
    clean: dict[str, Any] = {}
    known = spec["params"]
    for key, value in (params or {}).items():
        if key not in known:
            errors.append(f"unknown parameter '{key}' for {method}")
            continue
        pspec = known[key]
        if pspec["type"] == "aspect":
            if value not in aspects():
                errors.append(f"aspect '{value}' not in the snapshot catalogue")
                continue
        if pspec["type"] == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                errors.append(f"parameter '{key}' must be an integer")
                continue
            if pspec.get("max") is not None:
                value = min(value, int(pspec["max"]))
            if value <= 0:
                errors.append(f"parameter '{key}' must be positive")
                continue
        if pspec["type"] == "string_list":
            if (not isinstance(value, (list, tuple)) or not value
                    or not all(isinstance(item, str) and item for item in value)):
                errors.append(f"parameter '{key}' must be a non-empty string array")
                continue
            value = [str(item) for item in value]
        if pspec["type"] == "object" and not isinstance(value, dict):
            errors.append(f"parameter '{key}' must be an object")
            continue
        if pspec["type"] == "array" and not isinstance(value, (list, tuple)):
            errors.append(f"parameter '{key}' must be an array")
            continue
        clean[key] = value
    for pname, pspec in known.items():
        if pspec.get("required") and pname not in clean:
            errors.append(f"missing required parameter '{pname}' for {method}")
        elif pname not in clean and "default" in pspec:
            clean[pname] = pspec["default"]
    if spec.get("semantic"):
        _validate_semantic_names(clean, errors)
    return clean, errors


def _validate_semantic_names(clean: dict[str, Any], errors: list[str]) -> None:
    """指标/维度/口径名在计划阶段就校验：越界要整单拒绝，而不是执行时才报错。"""
    try:
        from semantic.adapters import api as semantic_api
        catalogue = semantic_api.catalogue(with_values=False)
    except Exception:  # noqa: BLE001 - 语义层不可用时留给执行期报错
        return
    metrics, dimensions = catalogue["metrics"], catalogue["dimensions"]
    populations = catalogue["populations"]
    for name in clean.get("metrics") or []:
        if name not in metrics:
            errors.append(f"unknown metric '{name}'；可用：{sorted(metrics)}")
    for name in clean.get("dimensions") or []:
        if name not in dimensions:
            errors.append(f"unknown dimension '{name}'；可用：{sorted(dimensions)}")
    for name in clean.get("filters") or {}:
        if name not in dimensions:
            errors.append(f"unknown filter dimension '{name}'")
    population = clean.get("population")
    if population and population not in populations:
        errors.append(f"unknown population '{population}'；可用：{sorted(populations)}")
    # 议题值必须真实存在：自造议题名会被编译成 0 行结果，报告却可能照样写结论。
    aspect_value = (clean.get("filters") or {}).get("aspect")
    if aspect_value:
        try:
            from semantic.adapters import records
            if aspect_value not in set(records.aspects()):
                errors.append(f"unknown aspect '{aspect_value}'")
        except Exception:  # noqa: BLE001 - 语义库不可用时交给执行期报错
            pass
    if errors:
        return
    # 名字都对不代表组合成立（如 curated 口径配 experience 指标）。只编译不执行，
    # 把这类口径冲突挡在计划阶段——计划批准后不可变更，执行期才发现就整单失败。
    verdict = semantic_api.validate(clean)
    if not verdict.get("ok"):
        # message 已含错误码与 hint，再拼一次会变成 "CODE: CODE: ..."。
        error = verdict.get("error") or {}
        errors.append(str(error.get("message") or error.get("code") or "查询无法成立"))


def run_semantic(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行语义层方法；参数与结果都按分析方法形状返回（供登记与门禁使用）。"""
    from semantic.adapters import api as semantic_api

    clean, errors = validate_params(SEMANTIC_METHOD, params or {})
    if errors:
        raise ValueError("; ".join(errors))
    return semantic_api.query_result(clean)


def run(method: str, params: dict[str, Any] | None = None,
        con: Any = None) -> dict[str, Any]:
    """Execute a whitelisted method; returns rows, SQL text and timing.

    auto-042：只剩 `semantic_aggregate`；`con` 参数保留以兼容既有调用签名，
    语义层自行管理连接。
    """
    spec = METHODS.get(method)
    if spec is None:
        raise ValueError(f"unknown method: {method}")
    return run_semantic(params or {})
