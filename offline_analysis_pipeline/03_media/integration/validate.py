# -*- coding: utf-8 -*-
"""Validation + retry-policy helpers (offline-testable, no network/files).

Terminal states for a processed post:
  * ``empty_response``         -- model returned no usable content.
  * ``invalid_json_response`` -- not parseable / not conforming to the schema.
  * ``truncated_or_incomplete``-- output cut off (finish_reason != stop).
  * ``invalid_source_reference``-- cites a text_block_id/image_id not present in
                                   the actual input, or cites image_id=null.
  * ``api_or_transport_failure``-- HTTP/transport/network error.

Citation legality is a HARD gate here (unlike the soft flag in AUTO-007): a
summary that cites ids the post does not contain is not trusted as a success.
"""
import re

import jsonschema

from . import config

SECRET_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
MODEL_ID_RE = re.compile(r"[A-Za-z0-9_/.:\-]{1,100}")
_FENCE = "```"


class ExtractError(Exception):
    """Carries a machine-readable code and optional HTTP status."""

    def __init__(self, code, http_status=None):
        self.code = code
        self.http_status = http_status
        super().__init__(code)


def redact(text, key):
    """Remove the credential and any echoed secret-looking tokens from text."""
    if not text:
        return text
    out = text
    if key:
        out = out.replace(key, "***")
    out = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "***", out)
    out = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}", r"\1***", out)
    return out


def safe_usage(value):
    """Normalize a usage object; missing fields are simply absent (=> unknown)."""
    if not isinstance(value, dict):
        return {}
    result = {
        k: value[k]
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(value.get(k), int) and not isinstance(value.get(k), bool)
    }
    for section, fields in {
        "completion_tokens_details": ("reasoning_tokens",),
        "prompt_tokens_details": ("cached_tokens",),
    }.items():
        details = value.get(section, {})
        if isinstance(details, dict):
            result[section] = {
                k: details[k]
                for k in fields
                if isinstance(details.get(k), int) and not isinstance(details.get(k), bool)
            }
    return result


def backoff_delay(attempt):
    return min(config.BACKOFF_CAP,
               config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** max(0, attempt - 1)))


def is_retryable(err_code, http_status, attempt, max_retries):
    if attempt >= max_retries:
        return False
    base = (err_code or "").split(":")[0]
    transient = (http_status in config.TRANSIENT_HTTP) or (base in config.TRANSPORT_CODES)
    return transient or (base in config.RETRYABLE_CONTENT)


def normalize_json_text(content):
    """Strip a single outer Markdown code fence if present. Returns (text, stripped)."""
    s = content.strip()
    if s.startswith(_FENCE):
        idx = s.find("\n")
        if idx != -1:
            rest = s[idx + 1:]
            close = rest.rfind(_FENCE)
            if close != -1:
                return rest[:close].strip(), True
    return s, False


def validate_schema(obj, schema):
    """Validate against the result schema. Returns (ok, reason)."""
    if not isinstance(obj, dict):
        return False, "not_an_object"
    try:
        jsonschema.validate(instance=obj, schema=schema)
    except jsonschema.ValidationError as exc:
        return False, "schema_mismatch:%s" % exc.message
    except Exception:
        return False, "schema_error"
    return True, None


def check_citations(obj, valid_text_ids, valid_image_ids):
    """Every cited id must exist in the ACTUAL input. Returns (ok, offending).

    ``valid_text_ids`` / ``valid_image_ids`` are the sets of ids present in the
    post's sequence (null image_ids are never valid). A cited ``image_id`` that
    is ``None``/``"null"``/absent, or any id outside the valid sets, is illegal.
    """
    offending = []

    def scan(items):
        if not isinstance(items, list):
            return
        for kp in items:
            if not isinstance(kp, dict):
                continue
            for tid in kp.get("text_block_ids") or []:
                if not isinstance(tid, str) or tid not in valid_text_ids:
                    offending.append("text:%r" % (tid,))
            for iid in kp.get("image_ids") or []:
                if not isinstance(iid, str) or iid == "null" or iid not in valid_image_ids:
                    offending.append("image:%r" % (iid,))

    scan(obj.get("key_points"))
    scan(obj.get("uncertainties"))
    return (len(offending) == 0), offending
