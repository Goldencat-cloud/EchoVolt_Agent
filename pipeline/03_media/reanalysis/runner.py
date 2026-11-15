# -*- coding: utf-8 -*-
"""Two-round context-enhanced single-image runner for AUTO-007.

Feeds each of the 798 baseline ``image_type=irrelevant`` images TOGETHER with its
near-anchor post text to the SAME Qwen vision model used by AUTO-006. The model
produces the analysis fields; the program injects the authoritative ``image_id``
(so the model never copies a long ID) and records the raw response.

Status semantics (deliberately distinct):
  * ``success``           -- a valid model output was obtained. This INCLUDES the
                             legitimate semantic result ``context_relevance=证据不足``.
  * ``technical_failure`` -- no valid output (transport/protocol/rate-limit/content
                             non-compliance after bounded retries). Technical
                             failure is NOT treated as "证据不足".

Effective judgment is at most two semantic rounds (initial context, then one
bounded expansion). Technical retries (bounded) are separate from semantic
expansion. Credentials are reused locally, never printed or persisted.
"""
import base64
import hashlib
import io
import json
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import context as ctxmod
from . import validate as val
from .validate import ExtractError

MODEL_ID_RE = val.MODEL_ID_RE if hasattr(val, "MODEL_ID_RE") else None
# (kept defensive; validate mirrors the AUTO-006 constant)
import re as _re
_MODEL_ID_RE = _re.compile(r"[A-Za-z0-9_/.:\-]{1,100}")
_SYSTEM_PROMPT = val.SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def version_from_file(path):
    """Stable short version string derived from a file's content."""
    return sha256_bytes(Path(path).read_bytes())[:16]


def make_params_fingerprint(params):
    blob = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(blob)[:16]


def make_record_fingerprint(image_id, input_sha, prompt_version, schema_version,
                            params_fp, context_version):
    blob = json.dumps(
        {
            "image_id": image_id,
            "input_sha256": input_sha,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "params_fingerprint": params_fp,
            "context_version": context_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(blob)[:16]


# --------------------------------------------------------------------------- #
# Connection (mirrors AUTO-006 / tools/qwen_delegate.py credential handling)
# --------------------------------------------------------------------------- #
def load_connection(settings=config.SETTINGS, env_file=config.ENV_FILE):
    try:
        cfg = json.loads(Path(settings).read_text(encoding="utf-8-sig"))
        model = cfg["model"]["name"]
        provider = next(p for p in cfg["modelProviders"]["openai"] if p["id"] == model)
        base = provider["baseUrl"].rstrip("/")
        parts = urllib.parse.urlsplit(base)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ExtractError("invalid_endpoint")
        values = {}
        if Path(env_file).is_file():
            for line in Path(env_file).read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.removeprefix("export ").split("=", 1)
                    values[name.strip()] = value.strip().strip("\"'")
        key = os.environ.get(provider["envKey"]) or values.get(provider["envKey"])
        if not key:
            raise ExtractError("credential_unavailable")
        if not isinstance(model, str) or not _MODEL_ID_RE.fullmatch(model):
            raise ExtractError("invalid_model_id")
        return model, base, key
    except ExtractError:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        raise ExtractError("connection_config_unavailable") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def call_api(base, key, payload, timeout):
    """POST one chat-completion request. Returns (response_dict, status)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(config.MAX_RESPONSE_BYTES + 1)
            if len(raw) > config.MAX_RESPONSE_BYTES:
                raise ExtractError("api_response_too_large")
            return json.loads(raw), response.status
    except urllib.error.HTTPError as err:
        raise ExtractError("http_error", err.code) from None
    except ExtractError:
        raise
    except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError,
            json.JSONDecodeError) as err:
        raise ExtractError(_classify_transport(err)) from None


def _classify_transport(err):
    if isinstance(err, (socket.timeout, TimeoutError)):
        return "request_timeout"
    if isinstance(err, urllib.error.URLError):
        reason = getattr(err, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "request_timeout"
        return "connection_error"
    if isinstance(err, ConnectionError):
        return "connection_reset"
    return "transport_or_json_error"


# --------------------------------------------------------------------------- #
# Image preparation (identical to AUTO-006 baseline)
# --------------------------------------------------------------------------- #
def prepare_image(abs_path, max_edge):
    from PIL import Image

    raw = Path(abs_path).read_bytes()
    if len(raw) > config.MAX_IMAGE_BYTES:
        raise ExtractError("image_file_too_large")
    with Image.open(io.BytesIO(raw)) as image:
        original = image.size
        if image.width * image.height > config.MAX_PIXELS:
            raise ExtractError("image_pixel_limit_exceeded")
        image = image.convert("RGB")
        image.thumbnail((int(max_edge), int(max_edge)))
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=85)
        sent = image.size
    return {
        "jpeg_b64": base64.b64encode(stream.getvalue()).decode("ascii"),
        "orig_dims": [original[0], original[1]],
        "sent_dims": [sent[0], sent[1]],
        "jpeg_bytes": len(stream.getvalue()),
    }


# --------------------------------------------------------------------------- #
# Payload construction
# --------------------------------------------------------------------------- #
def _build_payload(ctx, jpeg_b64, context_block):
    # The FULL instruction template (field schema + principles + anti-injection
    # rules) MUST be sent; the model then sees the concrete post context appended.
    # Dropping the template makes the model invent arbitrary output schemas.
    user_text = ctx["template"].rstrip() + "\n\n[以下是本帖的实际局部原文]\n" + context_block
    return {
        "model": ctx["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + jpeg_b64}},
                ],
            },
        ],
        "max_tokens": ctx["params"]["max_tokens"],
        "temperature": ctx["params"]["temperature"],
        "chat_template_kwargs": {"enable_thinking": ctx["params"]["enable_thinking"]},
        "stream": False,
    }


# --------------------------------------------------------------------------- #
# One semantic round (bounded technical retries)
# --------------------------------------------------------------------------- #
def _run_round(ctx, payload, rng, log, round_tag):
    """Call the API with bounded technical retries.

    Returns ``(parsed_obj, round_info)`` on success, or ``(None, round_info)``
    with ``round_info['error_code']`` set on technical failure.
    """
    info = {
        "round": round_tag,
        "api_attempts": 0,
        "http_status": None,
        "elapsed_s": None,
        "finish_reason": None,
        "usage": None,
        "response_model": None,
        "raw_response": None,
        "raw_fence_stripped": False,
        "error_code": None,
    }
    last_error = "unknown"
    for attempt in range(1, ctx["max_retries"] + 1):
        info["api_attempts"] = attempt
        started = time.perf_counter()
        try:
            response, status = call_api(ctx["base"], ctx["key"], payload, ctx["params"]["timeout"])
            info["http_status"] = status
            info["elapsed_s"] = round(time.perf_counter() - started, 3)
            choice = response["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if not isinstance(content, str):
                raise ExtractError("invalid_completion_response")
            info["finish_reason"] = choice.get("finish_reason")
            info["usage"] = val.safe_usage(response.get("usage"))
            returned = response.get("model", "")
            if isinstance(returned, str) and _MODEL_ID_RE.fullmatch(returned) and ctx["key"] not in returned:
                info["response_model"] = returned
            info["raw_response"] = val.redact(content, ctx["key"])
            if message.get("tool_calls") or message.get("function_call"):
                raise ExtractError("unexpected_tool_call")
            if not content.strip():
                raise ExtractError("empty_response")
            if choice.get("finish_reason") != "stop":
                raise ExtractError("truncated_or_incomplete:%s" % choice.get("finish_reason"))
            normalized, fence_stripped = val.normalize_json_text(content)
            info["raw_fence_stripped"] = fence_stripped
            try:
                parsed = json.loads(normalized)
            except ValueError:
                raise ExtractError("invalid_json_response") from None
            ok, reason = val.validate_model_output(parsed, ctx["schema"])
            if not ok:
                raise ExtractError(reason)
            return parsed, info
        except ExtractError as err:
            last_error = err.code
            info["error_code"] = err.code
            if err.http_status:
                info["http_status"] = err.http_status
            if not val.is_retryable(err.code, err.http_status, attempt, ctx["max_retries"]):
                break
            transient = (err.http_status in config.TRANSIENT_HTTP
                         or err.code.split(":")[0] in config.TRANSPORT_CODES)
            delay = ((val.backoff_delay(attempt) if transient else config.CONTENT_RETRY_DELAY)
                     + rng.random() * 0.4)
            log("[%s] retry image=? attempt=%d/%d code=%s sleep=%.1fs"
                % (round_tag, attempt, ctx["max_retries"], err.code, delay))
            time.sleep(delay)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            last_error = "malformed_response_shape"
            info["error_code"] = last_error
            break
    info["error_code"] = last_error
    return None, info


# --------------------------------------------------------------------------- #
# Per-image processing (two semantic rounds max)
# --------------------------------------------------------------------------- #
def process_one(entry, ctx, log=lambda *_a: None):
    image_id = entry["image_id"]
    fp = make_record_fingerprint(
        image_id, entry["input_sha256"], ctx["prompt_version"],
        ctx["schema_version"], ctx["params_fingerprint"], ctx["context_version"],
    )
    started_at = datetime.now(timezone.utc).isoformat()
    record = {
        "image_id": image_id,
        "input_sha256": entry["input_sha256"],
        "relpath": entry.get("relpath"),
        "post_id": entry.get("post_id"),
        "url": entry.get("url"),
        "source_url": entry.get("source_url"),
        "model": ctx["model"],
        "params": ctx["params"],
        "params_fingerprint": ctx["params_fingerprint"],
        "prompt_version": ctx["prompt_version"],
        "schema_version": ctx["schema_version"],
        "context_version": ctx["context_version"],
        "record_fingerprint": fp,
        "status": "technical_failure",
        "rounds": [],
        "context": None,
        "parsed": None,
        "citation_valid": None,
        "citation_offending": None,
        "error_code": None,
        "started_at": started_at,
        "finished_at": None,
    }

    abs_path = str(Path(config.IMG_ROOT) / entry["relpath"])
    try:
        prep = prepare_image(abs_path, ctx["params"]["image_max_edge"])
    except ExtractError as err:
        record["error_code"] = err.code
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record
    except Exception:
        record["error_code"] = "image_prepare_failed"
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record
    record["orig_dims"] = prep["orig_dims"]
    record["sent_dims"] = prep["sent_dims"]
    record["jpeg_bytes"] = prep["jpeg_bytes"]

    rng = random.Random(fp)

    # --- Round 1: initial near-anchor context ------------------------------ #
    initial = ctxmod.select_initial_context(entry, budget=config.INITIAL_TEXT_TOKEN_BUDGET)
    r1_payload = _build_payload(ctx, prep["jpeg_b64"], ctxmod.render_context_for_prompt(initial))
    parsed1, r1info = _run_round(ctx, r1_payload, rng, log, "round1")
    record["rounds"].append(r1info)
    if parsed1 is None:
        record["error_code"] = r1info.get("error_code") or "round1_technical_failure"
        record["context"] = {"initial": initial, "expansion": None,
                             "applied": False, "blocked_reason": "round1_technical_failure"}
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record

    ca1 = parsed1.get("context_assessment") or {}
    requested = bool(ca1.get("requested_expansion"))
    expansion = None
    if requested:
        gap = ca1.get("expansion_gap")
        query = ca1.get("expansion_query")
        expansion = ctxmod.select_expansion(
            entry, initial, (query or gap or ""),
            new_budget=config.EXPANSION_NEW_TOKEN_BUDGET,
            total_budget=config.TOTAL_TEXT_TOKEN_BUDGET,
        )
        if expansion is None:
            # Model asked for more, but no relevant remaining same-post text fits.
            # Honest outcome: keep the round-1 judgment; the context is insufficient.
            record["parsed"] = val.inject_image_id(parsed1, image_id)
            record["status"] = "success"
            record["error_code"] = None
            blob = ctxmod.provided_text_blob(initial)
            ok, offending = val.check_citations(ca1.get("cited_fragments"), blob)
            record["citation_valid"] = ok
            record["citation_offending"] = offending
            record["context"] = {
                "initial": initial, "expansion": None,
                "applied": False,
                "requested": True,
                "blocked_reason": "no_relevant_remaining_text",
                "expansion_gap": gap, "expansion_query": query,
            }
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            return record

    # --- Round 2 (only if expansion available): combined context ----------- #
    if expansion is not None:
        combined = ctxmod.combined_bundle(initial, expansion)
        r2_payload = _build_payload(ctx, prep["jpeg_b64"], ctxmod.render_context_for_prompt(combined))
        parsed2, r2info = _run_round(ctx, r2_payload, rng, log, "round2")
        record["rounds"].append(r2info)
        if parsed2 is None:
            # Round 2 technically failed: we did not obtain a valid enhanced
            # judgment. Preserve round-1 for audit but mark technical_failure so
            # resume retries it (never fabricate 证据不足 from a transport fault).
            record["error_code"] = r2info.get("error_code") or "round2_technical_failure"
            record["round1_parsed_audit"] = val.inject_image_id(parsed1, image_id)
            record["context"] = {
                "initial": initial, "expansion": expansion,
                "applied": False, "requested": True,
                "blocked_reason": "round2_technical_failure",
                "expansion_gap": (ca1.get("expansion_gap")),
                "expansion_query": (ca1.get("expansion_query")),
            }
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            return record

        final = val.inject_image_id(parsed2, image_id)
        record["parsed"] = final
        record["status"] = "success"
        record["error_code"] = None
        blob = ctxmod.provided_text_blob(initial, expansion)
        ok, offending = val.check_citations((final.get("context_assessment") or {}).get("cited_fragments"), blob)
        record["citation_valid"] = ok
        record["citation_offending"] = offending
        record["context"] = {
            "initial": initial, "expansion": expansion,
            "applied": True, "requested": True,
            "expansion_gap": (ca1.get("expansion_gap")),
            "expansion_query": (ca1.get("expansion_query")),
        }
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        return record

    # --- Round 1 was conclusive (no expansion requested) -------------------- #
    final = val.inject_image_id(parsed1, image_id)
    record["parsed"] = final
    record["status"] = "success"
    record["error_code"] = None
    blob = ctxmod.provided_text_blob(initial)
    ok, offending = val.check_citations(ca1.get("cited_fragments"), blob)
    record["citation_valid"] = ok
    record["citation_offending"] = offending
    record["context"] = {"initial": initial, "expansion": None,
                         "applied": False, "requested": False}
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


# --------------------------------------------------------------------------- #
# Resume / batch orchestration
# --------------------------------------------------------------------------- #
def resume_skip_ids(existing_records, ctx, input_sha_by_id):
    """Skip only fingerprint-consistent successes (never overwrite old success)."""
    skip = set()
    for rec in existing_records:
        if rec.get("status") != "success":
            continue
        iid = rec.get("image_id")
        if not iid:
            continue
        if rec.get("prompt_version") != ctx["prompt_version"]:
            continue
        if rec.get("schema_version") != ctx["schema_version"]:
            continue
        if rec.get("params_fingerprint") != ctx["params_fingerprint"]:
            continue
        if rec.get("context_version") != ctx["context_version"]:
            continue
        if rec.get("input_sha256") != input_sha_by_id.get(iid):
            continue
        if rec.get("record_fingerprint") != make_record_fingerprint(
                iid, input_sha_by_id.get(iid), ctx["prompt_version"],
                ctx["schema_version"], ctx["params_fingerprint"], ctx["context_version"]):
            continue
        skip.add(iid)
    return skip


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def run_batch(entries, ctx, out_dir, resume=True, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    status_path = out_dir / "status.json"
    pid_path = out_dir / "batch.pid"
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    existing = []
    if resume and results_path.is_file():
        with open(results_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        existing.append(json.loads(line))
                    except ValueError:
                        pass
    input_sha_by_id = {e["image_id"]: e["input_sha256"] for e in entries}
    skip = resume_skip_ids(existing, ctx, input_sha_by_id) if resume else set()

    counters = {
        "total": len(entries),
        "skipped_resumed": len(skip),
        "success": 0,
        "failed": 0,
        "expanded": 0,
        "insufficient_evidence": 0,
        "pending": len(entries) - len(skip),
    }
    started_at = _utcnow_iso()
    log("[run] total=%d resume_skip=%d pending=%d concurrency=%d max_retries=%d model=%s"
        % (counters["total"], counters["skipped_resumed"], counters["pending"],
           ctx["concurrency"], ctx["max_retries"], ctx["model"]))

    lock = threading.Lock()

    def flush_status(state="running"):
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds()
        done_now = counters["success"] + counters["failed"]
        eta = None
        if done_now > 0 and counters["pending"] > 0:
            rate = done_now / max(elapsed, 1e-6)
            eta = int(counters["pending"] / rate) if rate > 0 else None
        snap = {
            "pid": os.getpid(),
            "started_at": started_at,
            "updated_at": _utcnow_iso(),
            "state": state,
            "concurrency": ctx["concurrency"],
            "max_retries": ctx["max_retries"],
            "model": ctx["model"],
            "params": ctx["params"],
            "params_fingerprint": ctx["params_fingerprint"],
            "prompt_version": ctx["prompt_version"],
            "schema_version": ctx["schema_version"],
            "context_version": ctx["context_version"],
            "counts": dict(counters),
            "eta_s": eta,
        }
        status_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(results_path, "a", encoding="utf-8") as out_fh:
        def handle_done(fut):
            rec = fut.result()
            with lock:
                if rec["status"] == "success":
                    counters["success"] += 1
                    ca = (rec.get("parsed") or {}).get("context_assessment") or {}
                    if ca.get("context_relevance") == "证据不足":
                        counters["insufficient_evidence"] += 1
                    if (rec.get("context") or {}).get("applied"):
                        counters["expanded"] += 1
                else:
                    counters["failed"] += 1
                counters["pending"] -= 1
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fh.flush()
                done_now = counters["success"] + counters["failed"]
                if done_now % 25 == 0:
                    flush_status()
                    log("[prog] success=%d failed=%d expanded=%d insufficient=%d pending=%d"
                        % (counters["success"], counters["failed"], counters["expanded"],
                           counters["insufficient_evidence"], counters["pending"]))

        pending_entries = [e for e in entries if e["image_id"] not in skip]
        flush_status()
        try:
            with ThreadPoolExecutor(max_workers=ctx["concurrency"]) as pool:
                futures = {pool.submit(process_one, e, ctx, log): e for e in pending_entries}
                for fut in as_completed(futures):
                    handle_done(fut)
        except KeyboardInterrupt:
            log("[run] interrupted; flushing status")
        finally:
            snap_state = "interrupted" if counters["pending"] > 0 else "completed"
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds()
            final = {
                "pid": os.getpid(),
                "started_at": started_at,
                "updated_at": _utcnow_iso(),
                "state": snap_state,
                "wall_clock_s": round(elapsed, 1),
                "concurrency": ctx["concurrency"],
                "max_retries": ctx["max_retries"],
                "model": ctx["model"],
                "params": ctx["params"],
                "params_fingerprint": ctx["params_fingerprint"],
                "prompt_version": ctx["prompt_version"],
                "schema_version": ctx["schema_version"],
                "context_version": ctx["context_version"],
                "counts": dict(counters),
            }
            status_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
            log("[run] done state=%s success=%d failed=%d expanded=%d insufficient=%d pending=%d"
                % (snap_state, counters["success"], counters["failed"], counters["expanded"],
                   counters["insufficient_evidence"], counters["pending"]))
    return counters


# --------------------------------------------------------------------------- #
# Result consolidation + reporting (checkpoint-independent, last-wins)
# --------------------------------------------------------------------------- #
def consolidate(results_path):
    """Return ``{image_id: record}`` (last record per id wins)."""
    by_id = {}
    rp = Path(results_path)
    if rp.is_file():
        with open(rp, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                by_id[rec.get("image_id")] = rec
    return by_id


def write_final(by_id, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results_final.jsonl", "w", encoding="utf-8") as fh:
        for iid in sorted(by_id):
            fh.write(json.dumps(by_id[iid], ensure_ascii=False) + "\n")
    return out_dir / "results_final.jsonl"


def summarize(by_id):
    success = [r for r in by_id.values() if r.get("status") == "success"]
    failed = [r for r in by_id.values() if r.get("status") != "success"]
    error_counts = {}
    for r in failed:
        code = (r.get("error_code") or "unknown").split(":")[0]
        error_counts[code] = error_counts.get(code, 0) + 1
    relevance_counts = {}
    confidences = []
    expanded = 0
    for r in success:
        p = r.get("parsed") or {}
        ca = p.get("context_assessment") or {}
        rel = ca.get("context_relevance")
        if rel:
            relevance_counts[rel] = relevance_counts.get(rel, 0) + 1
        c = p.get("confidence")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            confidences.append(c)
        if (r.get("context") or {}).get("applied"):
            expanded += 1
    return {
        "total": len(by_id),
        "success": len(success),
        "failed": len(failed),
        "error_counts": error_counts,
        "context_relevance_counts": relevance_counts,
        "expanded_count": expanded,
        "insufficient_evidence_count": relevance_counts.get("证据不足", 0),
        "confidence_mean": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "confidence_min": min(confidences) if confidences else None,
        "confidence_max": max(confidences) if confidences else None,
    }
