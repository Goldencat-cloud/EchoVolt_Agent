"""数据质量门禁（只读校验器）。

检查项：
  semantic-freshness  semantic.db meta.source_digests 与本地上游哈希比对（发布库陈旧检测）

用法：
  python pipeline/tools/quality_gate.py [--check semantic-freshness]

Exit code：0 通过；1 存在漂移（告警级）；2 结构性损坏（库缺失或不可读）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_DB = PIPELINE_ROOT / "data" / "published" / "semantic.db"
MODEL_YAML = PIPELINE_ROOT / "service" / "semantic" / "model.yaml"


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _parse_model_sources() -> dict[str, str]:
    """从 semantic/model.yaml 的 snapshot.paths 提取 {key: 相对路径}。"""
    text = MODEL_YAML.read_text(encoding="utf-8")
    block = re.search(r"^\s*paths:\s*$(.*?)^\S", text, re.M | re.S)
    if not block:
        raise ValueError("model.yaml: snapshot.paths not found")
    sources: dict[str, str] = {}
    for line in block.group(1).splitlines():
        pair = re.match(r"^    (\w+):\s*(.+?)\s*$", line)
        if pair:
            sources[pair.group(1)] = pair.group(2)
    return sources


def check_semantic_freshness() -> tuple[str, dict]:
    if not SEMANTIC_DB.is_file():
        return "fail", {"error": f"missing {SEMANTIC_DB}"}
    con = sqlite3.connect(f"file:{SEMANTIC_DB.as_posix()}?mode=ro", uri=True)
    try:
        rows = dict(con.execute("SELECT key, value FROM meta"))
    finally:
        con.close()
    digests = json.loads(rows.get("source_digests", "{}"))
    if not digests:
        return "fail", {"error": "meta.source_digests missing"}
    report: dict = {}
    drift = False
    for key, rel in _parse_model_sources().items():
        path = PIPELINE_ROOT / rel
        if not path.is_file():
            report[key] = {"status": "missing", "path": rel}
            drift = True
            continue
        actual = _sha256_file(path)
        expected = digests.get(key)
        report[key] = {"path": rel,
                       "status": "ok" if actual == expected else "changed"}
        if actual != expected:
            drift = True
    return ("pass" if not drift else "drift"), report


CHECKS = {
    "semantic-freshness": check_semantic_freshness,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", default=",".join(CHECKS),
                        help="逗号分隔的检查项，默认全部")
    args = parser.parse_args(argv)
    selected = [c.strip() for c in args.check.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CHECKS]
    if unknown:
        print(json.dumps({"error": f"unknown checks: {unknown}",
                          "available": list(CHECKS)}, ensure_ascii=False))
        return 2
    started = time.perf_counter()
    verdicts = {}
    overall = 0
    for name in selected:
        status, report = CHECKS[name]()
        verdicts[name] = {"status": status, **report}
        if status == "fail":
            overall = 2
        elif status == "drift" and overall == 0:
            overall = 1
    verdicts["_meta"] = {"exit": overall, "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    print(json.dumps(verdicts, ensure_ascii=False, indent=2))
    return overall


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
