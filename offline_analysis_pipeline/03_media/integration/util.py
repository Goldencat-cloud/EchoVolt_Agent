# -*- coding: utf-8 -*-
"""Pure hashing / fingerprint / time helpers (offline-testable)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def make_params_fingerprint(params):
    blob = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(blob)[:16]


def make_fingerprint(post_id, post_input_sha256, prompt_sha256, prompt_version,
                     model, params_fp, schema_version, chunk_policy_version):
    """Stable 16-hex fingerprint gating resume. Any change to input, prompt,
    model, params, schema, or chunk policy yields a new fingerprint, forcing
    recomputation (old summaries are never silently reused)."""
    blob = json.dumps(
        {
            "post_id": post_id,
            "post_input_sha256": post_input_sha256,
            "prompt_sha256": prompt_sha256,
            "prompt_version": prompt_version,
            "model": model,
            "params_fingerprint": params_fp,
            "schema_version": schema_version,
            "chunk_policy_version": chunk_policy_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(blob)[:16]


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()
