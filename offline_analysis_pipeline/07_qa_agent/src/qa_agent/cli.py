"""CLI: ask | diag. Mirrors report_kb CLI style."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="qa_agent", description=f"SU7 report Q&A (full-context LLM, stdlib-only) v{__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="ask a question against the report")
    ask.add_argument("question")
    ask.add_argument("--no-llm", action="store_true",
                     help="without LLM: show diagnostics only (report size, anchors, version)")
    sub.add_parser("diag", help="show knowledge-base diagnostics")
    args = parser.parse_args()

    if args.command == "diag":
        from . import pipeline
        print(json.dumps(pipeline.diagnostics(), ensure_ascii=False, indent=1))
        return 0
    if args.command == "ask":
        from . import pipeline
        result = pipeline.ask(args.question, no_llm=args.no_llm)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result.get("ok") else 1
    return 0
