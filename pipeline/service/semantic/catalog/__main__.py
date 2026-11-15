"""CLI: ``python -m semantic.catalog [--db PATH] [--no-values]``."""

from __future__ import annotations

import argparse
import sys

from ..compile import QueryError
from .describe import describe, dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出语义目录")
    parser.add_argument("--db", default=None, help="产物路径，默认 data/semantic.db")
    parser.add_argument("--no-values", action="store_true",
                        help="只导出定义，不读取库里的枚举与规模")
    args = parser.parse_args(argv)
    try:
        catalogue = describe(db_path=args.db, with_values=not args.no_values)
    except QueryError as exc:
        print(dumps(exc.as_dict()), file=sys.stderr)
        return 2
    print(dumps(catalogue))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
