# -*- coding: utf-8 -*-
"""The ten verification checks (Section 九), computed from the output tree + the
read-only inputs. Returns a list of ``{"id","name","passed","detail"}``. This is
an audit of the pipeline; it does NOT equate JSON validity / coverage / model
confidence with summary accuracy."""
import json
from pathlib import Path

from . import config
from . import loader
from . import runner
from . import select
from . import util
from . import validate as val


def _load_json_lines(path):
    out = []
    p = Path(path)
    if p.is_file():
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    return out


def _load_json(path):
    p = Path(path)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def run_checks(out_dir):
    out_dir = Path(out_dir)
    integrations = _load_json_lines(out_dir / "integration.jsonl")
    results = runner.consolidate(out_dir / "results.jsonl")
    res006 = loader.read_jsonl(config.RES006)
    res007 = loader.read_jsonl(config.RES007)
    t006 = select.build_006_table(res006)
    t007 = select.build_007_table(res007)

    checks = []

    def add(cid, name, passed, detail):
        checks.append({"id": cid, "name": name, "passed": bool(passed), "detail": detail})

    # 1. population closure
    total = len(integrations)
    uniq = len({i["post_id"] for i in integrations})
    succ = sum(1 for r in results.values() if r.get("status") == "success")
    fail = len(results) - succ
    unproc = total - len(results)
    add(1, "population_closure",
        total == uniq and (succ + fail + unproc) == total,
        "total=%d unique=%d success=%d failed=%d unprocessed=%d"
        % (total, uniq, succ, fail, unproc))

    # 2. no-image coverage
    noimg = [i for i in integrations if not i["has_images"]]
    covered = sum(1 for i in noimg if i["post_id"] in results)
    add(2, "no_image_covered", covered == len(noimg),
        "no_image=%d covered=%d" % (len(noimg), covered))

    # 3. non-irrelevant image summaries == AUTO-006 verbatim
    mism3 = 0
    cnt3 = 0
    for i in integrations:
        for s in i["image_sources"]:
            if s.get("source") == "AUTO-006" and s.get("mapped"):
                cnt3 += 1
                exp = (t006.get(s["image_id"]) or {}).get("summary")
                if s.get("chosen_summary") != exp:
                    mism3 += 1
    add(3, "non_irrelevant_eq_auto006_verbatim", mism3 == 0,
        "checked=%d mismatches=%d" % (cnt3, mism3))

    # 4. irrelevant-class successful summaries == AUTO-007 verbatim
    mism4 = 0
    cnt4 = 0
    for i in integrations:
        for s in i["image_sources"]:
            if s.get("source") == "AUTO-007" and s.get("mapped"):
                cnt4 += 1
                exp = (t007.get(s["image_id"]) or {}).get("summary")
                if s.get("chosen_summary") != exp:
                    mism4 += 1
    add(4, "irrelevant_class_eq_auto007_verbatim", mism4 == 0,
        "checked=%d mismatches=%d" % (cnt4, mism4))

    # 5. every AUTO-007 result used or has explicit unused reason
    used007 = {s["image_id"] for i in integrations for s in i["image_sources"]
               if s.get("source") == "AUTO-007" and s.get("image_id")}
    unused_doc = _load_json(out_dir / "unused_auto007_results.json") or {}
    unused_ids = {x["image_id"] for x in unused_doc.get("items", [])}
    all007 = set(t007.keys())
    unaccounted = all007 - used007 - unused_ids
    add(5, "auto007_all_accounted", not unaccounted,
        "total_007=%d used=%d unused_recorded=%d unaccounted=%d"
        % (len(all007), len(used007), len(unused_ids), len(unaccounted)))

    # 6. fallback / missing / mapping-anomaly / citation-suspicious traceable
    fallback_n = sum(1 for i in integrations for s in i["image_sources"] if s.get("fallback"))
    missing_n = sum(1 for i in integrations for s in i["image_sources"]
                    if s.get("note", "").startswith(("006_", "007_")))
    unmapped_n = sum(1 for i in integrations for a in i.get("anomalies", [])
                     if a.get("kind") == "mapping_anomaly")
    cit_doc = _load_json(out_dir / "auto007_citation_suspicious_posts.json") or {}
    add(6, "anomalies_traceable",
        (out_dir / "image_positions_audit.jsonl").is_file()
        and (out_dir / "auto007_citation_suspicious_posts.json").is_file(),
        "fallback=%d missing_or_note=%d unmapped=%d citation_suspicious=%d"
        % (fallback_n, missing_n, unmapped_n, cit_doc.get("total", 0)))

    # 7. order / anchors / JSON / citation legality for successes
    bad7 = 0
    detail7 = []
    for pid, rec in results.items():
        if rec.get("status") != "success":
            continue
        integ = next((i for i in integrations if i["post_id"] == pid), None)
        if integ is None:
            bad7 += 1
            detail7.append("%s:no_integration" % pid)
            continue
        text_ids = {b["text_block_id"] for b in integ["sequence"] if b["type"] == "text"}
        img_ids = {b["image_id"] for b in integ["sequence"]
                   if b["type"] == "image" and b["image_id"] is not None}
        ok, offending = val.check_citations(rec.get("parsed") or {}, text_ids, img_ids)
        if not ok:
            bad7 += 1
            detail7.append("%s:%s" % (pid, offending[:3]))
    add(7, "order_anchors_json_citations_legal", bad7 == 0,
        "success_checked=%d illegal=%d %s"
        % (sum(1 for r in results.values() if r.get("status") == "success"), bad7,
           detail7[:3]))

    # 8. chunking: no silent omission, synthesis traceable
    chunked = [r for r in results.values() if r.get("chunked")]
    cov_bad = 0
    for r in chunked:
        plan = r.get("chunk_plan") or {}
        if plan.get("coverage_ok") is not True:
            cov_bad += 1
    add(8, "chunking_no_silent_omission", cov_bad == 0,
        "chunked_posts=%d coverage_bad=%d" % (len(chunked), cov_bad))

    # 9. resume: no reprocessing / no version mixing
    fp_by_pid = {}
    mix = 0
    for pid, rec in results.items():
        fp = rec.get("fingerprint")
        if fp in fp_by_pid and fp_by_pid[fp] != rec.get("fingerprint"):
            mix += 1
        fp_by_pid[pid] = rec.get("fingerprint")
    # ensure success fingerprints match current integrations
    integ_fp = {i["post_id"]: i["fingerprint"] for i in integrations}
    stale = 0
    for pid, rec in results.items():
        if rec.get("status") == "success" and rec.get("fingerprint") != integ_fp.get(pid):
            stale += 1
    add(9, "resume_no_mix", mix == 0 and stale == 0,
        "mixed=%d stale_success=%d" % (mix, stale))

    # 10. inputs unmodified (re-hash vs recorded baseline)
    baseline = _load_json(out_dir / "input_hashes.json") or {}
    input_files = [
        ("csv004", config.CSV004), ("csv003", config.CSV003),
        ("res006", config.RES006), ("res007", config.RES007),
    ]
    changed = []
    for label, path in input_files:
        rec = baseline.get(label) or {}
        if rec.get("sha256") and util.sha256_file(path) != rec["sha256"]:
            changed.append(label)
    add(10, "inputs_unmodified", not changed,
        "changed=%s" % (changed if changed else "none"))

    return checks


def summarize(checks):
    passed = sum(1 for c in checks if c["passed"])
    return {
        "total": len(checks),
        "passed": passed,
        "failed": len(checks) - passed,
        "all_passed": passed == len(checks),
        "checks": checks,
    }
