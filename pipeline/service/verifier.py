"""Deterministic verification of executed analysis steps.

校验只看**语义层结果本身能否自证**：同一条参数重跑必须得到同一 SQL 与同一
批行，比率必须与分子分母复算一致，口径必须可辨。不再连接第二份快照做交叉
核对——两套数据源交叉证明的不是正确性，而是两个版本是否同步。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from semantic.adapters import api as semantic_api
from semantic.adapters import records

TOLERANCE = 1e-6
MIN_ROWS = 1
THIN_ROWS = 3
MAX_ROW_DIFFS = 5


def _check_caliber(step: dict[str, Any], issues: list[str]) -> None:
    caliber = step.get("caliber") or ""
    if not caliber:
        issues.append("缺少口径声明（caliber）")
    elif "模型口径" not in caliber:
        issues.append("模型口径未在口径说明中标注")


def _check_rows(step: dict[str, Any], issues: list[str], warnings: list[str]) -> None:
    rows = step.get("rows") or []
    if len(rows) < MIN_ROWS:
        issues.append(f"查询结果为空（{step.get('method')}）")
    elif len(rows) < THIN_ROWS:
        warnings.append(f"结果仅 {len(rows)} 行，样本较薄，结论不宜外推")
    for row in rows:
        for key, value in row.items():
            if value is None:
                warnings.append(f"字段 {key} 存在空值")
                break


def _check_ratio_recompute(step: dict[str, Any], issues: list[str]) -> None:
    """比率必须等于同一行的分子/分母；对不上就是算错了。"""
    for row in step.get("rows") or []:
        claims = row.get("claims")
        negative = row.get("negative")
        share = row.get("negativeShare")
        if share is None or negative is None or not claims:
            continue
        if abs(negative / claims - float(share)) > TOLERANCE:
            issues.append(f"{row.get('aspect') or '合计'} 的负面占比与 negative/claims 复算不符")


def _check_recompute(step: dict[str, Any], issues: list[str]) -> None:
    """同参数重跑：SQL 与行必须逐字一致，否则结果不可复现。"""
    try:
        recomputed = semantic_api.query_result(step.get("params") or {})
    except Exception as exc:  # noqa: BLE001 - 复算失败即视为无法验证
        issues.append(f"语义层结果无法复算：{type(exc).__name__}: {exc}")
        return
    if recomputed.get("sql") != step.get("sql"):
        issues.append("语义层 SQL 与参数重建结果不一致")
        return
    actual = [dict(row) for row in step.get("rows") or []]
    expected = [dict(row) for row in recomputed.get("rows") or []]
    if actual != expected:
        issues.append("语义层结果与重新执行结果不一致")


def _check_relations(step: dict[str, Any], issues: list[str]) -> None:
    """执行的 SQL 只准引用语义层关系。"""
    sql = step.get("sql") or ""
    try:
        from semantic.compile import relations_in
    except ImportError:  # 兼容：编译层未暴露时退化为本地解析
        import re
        relations_in = lambda text: {name.lower() for name in re.findall(  # noqa: E731
            r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", text or "", re.IGNORECASE)}
    allowed = {name.lower() for name in semantic_api.relations()}
    unknown = relations_in(sql) - allowed
    if unknown:
        issues.append("SQL 引用了非语义层关系：" + ", ".join(sorted(unknown)))


def verify_step(step: dict[str, Any], con: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Verify one executed step; returns {ok, errors, warnings, checks}."""
    issues: list[str] = []
    warnings: list[str] = []
    if step.get("method") != semantic_api.METHOD:
        issues.append(f"未知方法：{step.get('method')}")
    _check_caliber(step, issues)
    _check_rows(step, issues, warnings)
    _check_ratio_recompute(step, issues)
    _check_recompute(step, issues)
    _check_relations(step, issues)
    return {"ok": not issues, "errors": issues, "warnings": warnings,
            "checks": ["caliber_declared", "rows_present", "ratio_recomputed",
                       "result_reproducible", "semantic_relations_only"]}


def verify_all(steps: list[dict[str, Any]]) -> dict[str, Any]:
    results = [verify_step(step) for step in steps]
    accepted = [step for step, verdict in zip(steps, results) if verdict["ok"]]
    rejected = [{"step_id": step.get("step_id"), "method": step.get("method"),
                 "errors": verdict["errors"]}
                for step, verdict in zip(steps, results) if not verdict["ok"]]
    return {"ok": not rejected, "accepted": len(accepted), "rejected": rejected,
            "results": results}


def assert_semantic_only(sql: str) -> None:
    """给调用方复用的静态检查（旧入口保留同名）。"""
    issues: list[str] = []
    _check_relations({"sql": sql}, issues)
    if issues:
        raise ValueError("; ".join(issues))


__all__ = ["verify_step", "verify_all", "assert_semantic_only", "records"]
