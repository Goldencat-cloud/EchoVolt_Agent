"""CLI: ``python -m semantic.model [path]`` prints a model summary.

Exit code 0 means the document is both well shaped and internally consistent;
exit code 2 means it was rejected, with the reason printed to stderr.
"""

from __future__ import annotations

import json
import sys

from .loader import load_model, summarise
from ..spec.errors import ModelError


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else None
    try:
        model = load_model(path)
    except ModelError as exc:
        print(f"模型校验失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(summarise(model), ensure_ascii=False, indent=2))
    print("模型校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
