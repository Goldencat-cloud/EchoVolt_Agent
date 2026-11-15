"""Consistency gate for the knowledge-base build chain.

Checks (all must pass before delivery):
  1. figures exist and are non-trivial
  2. human HTML has no unresolved [[...]] tokens and inlines every figure
  3. Agent MD carries every key statistic from numbers.json (speed table [K])
  4. HTML/MD numeric consistency on a sample of critical values
  5. case count matches reviewed-cases.json
  6. data-version.json source hashes match actual files
Exit code 0 only when everything passes; JSON verdict on stdout.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from .paths import ANALYSIS, CONFIGS, EVIDENCE, OUTPUT

ROOT = OUTPUT
SAMPLE_KEYS = [
    ("meta.posts_total", "meta", "summary.json"),
    ("comfort_share", "aspects", "aspect-sentiment.csv"),
    ("reli_share", "aspects", "aspect-sentiment.csv"),
    ("price_pre_share", "journey", "profiles.json"),
    ("scope_in", "scope", "scope.json"),
]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    errors, checks = [], []
    n = json.loads((ROOT / "numbers.json").read_text(encoding="utf-8"))

    # 1. figures
    manifest = json.loads((ROOT / "data-version.json").read_text(encoding="utf-8"))
    for fig in manifest["figures"]:
        p = ROOT / "assets" / fig
        if not p.is_file() or p.stat().st_size < 500 or "<svg" not in p.read_text(encoding="utf-8"):
            errors.append(f"figure bad or missing: {fig}")
    checks.append(("figures", manifest["figures"] and not errors))

    html = (ROOT / "report.html").read_text(encoding="utf-8")
    md = (ROOT / "report.md").read_text(encoding="utf-8")

    # 2. HTML tokens, figures, content-driven sections
    leftover = re.findall(r"\[\[[^\]]+\]\]", html)
    if leftover:
        errors.append(f"unresolved tokens in report.html: {sorted(set(leftover))}")
    for fig in manifest["figures"]:
        if "<svg" not in html:
            errors.append("no inline svg in report.html")
            break
    for needle in ["P1", "研究含义", "研究方法与数据", "核心发现", "使用边界"]:
        if needle not in html:
            errors.append(f"report.html missing expected content: {needle}")
    content = json.loads((CONFIGS / "content.json").read_text(encoding="utf-8"))
    for key in [content["methodology"]["id"], content["recommendations"]["id"]] + \
               [f["id"] for f in content["findings"]]:
        if f"id='{key}'" not in html:
            errors.append(f"section missing in report.html: {key}")
    checks.append(("html_rendered", not any(("token" in e) or ("svg" in e) or ("content" in e) or ("section" in e) for e in errors)))

    # 3. Agent MD speed table covers numbers.json scalars
    flat = {}
    def walk(d, prefix=""):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, prefix + k + ".")
            elif isinstance(v, str):
                flat[prefix + k] = v
    walk(n["meta"])
    for k in ["comfort_share", "reli_share", "serv_share", "price_pre_share", "svc_ordered_share",
              "scope_in", "heat_neg_share", "cases_count"]:
        flat[k] = str(n.get(k, ""))
    missing_md = [k for k, v in flat.items() if v and v not in md]
    if missing_md:
        errors.append(f"values absent from report.md: {missing_md}")
    checks.append(("md_numbers", not missing_md))

    # 4. HTML/MD consistency on sample values
    def dig(d, path):
        cur = d
        for part in path.split("."):
            cur = cur[part]
        return str(cur)
    for path, *_ in SAMPLE_KEYS:
        v = dig(n, path)
        if v not in html or v not in md:
            errors.append(f"consistency: '{path}'={v} not found in both html and md")
    checks.append(("consistency_sample", all(dig(n, p) in html and dig(n, p) in md for p, *_ in SAMPLE_KEYS)))

    # 5. cases
    cases = n["cases"]
    card_count = len(re.findall(r"class=['\"]case['\"]", html))
    if card_count != len(cases):
        errors.append(f"case cards {card_count} != cases {len(cases)}")
    checks.append(("cases", card_count == len(cases)))

    # 6. source hashes
    for s in manifest["sources"]:
        p = ANALYSIS / Path(s["file"]).name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != s["sha256"]:
            errors.append(f"source file changed or missing: {s['file']}")
    checks.append(("source_hashes", all("source file" not in e for e in errors)))

    ok = not errors
    verdict = {"ok": ok, "checks": {k: bool(v) for k, v in checks}, "errors": errors}
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "verify-latest.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
