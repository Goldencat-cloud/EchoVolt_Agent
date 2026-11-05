"""Pipeline unit tests (no LLM needed).

Covers the deterministic guarantees: version footer, anchor validation,
context assembly includes refusal list [R] and template [T], context budget.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qa_agent import pipeline  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    checks = []

    diag = pipeline.diagnostics()
    checks.append(("report_exists", diag["exists"]))
    checks.append(("fits_full_context", diag["fits_full_context"]))

    report = pipeline.REPORT_MD.read_text(encoding="utf-8")
    anchors = pipeline._anchors(report)
    checks.append(("anchors_parsed", {"K", "D", "R", "T"} <= anchors))

    sys_prompt = pipeline._system_prompt()
    checks.append(("version_in_system_prompt", "数据版本" in sys_prompt))

    known = pipeline._validate_anchors("依据 [K] 与 [F3]", anchors)
    checks.append(("known_anchor_ok", known["unknown"] == []))
    bogus = pipeline._validate_anchors("见 [F9]", anchors)
    checks.append(("bogus_anchor_flagged", bogus["unknown"] == ["F9"]))

    r = pipeline.ask("", no_llm=True)
    checks.append(("empty_question_rejected", r.get("error_code") == "empty_question"))

    r = pipeline.ask("舒适性负面占比是多少", no_llm=True)
    checks.append(("no_llm_diagnostics", r["mode"] == "diagnostics_only" and r["ok"]))
    checks.append(("version_everywhere", "数据版本" in r["version"]))

    ok = all(v for _, v in checks)
    print(json.dumps({"ok": ok, "checks": checks, "diag": diag}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
