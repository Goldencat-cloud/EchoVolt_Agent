"""查询期错误：每一个都是一个可被调用方处理的结论，而不是空结果。

错误码集中在这里，是因为错误码一旦散落成字符串，调用方就只能靠中文文案判断，
文案一改校验就失效——这正是本项目已经发生过的问题。
"""

from __future__ import annotations

from typing import Any

UNKNOWN_METRIC = "UNKNOWN_METRIC"
UNKNOWN_DIMENSION = "UNKNOWN_DIMENSION"
UNKNOWN_POPULATION = "UNKNOWN_POPULATION"
UNKNOWN_FIELD = "UNKNOWN_FIELD"
DIMENSION_NOT_ALLOWED = "DIMENSION_NOT_ALLOWED"
TOO_MANY_DIMENSIONS = "TOO_MANY_DIMENSIONS"
LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
POPULATION_MISMATCH = "POPULATION_MISMATCH"
MIXED_DATASETS = "MIXED_DATASETS"
FANOUT_RISK = "FANOUT_RISK"
UNRESOLVED_FILTER = "UNRESOLVED_FILTER"
OUT_OF_COVERAGE = "OUT_OF_COVERAGE"
MISSING_PARAM = "MISSING_PARAM"
STALE_ARTIFACT = "STALE_ARTIFACT"
UNSUPPORTED = "UNSUPPORTED"


class QueryError(ValueError):
    """A request the model cannot answer; never silently degraded to empty rows."""

    def __init__(self, code: str, message: str, *, hint: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.hint = hint
        self.details = details or {}
        text = f"{code}: {message}"
        if hint:
            text += f"（{hint}）"
        super().__init__(text)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return payload
