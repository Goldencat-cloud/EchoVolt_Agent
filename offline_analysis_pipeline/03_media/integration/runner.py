# -*- coding: utf-8 -*-
"""Phase 2 (online): per-post full-text summary runner.

Text-only Qwen chat calls (no vision). One call per post by default; a post whose
estimated input exceeds the budget is chunked in order and synthesized. Bounded
technical retries, controlled concurrency, per-post checkpoint (append-only
results.jsonl), per-request raw/status/params/elapsed/usage/finish_reason.
Credentials are reused locally, never printed or persisted.
"""
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

from . import chunk
from . import config
from . import prompt as promptmod
from . import util
from . import validate as val
from .validate import ExtractError

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


# --------------------------------------------------------------------------- #
# Connection (mirrors AUTO-006/007 credential handling)
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
        if not isinstance(model, str) or not val.MODEL_ID_RE.fullmatch(model):
            raise ExtractError("invalid_model_id")
        return model, base, key
    except ExtractError:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        raise ExtractError("connection_config_unavailable") from None


def load_model_name(settings=config.SETTINGS):
    """Read only the configured model name from settings (no network, no key).

    Used by the offline build phase so the fingerprint's model component matches
    the online run (which obtains the same value via ``load_connection``)."""
    cfg = json.loads(Path(settings).read_text(encoding="utf-8-sig"))
    return cfg["model"]["name"]


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
# State classification
# --------------------------------------------------------------------------- #
def classify_state(error_code):
    if not error_code:
        return None
    base = error_code.split(":")[0]
    if base == "empty_response":
        return "empty_response"
    if base in ("invalid_json_response", "not_an_object", "schema_mismatch", "schema_error"):
        return "invalid_json_response"
    if base == "truncated_or_incomplete":
        return "truncated_or_incomplete"
    if base == "invalid_source_reference":
        return "invalid_source_reference"
    return "api_or_transport_failure"


def citation_universe(integration, plan):
    """Accepted citation ids for a post: original sequence ids plus any chunk
    sub-block ids introduced by splitting. Null image_ids are never valid."""
    seq = integration["sequence"]
    text_ids = {b["text_block_id"] for b in seq if b.get("type") == "text"}
    image_ids = {b["image_id"] for b in seq
                 if b.get("type") == "image" and b.get("image_id") is not None}
    if plan:
        for info in plan.get("split_parents", {}).values():
            text_ids.update(info.get("sub_ids", []))
    return text_ids, image_ids


# --------------------------------------------------------------------------- #
# One API call with bounded technical retries
# --------------------------------------------------------------------------- #
def run_call(ctx, payload, rng, log, tag, valid_text_ids, valid_image_ids):
    """Returns ``(parsed_obj, info)``; ``parsed_obj`` is None on failure with
    ``info['error_code']`` set. Every attempt's transport/content outcome is
    reflected in the returned ``info``."""
    info = {
        "tag": tag,
        "api_attempts": 0,
        "http_status": None,
        "elapsed_s": None,
        "finish_reason": None,
        "usage": None,
        "response_model": None,
        "raw_response": None,
        "raw_fence_stripped": False,
        "citation_offending": None,
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
            if isinstance(returned, str) and val.MODEL_ID_RE.fullmatch(returned) \
                    and ctx["key"] not in returned:
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
            ok, reason = val.validate_schema(parsed, ctx["schema"])
            if not ok:
                raise ExtractError(reason)
            cit_ok, offending = val.check_citations(parsed, valid_text_ids, valid_image_ids)
            if not cit_ok:
                info["citation_offending"] = offending
                raise ExtractError("invalid_source_reference:%s" % ";".join(offending[:5]))
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
            log("[%s] retry attempt=%d/%d code=%s sleep=%.1fs"
                % (tag, attempt, ctx["max_retries"], err.code, delay))
            time.sleep(delay)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            last_error = "malformed_response_shape"
            info["error_code"] = last_error
            break
    info["error_code"] = last_error
    return None, info


# --------------------------------------------------------------------------- #
# Per-post processing
# --------------------------------------------------------------------------- #
def _render_synthesis_user(chunk_summaries):
    return "[分段摘要合集]\n" + json.dumps(
        {"segments": chunk_summaries}, ensure_ascii=False)


def process_one(integration, ctx, log=lambda *_a: None):
    post_id = integration["post_id"]
    fp = integration["fingerprint"]
    started_at = util.utcnow_iso()
    record = {
        "post_id": post_id,
        "source_url": integration.get("source_url"),
        "title": integration.get("title"),
        "model": ctx["model"],
        "params": ctx["params"],
        "params_fingerprint": ctx["params_fingerprint"],
        "prompt_version": ctx["prompt_version"],
        "prompt_sha256": ctx["prompt_sha256"],
        "schema_version": ctx["schema_version"],
        "chunk_policy_version": ctx["chunk_policy_version"],
        "post_input_sha256": integration["post_input_sha256"],
        "fingerprint": fp,
        "status": "api_or_transport_failure",
        "chunked": False,
        "num_chunks": 1,
        "calls": [],
        "parsed": None,
        "citation_offending": None,
        "error_code": None,
        "started_at": started_at,
        "finished_at": None,
    }
    rng = random.Random(fp)
    calls = []

    def finish(status=None):
        record["calls"] = calls
        record["finished_at"] = util.utcnow_iso()
        if status is not None:
            record["status"] = status
        return record

    if chunk.needs_chunking(integration["est_input_tokens"], ctx["budget"]):
        plan = chunk.plan_chunks(integration["sequence"], integration["title"],
                                 ctx["prompt_text"], ctx["budget"])
        record["chunked"] = True
        record["num_chunks"] = plan["num_chunks"]
        record["chunk_plan"] = {
            "num_chunks": plan["num_chunks"],
            "coverage_ok": plan["coverage_ok"],
            "method": plan["method"],
            "split_parents": {k: v["sub_ids"] for k, v in plan["split_parents"].items()},
        }
        valid_text, valid_image = citation_universe(integration, plan)
        chunk_summaries = []
        for ch in plan["chunks"]:
            ch_text = {b["text_block_id"] for b in ch["blocks"] if b["type"] == "text"}
            ch_img = {b["image_id"] for b in ch["blocks"]
                      if b["type"] == "image" and b["image_id"] is not None}
            payload = promptmod.build_payload(ctx["prompt_text"], ch["user_content"],
                                              ctx["model"], ctx["params"])
            obj, info = run_call(ctx, payload, rng, log,
                                 "chunk%d/%d" % (ch["k"], ch["n"]), ch_text, ch_img)
            calls.append(info)
            if obj is None:
                return finish(classify_state(info["error_code"]) or "api_or_transport_failure")
            chunk_summaries.append(obj)
        payload = promptmod.build_payload(ctx["synth_text"],
                                          _render_synthesis_user(chunk_summaries),
                                          ctx["model"], ctx["params"])
        obj, info = run_call(ctx, payload, rng, log, "synthesis", valid_text, valid_image)
        calls.append(info)
        if obj is None:
            record["citation_offending"] = info.get("citation_offending")
            return finish(classify_state(info["error_code"]) or "api_or_transport_failure")
        record["parsed"] = obj
        record["error_code"] = None
        return finish("success")

    # --- single-call path (default) ---------------------------------------- #
    valid_text, valid_image = citation_universe(integration, None)
    payload = promptmod.build_payload(ctx["prompt_text"],
                                      promptmod.render_user(integration["post_input_json"]),
                                      ctx["model"], ctx["params"])
    obj, info = run_call(ctx, payload, rng, log, "single", valid_text, valid_image)
    calls.append(info)
    if obj is None:
        record["citation_offending"] = info.get("citation_offending")
        return finish(classify_state(info["error_code"]) or "api_or_transport_failure")
    record["parsed"] = obj
    record["error_code"] = None
    return finish("success")


# --------------------------------------------------------------------------- #
# Resume / batch orchestration
# --------------------------------------------------------------------------- #
def resume_skip(existing_records, integrations):
    """Skip only fingerprint-matching successes (never overwrite an old success)."""
    integ_fp = {integ["post_id"]: integ["fingerprint"] for integ in integrations}
    skip = set()
    for rec in existing_records:
        if rec.get("status") != "success":
            continue
        pid = rec.get("post_id")
        if not pid or pid not in integ_fp:
            continue
        if rec.get("fingerprint") != integ_fp[pid]:
            continue
        skip.add(pid)
    return skip


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def run_batch(integrations, ctx, out_dir, resume=True, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    status_path = out_dir / "status.json"
    pid_path = out_dir / "batch.pid"
    requests_path = out_dir / "requests_log.jsonl"
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
    skip = resume_skip(existing, integrations) if resume else set()

    state_counts = {
        "empty_response": 0, "invalid_json_response": 0, "truncated_or_incomplete": 0,
        "invalid_source_reference": 0, "api_or_transport_failure": 0,
    }
    counters = {
        "total": len(integrations),
        "skipped_resumed": len(skip),
        "success": 0,
        "failed": 0,
        "chunked": 0,
        "pending": len(integrations) - len(skip),
        "states": dict(state_counts),
    }
    started_at = _utcnow_iso()
    log("[run] total=%d resume_skip=%d pending=%d concurrency=%d max_retries=%d model=%s"
        % (counters["total"], counters["skipped_resumed"], counters["pending"],
           ctx["concurrency"], ctx["max_retries"], ctx["model"]))

    lock = threading.Lock()
    req_seq = [0]

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
            "prompt_sha256": ctx["prompt_sha256"],
            "schema_version": ctx["schema_version"],
            "chunk_policy_version": ctx["chunk_policy_version"],
            "counts": counters,
            "eta_s": eta,
        }
        status_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_request(record, info):
        with lock:
            req_seq[0] += 1
            entry = {
                "req_seq": req_seq[0],
                "post_id": record.get("post_id"),
                "tag": info.get("tag"),
                "http_status": info.get("http_status"),
                "params": ctx["params"],
                "elapsed_s": info.get("elapsed_s"),
                "usage": info.get("usage"),
                "finish_reason": info.get("finish_reason"),
                "response_model": info.get("response_model"),
                "api_attempts": info.get("api_attempts"),
                "error_code": info.get("error_code"),
                "raw_response": info.get("raw_response"),
            }
            requests_path.open("a", encoding="utf-8").write(
                json.dumps(entry, ensure_ascii=False) + "\n")

    with open(results_path, "a", encoding="utf-8") as out_fh:
        def handle_done(fut):
            rec = fut.result()
            with lock:
                for info in rec.get("calls", []):
                    log_request(rec, info)
                if rec["status"] == "success":
                    counters["success"] += 1
                    if rec.get("chunked"):
                        counters["chunked"] += 1
                else:
                    counters["failed"] += 1
                    st = rec["status"]
                    if st in counters["states"]:
                        counters["states"][st] += 1
                counters["pending"] -= 1
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fh.flush()
                done_now = counters["success"] + counters["failed"]
                if done_now % 50 == 0:
                    flush_status()
                    log("[prog] success=%d failed=%d pending=%d"
                        % (counters["success"], counters["failed"], counters["pending"]))

        pending = [integ for integ in integrations if integ["post_id"] not in skip]
        flush_status()
        try:
            with ThreadPoolExecutor(max_workers=ctx["concurrency"]) as pool:
                futures = {pool.submit(process_one, integ, ctx, log): integ
                           for integ in pending}
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
                "prompt_sha256": ctx["prompt_sha256"],
                "schema_version": ctx["schema_version"],
                "chunk_policy_version": ctx["chunk_policy_version"],
                "counts": counters,
            }
            status_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
            log("[run] done state=%s success=%d failed=%d chunked=%d pending=%d"
                % (snap_state, counters["success"], counters["failed"],
                   counters["chunked"], counters["pending"]))
    return counters


# --------------------------------------------------------------------------- #
# Consolidation (checkpoint-independent, last-wins per post)
# --------------------------------------------------------------------------- #
def consolidate(results_path):
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
                by_id[rec.get("post_id")] = rec
    return by_id


def write_final(by_id, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results_final.jsonl", "w", encoding="utf-8") as fh:
        for pid in sorted(by_id):
            fh.write(json.dumps(by_id[pid], ensure_ascii=False) + "\n")
    return out_dir / "results_final.jsonl"
