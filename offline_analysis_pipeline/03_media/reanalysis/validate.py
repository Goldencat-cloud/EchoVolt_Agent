# -*- coding: utf-8 -*-
"""Pure validation + retry-policy helpers (offline-testable, no network/files).

Mirrors the proven AUTO-006 helpers. The model does NOT emit ``image_id`` here
(the program injects it), so ``image_id_mismatch`` is not a retryable code.
"""
import re

import jsonschema

from . import config

SECRET_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
MODEL_ID_RE = re.compile(r"[A-Za-z0-9_/.:\-]{1,100}")
SYSTEM_PROMPT = (
    "你是一名严谨的多模态理解模型。严格按照用户指令只输出一个合法的 JSON 对象，"
    "不输出任何额外文字、解释或 Markdown 围栏。"
)
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


def is_transient(http_status):
    return http_status in config.TRANSIENT_HTTP


def backoff_delay(attempt):
    """Exponential backoff with a hard cap (seconds). Caller adds jitter."""
    return min(config.BACKOFF_CAP, config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** max(0, attempt - 1)))


def is_retryable(err_code, http_status, attempt, max_retries):
    """Bounded retry: transport/transient errors or sporadic content non-compliance
    retry up to max_retries; deterministic failures do not."""
    if attempt >= max_retries:
        return False
    base = (err_code or "").split(":")[0]
    transient = (http_status in config.TRANSIENT_HTTP) or (base in config.TRANSPORT_CODES)
    return transient or (base in config.RETRYABLE_CONTENT)


def normalize_json_text(content):
    """Strip a single outer Markdown code fence if present; never guess content.

    Returns ``(normalized_text, fence_stripped)``. The interior is still strictly
    parsed and schema-validated downstream.
    """
    s = content.strip()
    if s.startswith(_FENCE):
        idx = s.find("\n")
        if idx != -1:
            rest = s[idx + 1:]
            close = rest.rfind(_FENCE)
            if close != -1:
                return rest[:close].strip(), True
    return s, False


def validate_model_output(obj, schema):
    """Strictly validate the model's analysis object. Returns (ok, reason)."""
    if not isinstance(obj, dict):
        return False, "not_an_object"
    try:
        jsonschema.validate(instance=obj, schema=schema)
    except jsonschema.ValidationError as exc:
        return False, "schema_mismatch:%s" % exc.message
    except Exception:
        return False, "schema_error"
    return True, None


def check_citations(cited_fragments, provided_blob):
    """Every cited fragment must be a substring of the provided text.

    Returns ``(ok, offending)``. Empty/blank citations are fine. This is a
    quality flag (not a hard failure): the analysis is kept but flagged.
    """
    if not isinstance(cited_fragments, list):
        return False, ["cited_fragments_not_list"]
    blob = provided_blob or ""
    offending = []
    for c in cited_fragments:
        if not isinstance(c, str):
            offending.append(repr(c))
            continue
        c2 = c.strip()
        if not c2:
            continue
        if c2 not in blob:
            offending.append(c2[:80])
    return (len(offending) == 0), offending


def inject_image_id(model_obj, image_id):
    """Attach the authoritative image_id to the model's analysis object."""
    out = dict(model_obj)
    out["image_id"] = image_id
    return out
