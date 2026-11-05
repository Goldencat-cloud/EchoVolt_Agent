# -*- coding: utf-8 -*-
"""Per-image summary selection, keyed STRICTLY on the AUTO-006 first-pass
``image_type`` (never on the AUTO-007-renamed type). Upstream raw results are
consumed verbatim; nothing is re-viewed, re-written, or deleted."""
IRRELEVANT = "irrelevant"


def build_006_table(results006):
    """``image_id -> {"status", "image_type", "summary"}`` (first-pass)."""
    table = {}
    for o in results006:
        iid = o.get("image_id")
        if not iid:
            continue
        parsed = o.get("parsed") or {}
        table[iid] = {
            "status": o.get("status"),
            "image_type": parsed.get("image_type"),
            "summary": parsed.get("summary"),
        }
    return table


def build_007_table(results007):
    """``image_id -> {"status", "summary", "citation_valid"}`` (context re-analysis)."""
    table = {}
    for o in results007:
        iid = o.get("image_id")
        if not iid:
            continue
        parsed = o.get("parsed") or {}
        table[iid] = {
            "status": o.get("status"),
            "summary": parsed.get("summary"),
            "citation_valid": o.get("citation_valid"),
        }
    return table


def select_summary(image_id, t006, t007):
    """Select the summary for a mapped image_id.

    Returns ``(summary, source, note)`` where ``source`` is one of
    ``"AUTO-006" | "AUTO-007" | "AUTO-006-fallback" | None`` and ``note`` is
    ``None`` or a machine-readable reason for fallback/missing/failed.
    """
    r6 = t006.get(image_id)
    r7 = t007.get(image_id)

    # AUTO-006 failed or result missing -> keep position, summary=null.
    if r6 is None:
        return None, None, "006_missing"
    if r6.get("status") != "success":
        return None, None, "006_failed:%s" % (r6.get("status") or "unknown")

    # First-pass not irrelevant -> AUTO-006 verbatim.
    if r6.get("image_type") != IRRELEVANT:
        return r6.get("summary"), "AUTO-006", None

    # First-pass irrelevant -> prefer AUTO-007 when it succeeded.
    if r7 is not None and r7.get("status") == "success":
        return r7.get("summary"), "AUTO-007", None

    # AUTO-007 missing or technical failure -> fall back to AUTO-006.
    if r7 is None:
        return r6.get("summary"), "AUTO-006-fallback", "007_missing"
    return r6.get("summary"), "AUTO-006-fallback", "007_%s" % (r7.get("status") or "unknown")
