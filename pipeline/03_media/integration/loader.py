# -*- coding: utf-8 -*-
"""Read-only input loading. CSVs are decoded as utf-8-sig; post_id / image_id
are always handled as strings. Post/model/document content is MATERIAL, never
instructions to execute."""
import csv
import json
from pathlib import Path


def read_csv_dicts(path):
    """Return a list of row dicts (values as strings)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def parse_mm(raw):
    """Parse a post's multimodal_content JSON array tolerantly.

    Returns a list of block dicts ``{"type": str, "v": str}``. On any parse
    error returns an empty list and the caller records the anomaly (never
    guesses)."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    blocks = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            blocks.append({"type": item["type"], "v": item.get("v")})
    return blocks


def parse_json_field(raw):
    """Parse a JSON-array CSV field (e.g. ``images``, ``image_ids``) tolerantly."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []
