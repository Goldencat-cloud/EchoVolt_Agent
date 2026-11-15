"""标准层记录的新旧版本裁决。

纯函数：不访问数据库、不感知表结构。记录来源优先级由调用方按需提供，
因此时间戳已能定论时不会额外查询 provenance。
"""
from __future__ import annotations

from typing import Any, Callable, Collection, Mapping

OLDER_SKIPPED = 'older_skipped'
CONFLICT = 'conflict'
APPLY = 'updated'


def decide(*, incoming_ts: float | None, previous_ts: float | None, same_snapshot: bool,
           priorities: Callable[[], tuple[int, int]],
           incoming: Mapping[str, Any], previous: Mapping[str, Any],
           ignored: Collection[str] = ()) -> str:
    """裁决一条新记录的去向：保留旧版、判为冲突或写入。

    `priorities()` 返回 (新, 旧) 的来源优先级，只在时间戳相同且快照不同时
    调用，调用方的查询次数因此与内联实现保持一致。
    """
    if previous_ts is not None and (incoming_ts is None or incoming_ts < previous_ts):
        return OLDER_SKIPPED
    if incoming_ts != previous_ts or same_snapshot:
        return APPLY
    incoming_priority, previous_priority = priorities()
    if incoming_priority < previous_priority:
        return OLDER_SKIPPED
    if incoming_priority > previous_priority:
        return APPLY
    return CONFLICT if differs(incoming, previous, ignored) else APPLY


def differs(incoming: Mapping[str, Any], previous: Mapping[str, Any],
            ignored: Collection[str] = ()) -> bool:
    """同一时点下两侧都有值的字段是否存在不一致。

    `previous` 可能是 `sqlite3.Row`：它的 `in` 按值迭代而非按列名，
    因此先取显式列名集合再判断字段是否存在。
    """
    skip = set(ignored)
    known = previous.keys() if hasattr(previous, 'keys') else previous
    return any(
        key not in skip
        and incoming[key] not in (None, '')
        and previous[key] not in (None, '')
        and incoming[key] != previous[key]
        for key in incoming if key in known
    )
