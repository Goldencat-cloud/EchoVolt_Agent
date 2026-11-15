"""Command-line entry: build | render | verify | all."""
from __future__ import annotations

import argparse
import json
import sys

from . import SCHEMA_VERSION
from .paths import ANALYSIS, OUTPUT


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="report_kb",
        description="SU7 offline analysis knowledge-base builder (stdlib-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="generate numbers.json, figures and report.md from frozen analysis data")
    sub.add_parser("render", help="render report.html from configs + numbers.json")
    sub.add_parser("verify", help="consistency gate; exit 1 on any failure")
    sub.add_parser("all", help="build, then render, then verify")
    args = parser.parse_args()

    if args.command in ("build", "all"):
        from .builder import main as build
        build()
    if args.command in ("render", "all"):
        from .render import main as render
        render()
    if args.command in ("verify", "all"):
        from .verify import main as verify
        code = verify()
        if args.command == "verify":
            sys.exit(code)

    print(json.dumps({"command": args.command, "schema_version": SCHEMA_VERSION,
                      "data_root": str(ANALYSIS), "output_root": str(OUTPUT)}, ensure_ascii=False))
    return 0
