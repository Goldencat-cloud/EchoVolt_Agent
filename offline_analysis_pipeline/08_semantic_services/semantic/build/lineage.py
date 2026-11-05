"""血缘：源文件摘要、模型版本、构建时间与各级规模。

没有这一层，源数据换了而产物没重建时，所有数字会带着"最新版本"的标签继续发出去。
摘要比较就是为了让这种情况变成一个明确的结论，而不是一个沉默的巧合。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..spec.types import SemanticModel

META_DDL = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def digests(sources: Mapping[str, Path]) -> dict[str, str]:
    return {key: digest(path) for key, path in sorted(sources.items())}


def snapshot_hash(source_digests: Mapping[str, str]) -> str:
    payload = json.dumps(dict(sorted(source_digests.items())), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def write_meta(con: sqlite3.Connection, *, model: SemanticModel,
               source_digests: Mapping[str, str], sources: Mapping[str, Path],
               staging_counts: Mapping[str, int], core_counts: Mapping[str, Any]) -> dict[str, Any]:
    con.executescript(META_DDL)
    meta: dict[str, Any] = {
        "model_version": model.model_version,
        "schema_version": model.schema_version,
        "snapshot_hash": snapshot_hash(source_digests),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_paths": {key: str(path) for key, path in sorted(sources.items())},
        "source_digests": dict(source_digests),
        "staging_counts": dict(staging_counts),
        "core_counts": dict(core_counts),
        "ladder": dict(core_counts.get("ladder") or {}),
    }
    for key, value in meta.items():
        stored = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, stored))
    return meta


def read_meta(path: Path) -> dict[str, Any]:
    """Read the meta table without assuming it exists."""
    if not path.is_file():
        return {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = dict(con.execute("SELECT key, value FROM meta"))
    except sqlite3.DatabaseError:
        return {}
    finally:
        con.close()
    parsed: dict[str, Any] = {}
    for key, value in rows.items():
        try:
            parsed[key] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed[key] = value
    return parsed


def staleness(meta: Mapping[str, Any], source_digests: Mapping[str, str],
              model_version: str) -> tuple[bool, str]:
    """(是否陈旧, 原因)。原因用于让"为什么重建"可解释。"""
    if not meta:
        return True, "no_metadata"
    if meta.get("model_version") != model_version:
        return True, "model_changed"
    if meta.get("source_digests") != dict(source_digests):
        return True, "source_changed"
    return False, ""
