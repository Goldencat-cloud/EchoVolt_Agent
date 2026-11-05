"""构建入口：源 → staging → core → 元信息。

构建是幂等的：同样的源与同样的模型版本，第二次调用直接返回"已是最新"，
不再重复解析 2.7 万条观点。源或模型变了才重建，并在返回值里说明原因。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from ..model import load_model
from ..spec.types import SemanticModel
from . import core, ddl, lineage, staging
from .paths import DEFAULT_DB_PATH, source_path


class BuildError(RuntimeError):
    """构建无法产生可信产物。"""


def build(model: SemanticModel | None = None, db_path: str | Path | None = None,
          force: bool = False) -> dict[str, Any]:
    model = model or load_model()
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    sources = {key: source_path(model, key) for key in model.snapshot.paths}
    source_digests = lineage.digests(sources)

    if path.is_file() and not force:
        meta = lineage.read_meta(path)
        stale, reason = lineage.staleness(meta, source_digests, model.model_version)
        if not stale:
            return {"status": "up_to_date", "db_path": str(path), **meta}

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    started = time.perf_counter()
    con = sqlite3.connect(path)
    try:
        staging.create(con)
        staging_counts = staging.load(con, model)
        core.create(con)
        core_counts = core.build(con, model, lineage.snapshot_hash(source_digests))
        views = ddl.create_views(con, model)
        meta = lineage.write_meta(
            con, model=model, source_digests=source_digests, sources=sources,
            staging_counts=staging_counts, core_counts=core_counts)
        con.commit()
    except Exception:
        con.close()
        # 半成品库不能被后续查询当成有效产物。
        if path.exists():
            path.unlink()
        raise
    finally:
        try:
            con.close()
        except sqlite3.ProgrammingError:
            pass
    return {
        "status": "built",
        "db_path": str(path),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "views": views,
        **meta,
    }


def check(model: SemanticModel | None = None,
          db_path: str | Path | None = None) -> dict[str, Any]:
    """Report whether the existing database still matches its sources."""
    model = model or load_model()
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.is_file():
        return {"status": "missing", "db_path": str(path)}
    sources = {key: source_path(model, key) for key in model.snapshot.paths}
    meta = lineage.read_meta(path)
    stale, reason = lineage.staleness(meta, lineage.digests(sources), model.model_version)
    return {"status": "stale" if stale else "up_to_date", "reason": reason,
            "db_path": str(path), **meta}
