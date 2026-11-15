# -*- coding: utf-8 -*-
"""清洗管线命令行入口（pyproject scripts 指向此模块）。"""
from __future__ import annotations

import argparse
import json
import sys

from . import pipeline

DEFAULT_DB_HINT = "pipeline/data/stock/db/ingestion.sqlite3"


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp1252，中文输出会 UnicodeEncodeError；强制 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="auto-022 语料清洗管线（stdlib-only）")
    ap.add_argument("--db", required=True, help="stock 库路径")
    ap.add_argument("--version", default=pipeline.DEFAULT_CLEANING_VERSION, help="cleaning_version 标识")
    ap.add_argument("--dry-run", action="store_true", help="只计算与打印统计，不写库")
    args = ap.parse_args(argv)

    stats = pipeline.run(args.db, cleaning_version=args.version, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))

    drift_bad = [k for k, v in stats.get("anchors", {}).items() if abs(v.get("delta", 0)) > 5
                 and k not in ("clean_subset", "multimodal_urls_before")]
    if drift_bad:
        print(f"WARN anchor drift>5: {drift_bad} (see docs/evidence/)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
