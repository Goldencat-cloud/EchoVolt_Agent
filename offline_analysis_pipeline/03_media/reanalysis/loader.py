# -*- coding: utf-8 -*-
"""Load the read-only inputs and build the 798 before-index + post store.

Enforces the data contract: every before image must join 003 by string image_id,
its post must exist in 002, and its url must anchor UNIVOCALLY in the post's
multimodal_content. Any violation raises ContractViolation.
"""
import csv
import json

from . import config


class ContractViolation(Exception):
    def __init__(self, sample, total):
        self.sample = sample
        self.total = total
        super().__init__("data contract violated: %d problem(s); sample=%r" % (total, sample))


def load_baseline_before(path=config.BASELINE):
    """Return ``{image_id: record}`` for image_type=irrelevant AND status=success."""
    before = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            parsed = rec.get("parsed") or {}
            if parsed.get("image_type") == "irrelevant" and rec.get("status") == "success":
                before[rec["image_id"]] = rec
    return before


def load_csv003(path=config.CSV003):
    m = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            m[row["image_id"]] = row
    return m


def load_posts(path=config.CSV002):
    posts = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = row.get("post_id")
            if not pid:
                continue
            try:
                mm = json.loads(row.get("multimodal_content") or "[]")
            except ValueError:
                mm = []
            posts[pid] = {
                "title": row.get("title") or "",
                "source_url": row.get("source_url") or "",
                "mm": mm,
            }
    return posts


def find_anchor(mm, url):
    """Indices of img entries whose v equals ``url`` (exact string match)."""
    return [
        i for i, e in enumerate(mm)
        if isinstance(e, dict) and e.get("type") == "img" and e.get("v") == url
    ]


def build_before_index(before=None, m003=None, posts=None):
    """Join baseline before-records to posts; require a UNIQUE url anchor each.

    Returns ``{image_id: BeforeEntry}``. Raises ContractViolation on any
    join-miss / missing-post / non-unique-anchor.
    """
    if before is None:
        before = load_baseline_before()
    if m003 is None:
        m003 = load_csv003()
    if posts is None:
        posts = load_posts()

    index = {}
    problems = []
    for iid, rec in before.items():
        row = m003.get(iid)
        if not row:
            problems.append(("join_miss", iid))
            continue
        pid = row["post_id"]
        url = row["url"]
        po = posts.get(pid)
        if not po:
            problems.append(("post_missing", iid))
            continue
        idxs = find_anchor(po["mm"], url)
        if len(idxs) != 1:
            problems.append(("anchor_not_unique:%d" % len(idxs), iid))
            continue
        index[iid] = {
            "image_id": iid,
            "input_sha256": rec.get("input_sha256"),
            "relpath": rec.get("relpath"),
            "before_parsed": rec.get("parsed"),
            "post_id": pid,
            "url": url,
            "source_url": po["source_url"],
            "title": po["title"],
            "mm": po["mm"],
            "anchor_idx": idxs[0],
        }
    if problems:
        raise ContractViolation(problems[:20], len(problems))
    return index
