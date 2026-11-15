# -*- coding: utf-8 -*-
"""Independent audit products (Phase 3, offline). Audit data is NEVER fed to the
model; credentials never appear here. Written only under the allowed output tree.

Products:
  * input_hashes.json                       -- whole-file SHA-256 of read-only inputs
  * model_inputs.jsonl                      -- exact slim image-text input + hash per post
  * image_positions_audit.jsonl             -- per-image-position source/fallback/anomaly
  * auto007_citation_suspicious_posts.json  -- the citation-suspicious 007 images + affected posts
  * unused_auto007_results.json             -- 007 results not injected anywhere + reason
"""
import json
from pathlib import Path

from . import util


def write_input_hashes(input_files, out_path):
    """``input_files``: list of (label, path). Writes a JSON mapping label -> hashes."""
    entries = {}
    for label, path in input_files:
        p = Path(path)
        entries[label] = {
            "path": str(p),
            "sha256": util.sha256_file(p) if p.is_file() else None,
            "size_bytes": p.stat().st_size if p.is_file() else None,
        }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_model_inputs(integrations, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for integ in integrations:
            fh.write(json.dumps({
                "post_id": integ["post_id"],
                "post_input": integ["post_input"],
                "post_input_json": integ["post_input_json"],
                "post_input_sha256": integ["post_input_sha256"],
                "fingerprint": integ["fingerprint"],
            }, ensure_ascii=False) + "\n")
    return out_path


def write_image_positions_audit(integrations, out_path):
    """One line per image position (in post order) with source/fallback/anomaly."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for integ in integrations:
            for src in integ["image_sources"]:
                fh.write(json.dumps({
                    "post_id": integ["post_id"],
                    "pos": src["pos"],
                    "url": src.get("url"),
                    "image_id": src.get("image_id"),
                    "mapped": src["mapped"],
                    "source": src.get("source"),
                    "summary_present": src["summary_present"],
                    "fallback": src["fallback"],
                    "note": src.get("note"),
                }, ensure_ascii=False) + "\n")
            for anom in integ.get("anomalies", []):
                fh.write(json.dumps({"post_id": integ["post_id"], "anomaly": anom},
                                    ensure_ascii=False) + "\n")
    return out_path


def _used_007_by_image(integrations):
    """``image_id -> [post_id]`` for images whose AUTO-007 summary was adopted."""
    by_image = {}
    for integ in integrations:
        for src in integ["image_sources"]:
            if src.get("source") == "AUTO-007" and src.get("image_id"):
                by_image.setdefault(src["image_id"], []).append(integ["post_id"])
    return by_image


def write_auto007_citation_suspicious(results007_raw, integrations, out_path):
    """Record every citation-suspicious 007 image, whether it was injected, and
    the posts affected (only where actually injected)."""
    used = _used_007_by_image(integrations)
    items = []
    for o in results007_raw:
        if o.get("citation_valid") is not False:
            continue
        iid = o.get("image_id")
        items.append({
            "image_id": iid,
            "post_id_007": o.get("post_id"),
            "url": o.get("url"),
            "citation_valid": False,
            "citation_offending": o.get("citation_offending"),
            "injected": iid in used,
            "affected_posts": sorted(set(used.get(iid, []))),
        })
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "definition": "AUTO-007 records with citation_valid == False",
        "total": len(items),
        "injected_count": sum(1 for i in items if i["injected"]),
        "distinct_affected_posts": len({p for i in items for p in i["affected_posts"]}),
        "items": items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_unused_auto007(results007_raw, integrations, out_path):
    """Record every AUTO-007 result NOT adopted as an AUTO-007 source, with a
    specific reason. Two cases:
      * the image appears in a post's sequence but its 007 result was a
        technical failure -> fell back to AUTO-006;
      * the image URL is absent from every post's multimodal_content.
    Nothing is silently dropped."""
    used = _used_007_by_image(integrations)
    mapped_in_seq = {s["image_id"] for i in integrations for s in i["image_sources"]
                     if s.get("mapped") and s.get("image_id")}
    items = []
    for o in results007_raw:
        iid = o.get("image_id")
        if iid in used:
            continue
        if iid in mapped_in_seq:
            reason = "auto007_failed_fell_back_to_auto006"
        else:
            reason = "image_url_absent_from_every_post_multimodal_content"
        items.append({
            "image_id": iid,
            "post_id_007": o.get("post_id"),
            "url": o.get("url"),
            "status": o.get("status"),
            "reason": reason,
        })
    reasons = {}
    for it in items:
        reasons[it["reason"]] = reasons.get(it["reason"], 0) + 1
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "definition": "AUTO-007 results not adopted as an AUTO-007 source",
        "total": len(items),
        "reason_counts": reasons,
        "items": items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
