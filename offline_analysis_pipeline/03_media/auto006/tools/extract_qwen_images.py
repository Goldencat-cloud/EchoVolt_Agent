"""Full-corpus single-image understanding via the configured Qwen vision API.

AUTO-006 batch tool. It builds a stable manifest over ``images/``, calls the Qwen
vision API one image at a time with a fixed Chinese instruction, strictly validates
the single-image JSON (schema + image_id consistency), and writes auditable,
resumable per-image records. Concurrency and retries are bounded; credentials are
reused locally and never printed or persisted; the proxy bypass is process-local.

This tool is deliberately independent of ``tools/qwen_delegate.py`` (which is a
single bounded subtask dispatcher) and does not extend that tool's scope.
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import random
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SETTINGS = ROOT / "local-config/settings.json"
DEFAULT_ENV_FILE = ROOT / "local-config/.env"
DEFAULT_IMAGES_ROOT = ROOT / "images"
DEFAULT_OUTPUT_DIR = ROOT / "generated/auto006"
CHANGE_ID = "auto-006-qwen-full-image-extraction"
DEFAULT_CHANGE_DIR = ROOT / "openspec" / "changes" / CHANGE_ID
DEFAULT_PROMPT_FILE = DEFAULT_CHANGE_DIR / "prompts" / "full_extraction_prompt.txt"
DEFAULT_SCHEMA_FILE = DEFAULT_CHANGE_DIR / "schema" / "single_image_result.schema.json"
MANIFEST_CSV_DEFAULT = ROOT / "collaboration/data/003_A4_图片下载_图片清单.csv"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MAX_PIXELS = 25_000_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 2_097_152

TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
BACKOFF_BASE = 1.5
BACKOFF_FACTOR = 2.0
BACKOFF_CAP = 20.0
TRANSPORT_CODES = {"request_timeout", "connection_error", "connection_reset", "transport_or_json_error"}
# Sporadic model non-compliance (dropped quote, omitted image_id, stray prose) is
# often stochastic even at temperature 0; a bounded re-roll recovers most of it.
RETRYABLE_CONTENT = {
    "invalid_json_response",
    "schema_mismatch",
    "image_id_mismatch",
    "empty_response",
    "truncated_or_incomplete",
    "not_an_object",
}
CONTENT_RETRY_DELAY = 0.6

SECRET_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
MODEL_ID_RE = re.compile(r"[A-Za-z0-9_/.:\-]{1,100}")

SYSTEM_PROMPT = "你是一名严谨的图片理解模型。严格按照用户指令只输出合法的 JSON，不输出任何额外文字、解释或 Markdown 围栏。"


class ExtractError(Exception):
    """Carries a machine-readable code and optional HTTP status."""

    def __init__(self, code, http_status=None):
        self.code = code
        self.http_status = http_status
        super().__init__(code)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without network/filesystem)
# --------------------------------------------------------------------------- #
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def derive_image_id(stem, relpath, csv_ids, used):
    """Pick a stable image_id: prefer the manifest value, else derive from relpath.

    Guarantees uniqueness against ``used``; on collision appends a numeric suffix.
    Returns ``(image_id, id_source)``.
    """
    if stem in csv_ids:
        candidate, source = stem, "manifest_join"
    else:
        posix = relpath.replace("\\", "/")
        base = PurePosixPath(posix).with_suffix("").as_posix()
        candidate = re.sub(r"[^A-Za-z0-9._\-]", "_", base)
        source = "relpath_derived"
    image_id = candidate
    n = 1
    while image_id in used:
        n += 1
        image_id = "%s_%d" % (candidate, n)
    return image_id, source


def compose_prompt(template, image_id):
    return "待分析图片ID：%s\n\n%s" % (image_id, template)


def make_params_fingerprint(params):
    blob = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(blob)[:16]


def make_record_fingerprint(image_id, input_sha, prompt_version, schema_version, params_fp):
    blob = json.dumps(
        {
            "image_id": image_id,
            "input_sha256": input_sha,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "params_fingerprint": params_fp,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(blob)[:16]


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


def is_transient(http_status):
    return http_status in TRANSIENT_HTTP


def backoff_delay(attempt):
    """Exponential backoff with a hard cap (seconds). Caller adds jitter."""
    return min(BACKOFF_CAP, BACKOFF_BASE * (BACKOFF_FACTOR ** max(0, attempt - 1)))


def is_retryable(err_code, http_status, attempt, max_retries):
    """Bounded retry decision: transport/transient errors, or sporadic content
    non-compliance, retry up to max_retries; deterministic failures do not."""
    if attempt >= max_retries:
        return False
    base = (err_code or "").split(":")[0]
    transient = http_status in TRANSIENT_HTTP or base in TRANSPORT_CODES
    return transient or base in RETRYABLE_CONTENT


_FENCE = "```"


def normalize_json_text(content):
    """Strip a single outer Markdown code fence if present; never guess content.

    The model is instructed to emit bare JSON but frequently wraps it in a
    ```` ```json ... ``` ```` presentation fence. Removing that one well-known
    wrapper is a bounded deserialization step: the interior is still strictly
    parsed, schema-validated and image_id-checked downstream. Returns
    ``(normalized_text, fence_stripped)``.
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


def validate_parsed(obj, schema, image_id):
    """Strictly validate a parsed single-image result. Returns (ok, reason)."""
    if not isinstance(obj, dict):
        return False, "not_an_object"
    try:
        import jsonschema

        jsonschema.validate(instance=obj, schema=schema)
    except ImportError:
        return False, "jsonschema_dependency_missing"
    except jsonschema.ValidationError as exc:
        return False, "schema_mismatch:%s" % exc.message
    except Exception:
        return False, "schema_error"
    if obj.get("image_id") != image_id:
        return False, "image_id_mismatch"
    return True, None


def resume_skip_ids(existing_records, ctx):
    """Return image_ids to skip on resume: fingerprint-consistent successes only."""
    skip = set()
    for rec in existing_records:
        if rec.get("status") != "success":
            continue
        if rec.get("prompt_version") != ctx["prompt_version"]:
            continue
        if rec.get("schema_version") != ctx["schema_version"]:
            continue
        if rec.get("params_fingerprint") != ctx["params_fingerprint"]:
            continue
        iid = rec.get("image_id")
        if iid and rec.get("input_sha256") == ctx["input_sha_by_id"].get(iid):
            skip.add(iid)
    return skip


# --------------------------------------------------------------------------- #
# Connection (mirrors tools/qwen_delegate.py credential handling)
# --------------------------------------------------------------------------- #
def load_connection(settings, env_file):
    try:
        config = json.loads(Path(settings).read_text(encoding="utf-8-sig"))
        model = config["model"]["name"]
        provider = next(p for p in config["modelProviders"]["openai"] if p["id"] == model)
        base = provider["baseUrl"].rstrip("/")
        parts = urllib.parse.urlsplit(base)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
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
        if not isinstance(model, str) or not MODEL_ID_RE.fullmatch(model):
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
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ExtractError("api_response_too_large")
            return json.loads(raw), response.status
    except urllib.error.HTTPError as err:
        raise ExtractError("http_error", err.code) from None
    except ExtractError:
        raise
    except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError, json.JSONDecodeError) as err:
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
                k: details[k] for k in fields if isinstance(details.get(k), int) and not isinstance(details.get(k), bool)
            }
    return result


# --------------------------------------------------------------------------- #
# Image preparation
# --------------------------------------------------------------------------- #
def prepare_image(abs_path, max_edge):
    """Decode, downscale and re-encode one image to JPEG. Returns a dict or raises."""
    from PIL import Image

    raw = Path(abs_path).read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ExtractError("image_file_too_large")
    with Image.open(io.BytesIO(raw)) as image:
        original = image.size
        if image.width * image.height > MAX_PIXELS:
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


def probe_header(abs_path):
    """Cheap format/dimension probe for the manifest (header only)."""
    from PIL import Image

    try:
        with Image.open(abs_path) as image:
            return True, image.format, [image.width, image.height]
    except Exception:
        return False, None, None


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def load_manifest_csv(csv_path):
    ids = set()
    if csv_path and Path(csv_path).is_file():
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                iid = (row.get("image_id") or "").strip()
                if iid:
                    ids.add(iid)
    return ids


def build_manifest(images_root, csv_path, out_path, log=print):
    images_root = Path(images_root)
    if not images_root.is_dir():
        raise ExtractError("images_root_missing")
    csv_ids = load_manifest_csv(csv_path)
    used = set()
    total = 0
    by_ext = {}
    dup_groups = {}
    undecodable = 0
    records = []
    for dirpath, _dirnames, filenames in os.walk(images_root):
        for name in sorted(filenames):
            ext = Path(name).suffix.lower()
            if ext not in IMAGE_EXTS:
                continue
            total += 1
            by_ext[ext] = by_ext.get(ext, 0) + 1
            abs_path = Path(dirpath) / name
            relpath = abs_path.relative_to(images_root).as_posix()
            stem = Path(name).stem
            digest = sha256_file(abs_path)
            size = abs_path.stat().st_size
            image_id, id_source = derive_image_id(stem, relpath, csv_ids, used)
            used.add(image_id)
            decodable, fmt, dims = probe_header(str(abs_path))
            if not decodable:
                undecodable += 1
            dup_groups.setdefault(digest, []).append(image_id)
            records.append(
                {
                    "image_id": image_id,
                    "id_source": id_source,
                    "relpath": relpath,
                    "abs_path": str(abs_path),
                    "sha256": digest,
                    "size_bytes": size,
                    "ext": ext,
                    "format": fmt,
                    "dims": dims,
                    "decodable": decodable,
                    "dup_group": digest,
                }
            )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    dup_dup = sum(1 for v in dup_groups.values() if len(v) > 1)
    dup_members = sum(len(v) for v in dup_groups.values() if len(v) > 1)
    summary = {
        "total_files": total,
        "by_ext": by_ext,
        "unique_content": len(dup_groups),
        "duplicate_groups_gt1": dup_dup,
        "duplicate_member_files": dup_members,
        "undecodable_or_unsupported": undecodable,
        "valid_images": total - undecodable,
        "manifest_path": str(out_path),
        "csv_image_ids": len(csv_ids),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    log("[manifest] total=%d valid=%d undecodable=%d dup_groups=%d dup_members=%d" % (
        total, total - undecodable, undecodable, dup_dup, dup_members))
    return summary, records


# --------------------------------------------------------------------------- #
# Per-image processing
# --------------------------------------------------------------------------- #
def process_one(entry, ctx, log=lambda *_a: None):
    """Run one image end-to-end with bounded retries. Returns a record dict."""
    image_id = entry["image_id"]
    fp = make_record_fingerprint(
        image_id, entry["sha256"], ctx["prompt_version"], ctx["schema_version"], ctx["params_fingerprint"]
    )
    record = {
        "image_id": image_id,
        "id_source": entry.get("id_source"),
        "relpath": entry.get("relpath"),
        "input_sha256": entry["sha256"],
        "size_bytes": entry.get("size_bytes"),
        "ext": entry.get("ext"),
        "format": entry.get("format"),
        "model": ctx["model"],
        "params": ctx["params"],
        "prompt_version": ctx["prompt_version"],
        "schema_version": ctx["schema_version"],
        "params_fingerprint": ctx["params_fingerprint"],
        "record_fingerprint": fp,
        "status": "failed",
        "api_attempts": 0,
        "raw_response": None,
        "parsed": None,
        "raw_fence_stripped": False,
        "error_code": None,
        "finished_at": None,
    }
    try:
        prep = prepare_image(entry["abs_path"], ctx["params"]["image_max_edge"])
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

    prompt = compose_prompt(ctx["template"], image_id)
    payload = {
        "model": ctx["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + prep["jpeg_b64"]}},
                ],
            },
        ],
        "max_tokens": ctx["params"]["max_tokens"],
        "temperature": ctx["params"]["temperature"],
        "chat_template_kwargs": {"enable_thinking": ctx["params"]["enable_thinking"]},
        "stream": False,
    }

    rng = random.Random(fp)
    last_error = "unknown"
    for attempt in range(1, ctx["max_retries"] + 1):
        record["api_attempts"] = attempt
        started = time.perf_counter()
        try:
            response, status = call_api(ctx["base"], ctx["key"], payload, ctx["params"]["timeout"])
            record["http_status"] = status
            record["elapsed_s"] = round(time.perf_counter() - started, 3)
            choice = response["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if not isinstance(content, str):
                raise ExtractError("invalid_completion_response")
            record["finish_reason"] = choice.get("finish_reason")
            record["usage"] = safe_usage(response.get("usage"))
            returned = response.get("model", "")
            if isinstance(returned, str) and MODEL_ID_RE.fullmatch(returned) and ctx["key"] not in returned:
                record["response_model"] = returned
            record["raw_response"] = redact(content, ctx["key"])
            if message.get("tool_calls") or message.get("function_call"):
                raise ExtractError("unexpected_tool_call")
            if not content.strip():
                raise ExtractError("empty_response")
            if choice.get("finish_reason") != "stop":
                raise ExtractError("truncated_or_incomplete:%s" % choice.get("finish_reason"))
            normalized, fence_stripped = normalize_json_text(content)
            record["raw_fence_stripped"] = fence_stripped
            try:
                parsed = json.loads(normalized)
            except ValueError:
                raise ExtractError("invalid_json_response") from None
            ok, reason = validate_parsed(parsed, ctx["schema"], image_id)
            if not ok:
                raise ExtractError(reason)
            record["parsed"] = parsed
            record["status"] = "success"
            record.pop("error_code", None)
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            return record
        except ExtractError as err:
            last_error = err.code
            record["error_code"] = err.code
            if err.http_status:
                record["http_status"] = err.http_status
            transient = err.http_status in TRANSIENT_HTTP or err.code.split(":")[0] in TRANSPORT_CODES
            if not is_retryable(err.code, err.http_status, attempt, ctx["max_retries"]):
                break
            delay = (backoff_delay(attempt) if transient else CONTENT_RETRY_DELAY) + rng.random() * 0.4
            log("[retry] %s attempt=%d/%d code=%s sleep=%.1fs" % (image_id, attempt, ctx["max_retries"], err.code, delay))
            time.sleep(delay)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            last_error = "malformed_response_shape"
            record["error_code"] = last_error
            break
    record["status"] = "failed"
    record["error_code"] = last_error
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


# --------------------------------------------------------------------------- #
# Batch orchestration
# --------------------------------------------------------------------------- #
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
    input_sha_by_id = {e["image_id"]: e["sha256"] for e in entries}
    ctx_full = dict(ctx)
    ctx_full["input_sha_by_id"] = input_sha_by_id
    skip = resume_skip_ids(existing, ctx_full) if resume else set()

    counters = {
        "total": len(entries),
        "skipped_resumed": len(skip),
        "success": 0,
        "failed": 0,
        "pending": len(entries) - len(skip),
    }
    started_at = _utcnow_iso()
    log("[run] total=%d resume_skip=%d pending=%d concurrency=%d max_retries=%d" % (
        counters["total"], counters["skipped_resumed"], counters["pending"], ctx["concurrency"], ctx["max_retries"]))

    lock = threading.Lock()
    with open(results_path, "a", encoding="utf-8") as out_fh:
        def flush_status():
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
                "state": "running",
                "concurrency": ctx["concurrency"],
                "max_retries": ctx["max_retries"],
                "params": ctx["params"],
                "params_fingerprint": ctx["params_fingerprint"],
                "prompt_version": ctx["prompt_version"],
                "schema_version": ctx["schema_version"],
                "model": ctx["model"],
                "counts": dict(counters),
                "eta_s": eta,
            }
            status_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

        def handle_done(fut):
            rec = fut.result()
            with lock:
                if rec["status"] == "success":
                    counters["success"] += 1
                else:
                    counters["failed"] += 1
                counters["pending"] -= 1
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_fh.flush()
                if (counters["success"] + counters["failed"]) % 50 == 0:
                    flush_status()

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
                "params": ctx["params"],
                "params_fingerprint": ctx["params_fingerprint"],
                "prompt_version": ctx["prompt_version"],
                "schema_version": ctx["schema_version"],
                "model": ctx["model"],
                "counts": dict(counters),
            }
            status_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
            log("[run] done state=%s success=%d failed=%d pending=%d" % (
                snap_state, counters["success"], counters["failed"], counters["pending"]))
    return counters


def _failed_ids(out_dir):
    """Last-wins set of image_ids currently marked failed in results.jsonl."""
    by_id = {}
    rp = Path(out_dir) / "results.jsonl"
    if rp.is_file():
        with open(rp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    by_id[rec.get("image_id")] = rec
    return {iid for iid, r in by_id.items() if r.get("status") == "failed"}


def load_manifest(out_dir):
    path = Path(out_dir) / "manifest.jsonl"
    records = []
    if path.is_file():
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def select_entries(records, ids=None, limit=None, seed=None, only_ext=None):
    sel = records
    if only_ext:
        allowed = {e.strip().lower() for e in only_ext.split(",")}
        sel = [r for r in sel if r.get("ext") in allowed]
    if ids:
        wanted = set(ids)
        by_id = {r["image_id"]: r for r in sel}
        by_rel = {r["relpath"]: r for r in sel}
        picked = []
        missing = []
        for w in ids:
            if w in by_id:
                picked.append(by_id[w])
            elif w in by_rel:
                picked.append(by_rel[w])
            else:
                missing.append(w)
        if missing:
            log = sys.stderr.write
            log("[select] WARNING: %d ids not found in manifest: %s\n" % (len(missing), ", ".join(missing[:20])))
        sel = picked
    if seed is not None:
        rnd = random.Random(seed)
        sel = list(sel)
        rnd.shuffle(sel)
    if limit is not None:
        sel = sel[:limit]
    return sel


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def build_report(out_dir, change_dir):
    out_dir = Path(out_dir)
    change_dir = Path(change_dir)
    manifest = load_manifest(out_dir)
    manifest_by_id = {m["image_id"]: m for m in manifest}
    results = []
    rp = out_dir / "results.jsonl"
    if rp.is_file():
        with open(rp, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except ValueError:
                        pass
    by_id = {}
    for rec in results:  # last record wins per image_id
        by_id[rec.get("image_id")] = rec

    # Consolidated per-image final state (one record per image_id, last-wins),
    # so reviewers get a clean checkpoint-independent view of every image.
    with open(out_dir / "results_final.jsonl", "w", encoding="utf-8") as fh:
        for iid in sorted(by_id):
            fh.write(json.dumps(by_id[iid], ensure_ascii=False) + "\n")

    success = [r for r in by_id.values() if r.get("status") == "success"]
    failed = [r for r in by_id.values() if r.get("status") == "failed"]
    covered_ids = set(by_id.keys())
    pending_ids = [mid for mid in manifest_by_id if mid not in covered_ids]

    # input correspondence check for successes
    mismatched = []
    for r in success:
        m = manifest_by_id.get(r.get("image_id"))
        if not m or m.get("sha256") != r.get("input_sha256"):
            mismatched.append(r.get("image_id"))

    error_counts = {}
    for r in failed:
        code = (r.get("error_code") or "unknown").split(":")[0]
        error_counts[code] = error_counts.get(code, 0) + 1

    image_type_counts = {}
    confidences = []
    for r in success:
        p = r.get("parsed") or {}
        it = p.get("image_type")
        if isinstance(it, str):
            image_type_counts[it] = image_type_counts.get(it, 0) + 1
        c = p.get("confidence")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            confidences.append(c)

    dup_members = {}
    for m in manifest:
        grp = m.get("dup_group")
        dup_members.setdefault(grp, []).append(m["image_id"])
    dup_groups_gt1 = {k: v for k, v in dup_members.items() if len(v) > 1}

    total = len(manifest)
    summary = {
        "change_id": CHANGE_ID,
        "generated_at": _utcnow_iso(),
        "corpus": {
            "total_manifest_entries": total,
            "success": len(success),
            "failed": len(failed),
            "pending": len(pending_ids),
            "coverage_success_pct": round(100.0 * len(success) / total, 3) if total else 0.0,
        },
        "checks": {
            "success_input_sha_match": len(success) - len(mismatched),
            "success_input_sha_mismatch": len(mismatched),
            "mismatched_ids_sample": mismatched[:20],
        },
        "errors": error_counts,
        "image_type_distribution": dict(sorted(image_type_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "confidence": {
            "n": len(confidences),
            "mean": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
            "note": "confidence is the model's self-assessment, not an accuracy metric",
        },
        "duplicates": {
            "groups_gt1": len(dup_groups_gt1),
            "member_files": sum(len(v) for v in dup_groups_gt1.values()),
            "note": "duplicate-content files keep distinct image_ids and are all processed",
        },
        "pending_ids_sample": pending_ids[:50],
        "failed_ids_sample": [r.get("image_id") for r in failed[:50]],
        "output_dir": str(out_dir),
    }
    (change_dir / "results").mkdir(parents=True, exist_ok=True)
    (change_dir / "results" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown_report(change_dir, summary, manifest, by_id, failed, success)
    return summary


def _write_markdown_report(change_dir, summary, manifest, by_id, failed, success):
    c = summary["corpus"]
    lines = []
    lines.append("# AUTO-006 全量单图理解 — 结果报告")
    lines.append("")
    lines.append("- 生成时间: %s" % summary["generated_at"])
    lines.append("- 输出目录(非提交): %s" % summary["output_dir"])
    lines.append("- 模型: (见 status.json / 逐图记录)")
    lines.append("")
    lines.append("## 覆盖与状态")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append("| manifest 总数 | %d |" % c["total_manifest_entries"])
    lines.append("| 成功 success | %d |" % c["success"])
    lines.append("| 失败 failed | %d |" % c["failed"])
    lines.append("| 未处理 pending | %d |" % c["pending"])
    lines.append("| 成功率 | %.3f%% |" % c["coverage_success_pct"])
    lines.append("")
    lines.append("## 一致性检查")
    lines.append("")
    chk = summary["checks"]
    lines.append("- 成功记录输入 sha 与 manifest 一致: %d" % chk["success_input_sha_match"])
    lines.append("- 成功记录输入 sha 不一致: %d" % chk["success_input_sha_mismatch"])
    lines.append("")
    lines.append("## 失败原因分布")
    lines.append("")
    if summary["errors"]:
        lines.append("| 原因码 | 数量 |")
        lines.append("|---|---|")
        for k, v in sorted(summary["errors"].items(), key=lambda kv: -kv[1]):
            lines.append("| %s | %d |" % (k, v))
    else:
        lines.append("(无失败)")
    lines.append("")
    lines.append("## image_type 分布 (成功)")
    lines.append("")
    if summary["image_type_distribution"]:
        lines.append("| image_type | 数量 |")
        lines.append("|---|---|")
        for k, v in summary["image_type_distribution"].items():
            lines.append("| %s | %d |" % (k, v))
    else:
        lines.append("(暂无成功记录)")
    lines.append("")
    lines.append("## confidence (自评分, 非准确率)")
    lines.append("")
    cf = summary["confidence"]
    lines.append("- n=%s mean=%s min=%s max=%s" % (cf["n"], cf["mean"], cf["min"], cf["max"]))
    lines.append("")
    lines.append("## 重复内容")
    lines.append("")
    lines.append("- 重复内容组(>1): %d, 涉及文件: %d (各组保留独立 image_id, 均已处理)" % (
        summary["duplicates"]["groups_gt1"], summary["duplicates"]["member_files"]))
    lines.append("")
    lines.append("## 未处理样例 (若有)")
    lines.append("")
    if summary["pending_ids_sample"]:
        for pid in summary["pending_ids_sample"]:
            lines.append("- %s" % pid)
    else:
        lines.append("(无未处理)")
    lines.append("")
    lines.append("## 失败样例 (若有)")
    lines.append("")
    if failed:
        lines.append("| image_id | 原因码 | finish_reason |")
        lines.append("|---|---|---|")
        for r in failed[:50]:
            lines.append("| %s | %s | %s |" % (r.get("image_id"), r.get("error_code"), r.get("finish_reason")))
    else:
        lines.append("(无失败)")
    lines.append("")
    lines.append("> confidence 是模型自评, 不等于准确率。本报告如实保留失败项, 不谎报全部成功。")
    (change_dir / "results" / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_ctx(args):
    prompt_text = Path(args.prompt_file).read_text(encoding="utf-8-sig")
    schema = json.loads(Path(args.schema_file).read_text(encoding="utf-8-sig"))
    model, base, key = load_connection(Path(args.settings), Path(args.env_file))
    params = {
        "image_max_edge": int(args.image_max_edge),
        "max_tokens": int(args.max_tokens),
        "temperature": float(args.temperature),
        "enable_thinking": bool(args.enable_thinking),
        "timeout": int(args.timeout),
    }
    return {
        "model": model,
        "base": base,
        "key": key,
        "template": prompt_text,
        "prompt_version": sha256_bytes(prompt_text.encode("utf-8"))[:16],
        "schema": schema,
        "schema_version": sha256_bytes(Path(args.schema_file).read_bytes())[:16],
        "params": params,
        "params_fingerprint": make_params_fingerprint(params),
        "max_retries": int(args.max_retries),
        "concurrency": int(args.concurrency),
    }


def cmd_connect(args):
    model, base, key = load_connection(Path(args.settings), Path(args.env_file))
    request = urllib.request.Request(
        base + "/models", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with _OPENER.open(request, timeout=args.timeout) as response:
            data = json.loads(response.read(MAX_RESPONSE_BYTES + 1))
            available = isinstance(data, dict) and model in [x.get("id") for x in data.get("data", []) if isinstance(x, dict)]
            print(json.dumps({"route": "direct_qwen_api", "configured_model": model, "http_status": response.status, "model_available": available}))
            return 0 if available else 3
    except urllib.error.HTTPError as err:
        print(json.dumps({"route": "direct_qwen_api", "configured_model": model, "http_status": err.code, "model_available": False}))
        return 3
    except Exception:
        print(json.dumps({"route": "direct_qwen_api", "configured_model": model, "http_status": None, "model_available": False}))
        return 3


def cmd_manifest(args):
    summary, _records = build_manifest(args.images_root, args.manifest_csv, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args):
    records = load_manifest(args.out_dir)
    if not records:
        print(json.dumps({"state": "FAILED", "error": "manifest_missing", "hint": "run 'manifest' first (or pass --out-dir with manifest.jsonl)"}))
        return 2
    if args.failed:
        failed = _failed_ids(args.out_dir)
        entries = [r for r in records if r["image_id"] in failed]
    else:
        entries = select_entries(
            records,
            ids=args.ids.split(",") if args.ids else None,
            limit=args.limit,
            seed=args.seed,
            only_ext=args.only_ext,
        )
    if not entries:
        print(json.dumps({"state": "FAILED", "error": "no_entries_selected"}))
        return 2
    ctx = _build_ctx(args)
    log_path = Path(args.out_dir) / "run.log"
    log_fh = open(log_path, "a", encoding="utf-8")

    def log(msg):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = "[%s] %s" % (stamp, msg)
        print(line, flush=True)
        log_fh.write(line + "\n")
        log_fh.flush()

    log_fh.write("[%s] ===== run start pid=%d selected=%d =====\n" % (_utcnow_iso(), os.getpid(), len(entries)))
    log_fh.flush()
    counters = run_batch(entries, ctx, args.out_dir, resume=not args.no_resume, log=log)
    log_fh.close()
    print(json.dumps({"state": "completed" if counters["pending"] == 0 else "partial", "counts": counters}, ensure_ascii=False))
    return 0 if counters["pending"] == 0 else 3


def cmd_report(args):
    summary = build_report(args.out_dir, args.change_dir)
    print(json.dumps({"success": summary["corpus"]["success"], "failed": summary["corpus"]["failed"], "pending": summary["corpus"]["pending"]}, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pc = sub.add_parser("connect", help="check the configured model endpoint")
    pc.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    pc.add_argument("--env-file", dest="env_file", default=str(DEFAULT_ENV_FILE))
    pc.add_argument("--timeout", type=int, default=15)
    pc.set_defaults(func=cmd_connect)

    pm = sub.add_parser("manifest", help="build the image manifest")
    pm.add_argument("--images-root", default=str(DEFAULT_IMAGES_ROOT))
    pm.add_argument("--manifest-csv", default=str(MANIFEST_CSV_DEFAULT))
    pm.add_argument("--out", default=str(DEFAULT_OUTPUT_DIR / "manifest.jsonl"))
    pm.set_defaults(func=cmd_manifest)

    pr = sub.add_parser("run", help="run the batch (resumable)")
    pr.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR))
    pr.add_argument("--prompt-file", default=str(DEFAULT_PROMPT_FILE))
    pr.add_argument("--schema-file", default=str(DEFAULT_SCHEMA_FILE))
    pr.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    pr.add_argument("--env-file", dest="env_file", default=str(DEFAULT_ENV_FILE))
    pr.add_argument("--ids", default=None, help="comma-separated image_ids or relpaths to run only these")
    pr.add_argument("--failed", action="store_true", help="re-run only image_ids currently marked failed in results.jsonl (recovery pass)")
    pr.add_argument("--limit", type=int, default=None)
    pr.add_argument("--seed", type=int, default=None)
    pr.add_argument("--only-ext", default=None)
    pr.add_argument("--concurrency", type=int, default=4)
    pr.add_argument("--max-retries", type=int, default=3)
    pr.add_argument("--image-max-edge", type=int, default=1280)
    pr.add_argument("--max-tokens", type=int, default=2048)
    pr.add_argument("--temperature", type=float, default=0.0)
    pr.add_argument("--timeout", type=int, default=180)
    pr.add_argument("--enable-thinking", action="store_true")
    pr.add_argument("--no-resume", action="store_true")
    pr.set_defaults(func=cmd_run)

    pp = sub.add_parser("report", help="aggregate results into summary.json + report.md")
    pp.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR))
    pp.add_argument("--change-dir", default=str(DEFAULT_CHANGE_DIR))
    pp.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ExtractError as err:
        print(json.dumps({"state": "FAILED", "error": err.code, "http_status": err.http_status}))
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(json.dumps({"state": "FAILED", "error": "io_or_parse_error", "detail": type(err).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
