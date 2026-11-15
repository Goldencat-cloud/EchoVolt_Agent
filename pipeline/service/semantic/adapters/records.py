"""行级读取适配：给 HTTP / MCP / Agent 提供明细与元信息的统一取数口。

语义模型的查询协议面向聚合（metrics × dimensions）；取证、列表、报告附录
需要的是**行**。两者读同一份 `semantic.db`，但入口不同：

- 聚合与口径：`compile/` 编译成 SQL，指标、维度与上限由模型声明决定；
- 明细：本模块直读 core 物化表（`fct_claim` / `dim_post` / `claim_population`），
  只做参数绑定与列裁剪。

**统计口径不在这里重复实现**：任何"多少条、占比多少"都必须走语义引擎
（`execute` / `execute_saved`），本模块只回答"有哪些具体记录"。

这里的物理表名是唯一允许出现的地方：core 表由 `semantic/build/core.py`
固定；上层只认本节返回的字段，不认表结构。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..build.paths import DEFAULT_DB_PATH

#: 明细允许的排序方式；调用方只能选名字，不能传表达式。
_ORDERS = {
    "date_desc": 'p."published_at" DESC, c."claim_id"',
    "date_asc": 'p."published_at" ASC, c."claim_id"',
    "claim_id": 'c."claim_id"',
}
#: 情感别名归一（旧接口把"混合"当独立取值）。
_SENTIMENT_ALIAS = {"混合": "正负混合"}
_SELECT = ('SELECT c."claim_id", c."post_id", c."aspect", c."sentiment", c."claim_type", '
           'c."journey", c."ownership", c."experience", c."statement", '
           'c."content", c."quote", c."month", '
           'p."title", p."url", p."published_at" '
           'FROM fct_claim c LEFT JOIN dim_post p ON p.post_id = c.post_id '
           'LEFT JOIN claim_population m ON m.claim_id = c.claim_id')


class RecordsUnavailable(RuntimeError):
    """语义库不存在或不可读；上层据此降级或报错，不静默返回空结果。"""


def db_path() -> Path:
    return Path(DEFAULT_DB_PATH)


def available() -> bool:
    return db_path().is_file()


def _connect() -> sqlite3.Connection:
    path = db_path()
    if not path.is_file():
        raise RecordsUnavailable(f"语义库不存在：{path}；先执行 python -m semantic.build")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def meta() -> dict[str, Any]:
    """构建元信息：模型版本、快照哈希、构建时间与各级口径规模。"""
    con = _connect()
    try:
        try:
            raw = dict(con.execute("SELECT key, value FROM meta"))
        except sqlite3.DatabaseError:
            raw = {}
    finally:
        con.close()
    return {"model_version": raw.get("model_version"),
            "snapshot_hash": raw.get("snapshot_hash"),
            "built_at": raw.get("built_at"),
            "temporary_sample": raw.get("temporary_sample"),
            "ladder": _ladder(raw.get("ladder"))}


def _ladder(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): int(item) for key, item in value.items()
            if isinstance(item, (int, float))}


def data_version() -> str:
    """对外数据版本令牌。

    语义库的版本就是模型版本（口径一变必须递增），令牌直接由它派生：
    再去读第二份 06 产物版本号，两处必然漂移。
    """
    version = meta().get("model_version")
    return f"semantic-{version}" if version else "unknown"


def snapshot_hash() -> str:
    return str(meta().get("snapshot_hash") or "")


def aspects(*, population: str | None = None) -> list[str]:
    """可用议题；给口径时只返回该口径内有成员的议题。"""
    con = _connect()
    try:
        if population:
            rows = con.execute(
                'SELECT DISTINCT c."aspect" FROM fct_claim c '
                'JOIN claim_population m ON m.claim_id = c.claim_id '
                'WHERE m.population = ? AND c."aspect" IS NOT NULL ORDER BY c."aspect"',
                (population,))
        else:
            rows = con.execute('SELECT DISTINCT "aspect" FROM fct_claim '
                               'WHERE "aspect" IS NOT NULL ORDER BY "aspect"')
        return [row[0] for row in rows]
    finally:
        con.close()


def population_size(population: str) -> int:
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM claim_population WHERE population = ?",
                           (population,)).fetchone()[0]
    finally:
        con.close()


def _where(*, aspect: str | None, sentiment: str | None, journey: str | None,
           ownership: str | None, experience: str | None, population: str | None,
           require_quote: bool) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if population:
        clauses.append("m.population = ?")
        params.append(population)
    if aspect:
        clauses.append('c."aspect" = ?')
        params.append(aspect)
    if sentiment:
        clauses.append('c."sentiment" = ?')
        params.append(_SENTIMENT_ALIAS.get(sentiment, sentiment))
    for column, value in (("journey", journey), ("ownership", ownership),
                          ("experience", experience)):
        if value:
            clauses.append(f'c."{column}" = ?')
            params.append(value)
    if require_quote:
        clauses.append("c.\"quote\" IS NOT NULL AND c.\"quote\" <> ''")
    return ((" WHERE " + " AND ".join(clauses)) if clauses else ""), params


def claim_rows(*, aspect: str | None = None, sentiment: str | None = None,
               journey: str | None = None, ownership: str | None = None,
               experience: str | None = None, population: str | None = "curated",
               require_quote: bool = False, limit: int | None = None,
               offset: int = 0, order: str = "date_desc") -> list[dict[str, Any]]:
    """按维度取观点明细（含标题、链接、引文）。

    `population=None` 表示不限口径；给口径时只取该口径成员，成员关系来自
    构建期写入的 `claim_population`，不在这里重算阶梯。
    """
    if order not in _ORDERS:
        raise ValueError(f"unsupported order: {order}")
    where, params = _where(aspect=aspect, sentiment=sentiment, journey=journey,
                           ownership=ownership, experience=experience,
                           population=population, require_quote=require_quote)
    sql = f"{_SELECT}{where} ORDER BY {_ORDERS[order]}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [max(0, int(limit)), max(0, int(offset))]
    con = _connect()
    try:
        return [dict(row) for row in con.execute(sql, params)]
    finally:
        con.close()


def claim_count(*, aspect: str | None = None, sentiment: str | None = None,
                journey: str | None = None, ownership: str | None = None,
                experience: str | None = None, population: str | None = "curated",
                require_quote: bool = False) -> int:
    """与 `claim_rows` 同筛选条件下的总数（分页用）。"""
    where, params = _where(aspect=aspect, sentiment=sentiment, journey=journey,
                           ownership=ownership, experience=experience,
                           population=population, require_quote=require_quote)
    sql = ('SELECT COUNT(*) FROM fct_claim c '
           'LEFT JOIN claim_population m ON m.claim_id = c.claim_id' + where)
    con = _connect()
    try:
        return con.execute(sql, params).fetchone()[0]
    finally:
        con.close()


def claim_by_id(claim_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """按 claim_id 取明细；不存在的 id 不出现在返回里，由调用方如实标注。"""
    wanted = [str(item).strip() for item in claim_ids or () if str(item).strip()]
    if not wanted:
        return {}
    placeholders = ",".join("?" for _ in wanted)
    con = _connect()
    try:
        rows = con.execute(f'{_SELECT} WHERE c."claim_id" IN ({placeholders})', wanted)
        return {row["claim_id"]: dict(row) for row in rows}
    finally:
        con.close()
