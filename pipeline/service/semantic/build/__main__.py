"""CLI: ``python -m semantic.build [--force] [--check] [--db PATH]``.

Exit codes: 0 built or already current, 2 model/source problem, 3 stale (with --check).
"""

from __future__ import annotations

import argparse
import json
import sys

from ..spec.errors import ModelError
from .runner import build, check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建语义层数据库")
    parser.add_argument("--db", default=None, help="产物路径，默认 data/semantic.db")
    parser.add_argument("--force", action="store_true", help="忽略已有产物，强制重建")
    parser.add_argument("--check", action="store_true", help="只检查产物是否与源一致")
    args = parser.parse_args(argv)
    try:
        result = check(db_path=args.db) if args.check else build(
            db_path=args.db, force=args.force)
    except ModelError as exc:
        print(f"模型或数据源错误：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.check and result.get("status") == "stale":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
