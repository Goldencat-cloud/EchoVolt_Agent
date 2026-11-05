"""Frozen 100-post V2.3 trial: prepare, dry-run, probe, run, report; no retries."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import time
import concurrent.futures as cf
import shutil

from tools import qwen_delegate as delegate
from tools.modular_post_extraction import validate_evidence, validate_post_pack
from tools.post_contract_v23 import validate as validate_v23, normalise_for_contract

ROOT = Path(__file__).resolve().parents[1]
CHANGE = ROOT / "openspec/changes/auto-016-modular-post-extraction"
PROMPTS, SCHEMAS = CHANGE / "prompts", CHANGE / "schemas"
BASE = ROOT / "collaboration/result/auto016-modular-post-extraction"
OUT = BASE / "v23-run1"
PACKETS = CHANGE / "delegations/v23-run1"
SETTINGS, ENV = ROOT / "local-config/settings.json", ROOT / "local-config/.env"
SOURCE = ROOT / "collaboration/result/auto008/model_inputs.jsonl"
META = ROOT / "collaboration/data/004_A4_图片策展_主链路终版.csv"
MODEL = "qwen3.8-27b"
PARAMS = {"max_tokens": 8192, "temperature": 0, "timeout_seconds": 300, "enable_thinking": False, "structured_output": True, "prompt_as_system": True}


def wire_schema(schema):
    """Keep uniqueness in canonical validation; unsupported in gateway grammar."""
    if isinstance(schema, dict):
        return {k: wire_schema(v) for k, v in schema.items() if k != "uniqueItems"}
    if isinstance(schema, list):
        return [wire_schema(v) for v in schema]
    return schema


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path, obj, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    else:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


def rel(path):
    return path.relative_to(ROOT).as_posix()


def candidate_schema():
    evidence = read(SCHEMAS / "post-output-v2.3.json")["properties"]["claims"]["items"]["properties"]["evidence"]
    fields = {"candidate_id": {"type": "string", "minLength": 1}, "raw_mentions": {"type": "array", "items": {"type": "string"}},
              "speaker": {"enum": ["author", "quoted_other", "unknown"]},
              "source_status": {"enum": ["author_text", "quoted_text", "image_summary", "unknown"]},
              "raw_text": {"type": "string", "minLength": 1}, "evidence": evidence}
    return {"type": "object", "additionalProperties": False, "required": ["schema_version", "candidates"],
            "properties": {"schema_version": {"const": "candidate-v2.3"}, "candidates": {"type": "array", "items": {
                "type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}}}


def prepare():
    if OUT.exists():
        raise ValueError("refuse overwrite existing experiment; use dry-run/probe/run/report")
    planned = read(BASE / "manifest.json")
    ids = planned["post_ids"]
    if len(ids) != 100 or len(set(ids)) != 100 or planned["seed"] != 20261016:
        raise ValueError("unexpected sample manifest")
    before = {str(p): hash_file(p) for p in (SOURCE, META, BASE / "manifest.json")}
    wanted = set(ids)
    with META.open(encoding="utf-8-sig", newline="") as f:
        metadata = {r["post_id"]: r for r in csv.DictReader(f) if r["post_id"] in wanted}
    sources = {}
    source_count = 0
    with SOURCE.open(encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            source_count += 1
            if row["post_id"] in wanted:
                if row["post_id"] in sources:
                    raise ValueError("duplicate source post_id")
                sources[row["post_id"]] = row
    if set(sources) != wanted or set(metadata) != wanted:
        raise ValueError("missing sampled post in integrated source or metadata")
    schema = candidate_schema()
    target = SCHEMAS / "candidate-v2.3.json"
    if target.exists() and read(target) != schema:
        raise ValueError("candidate schema changed")
    if not target.exists():
        save(target, schema, exclusive=True)
    rows = []
    # Freeze prompts/schema within the result package for portability/review.
    for name, source in {
        "candidate-prompt.md": PROMPTS / "candidate-v2.3.md", "post-pack-prompt.md": PROMPTS / "post-pack-v2.3.md",
        "baseline-prompt.md": PROMPTS / "source-v2.1.md", "candidate.schema.json": target,
        "post-output.schema.json": SCHEMAS / "post-output-v2.3.json", "baseline.schema.json": SCHEMAS / "post-pack-v1.json",
    }.items():
        dest = OUT / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    save(OUT / "post-output.wire.schema.json", wire_schema(read(OUT / "post-output.schema.json")), exclusive=True)
    save(OUT / "wire-schema-policy.json", {"removed_from_wire_only": ["uniqueItems"], "canonical_schema": "post-output.schema.json",
         "reason": "HTTP400 confirmed gateway Grammar error: Unimplemented keys uniqueItems", "local_validation_required": True}, exclusive=True)
    for index, pid in enumerate(ids):
        original = sources[pid]["post_input"]
        if metadata[pid]["title"] != original["title"]:
            raise ValueError("source title mismatch")
        blocks = [{"block_id": "T0", "type": "text", "text": original["title"]}]
        mapping = [{"block_id": "T0", "source_sequence_index": -1, "original_id": "title",
                    "content_sha256": digest(original["title"])}]
        t, im = 1, 0
        for seq_index, b in enumerate(original["sequence"]):
            if b["type"] == "text":
                block = {"block_id": f"T{t}", "type": "text", "text": b["text"]}
                t += 1
            elif b["type"] == "image":
                block = {"block_id": f"I{im}", "type": "image", "summary": b["summary"]}
                im += 1
            else:
                raise ValueError("unexpected source block")
            field = "summary" if block["type"] == "image" else "text"
            if not isinstance(block[field], str) or not block[field].strip():
                raise ValueError(f"empty integrated block: {pid}/{seq_index}")
            blocks.append(block)
            mapping.append({"block_id": block["block_id"], "source_sequence_index": seq_index,
                            "original_id": b.get("image_id", b.get("text_block_id")), "content_sha256": digest(block[field])})
        post = {"post_id": pid, "created_at": metadata[pid]["created_at"] or None, "title": original["title"], "blocks": blocks}
        path = OUT / "inputs" / (pid + ".json")
        save(path, post, exclusive=True)
        rows.append({"index": index, "post_id": pid, "input_path": rel(path), "input_sha256": hash_file(path), "images": im,
                     "source_record_sha256": digest(sources[pid]), "mapping": mapping})
    if any(hash_file(Path(p)) != h for p, h in before.items()):
        raise ValueError("sources changed while preparing")
    assets = {rel(p): hash_file(p) for p in OUT.glob("*.md")}
    assets.update({rel(p): hash_file(p) for p in OUT.glob("*.json")})
    for p in (ROOT / "tools/qwen_delegate.py", ROOT / "tools/post_contract_v23.py", Path(__file__)):
        assets[rel(p)] = hash_file(p)
        dest = OUT / "source" / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
    manifest = {"change_id": CHANGE.name, "branch": "change/auto-016-modular-post-extraction", "seed": planned["seed"],
                "sample_size": 100, "source_posts": source_count, "source_hashes": before, "assets": assets,
                "sample_identity_preserved": True, "image_posts": sum(r["images"] > 0 for r in rows), "rows": rows,
                "input_policy": "AUTO008 integrated sequence verbatim with title copied as first text block T0, created_at by exact CSV post_id; no new vision calls",
                "prompt_version": "2.3", "output_schema_version": "2.3", "api_calls": 0, "created_at": datetime.now(timezone.utc).isoformat()}
    save(OUT / "manifest.json", manifest, exclusive=True)
    for row in rows:
        for stage in ("baseline", "candidate"):
            packet_for(row, stage)
    print(json.dumps({"prepared": 100, "source_posts": source_count, "image_posts": manifest["image_posts"], "api_calls": 0}), flush=True)


def packet_for(row, stage, candidate=None):
    pid = row["post_id"]
    path = PACKETS / f"{stage}-{pid}.json"
    if stage == "post-pack":
        combined = {"post": read(ROOT / row["input_path"]), "candidates": candidate}
        input_path = OUT / "stage-inputs" / f"{pid}.json"
        if input_path.exists() and read(input_path) != combined:
            raise ValueError("upstream candidate changed; refusing overwrite")
        if not input_path.exists():
            save(input_path, combined, exclusive=True)
    else:
        input_path = ROOT / row["input_path"]
    prompt_name = {"candidate": "candidate-prompt.md", "post-pack": "post-pack-prompt.md", "baseline": "baseline-prompt.md"}[stage]
    schema_name = {"candidate": "candidate.schema.json", "post-pack": "post-output.wire.schema.json", "baseline": "baseline.schema.json"}[stage]
    packet = {"task_id": f"a016-{stage}-{pid}", "change_id": CHANGE.name,
              "task_refs": ["2.1"] if stage == "candidate" else ["3.1"] if stage == "post-pack" else ["4.2"],
              "prompt_file": rel(OUT / prompt_name), "context_files": [rel(input_path)], "response_type": "json",
              "schema_file": rel(OUT / schema_name), **PARAMS}
    if path.exists() and read(path) != packet:
        raise ValueError("packet changed; refusing reuse")
    if not path.exists():
        save(path, packet, exclusive=True)
    return path, packet


def audit():
    m = read(OUT / "manifest.json")
    for path, expected in {**m["source_hashes"], **m["assets"]}.items():
        actual = Path(path) if Path(path).is_absolute() else ROOT / path
        if hash_file(actual) != expected:
            raise ValueError("frozen asset/source changed: " + str(actual))
    for row in m["rows"]:
        if hash_file(ROOT / row["input_path"]) != row["input_sha256"]:
            raise ValueError("frozen input changed")
    return m


def quality(post, stage, payload):
    if stage == "post-pack":
        return validate_v23(post, normalise_for_contract(payload))
    if stage == "baseline":
        return validate_post_pack(post, payload)
    errors = []
    seen = set()
    for candidate in payload["candidates"]:
        cid = candidate["candidate_id"]
        if cid in seen:
            errors.append("duplicate_candidate_id")
        seen.add(cid)
        errors.extend(validate_evidence(post, candidate["evidence"]))
    return errors


def call_stage(row, stage, candidate, connection):
    path, packet = packet_for(row, stage, candidate)
    # prepare_task is the same validated dry-run used by the project CLI.
    prepared = delegate.prepare_task(ROOT, packet)
    fingerprint = digest({"packet": packet, "inputs": prepared["inputs"], "parameters": prepared["parameters"],
                          "model": MODEL, "endpoint": connection, "messages": prepared["messages"]})
    target = OUT / "calls" / f"{stage}-{row['post_id']}"
    if target.exists():
        if not (target / "local-review.json").exists():
            raise ValueError("uncertain or interrupted call; no retry: " + target.name)
        review = read(target / "local-review.json")
        if review["cache_key"] != fingerprint:
            raise ValueError("cached request fingerprint changed")
        recorded = read(target / "result.json")
        if review["state"] == "CONTRACT_PASS":
            if recorded.get("state") != "REVIEW_REQUIRED" or read(target / "response.json") != review.get("payload"):
                raise ValueError("cached review conflicts with raw result")
            if quality(read(ROOT / row["input_path"]), stage, review["payload"]):
                raise ValueError("cached result fails current quality gate")
        for item in recorded["inputs"]:
            if hash_file(ROOT / item["path"]) != item["sha256"]:
                raise ValueError("cached input changed")
        review["cache_hit"] = True
        return review
    actual_model, actual_base, _ = delegate.load_connection(SETTINGS, ENV)
    if actual_model != MODEL or hashlib.sha256(actual_base.encode()).hexdigest() != connection:
        raise ValueError("configured model or endpoint changed")
    reused = False
    prior = BASE / "v23-run1/calls" / f"{stage}-{row['post_id']}"
    prior_result = prior / "result.json"
    if stage in {"baseline", "candidate"} and prior_result.exists():
        old = read(prior_result)
        payload_fingerprint = digest({"model": MODEL, "messages": prepared["messages"], **prepared["parameters"], "stream": False})
        if old["state"] == "REVIEW_REQUIRED" and old["request_fingerprint"] == payload_fingerprint and old["endpoint_fingerprint"] == connection:
            for item in old["inputs"]:
                if hash_file(ROOT / item["path"]) != item["sha256"]:
                    raise ValueError("prior input changed")
            prior_payload = read(prior / "response.json")
            if not quality(read(ROOT / row["input_path"]), stage, prior_payload):
                target.mkdir(parents=True, exist_ok=False)
                for name in ("response.txt", "response.json"):
                    shutil.copyfile(prior / name, target / name)
                record = {**old, "api_calls": 0, "inputs": prepared["inputs"], "reused_from": rel(prior),
                          "task_fingerprint": digest(packet), "reuse_verified_identical_request": True}
                save(target / "result.json", record, exclusive=True)
                reused = True
    if not reused:
        record = delegate.dispatch(ROOT, packet, rel(target), SETTINGS, ENV)
    post = read(ROOT / row["input_path"])
    errors = []
    payload = None
    if record["state"] == "REVIEW_REQUIRED":
        payload = read(target / "response.json")
        errors = quality(post, stage, payload)
    else:
        errors = [record.get("error", "api_failed")]
    if record.get("inputs_changed_after_request"):
        errors.append("inputs_changed_after_request")
    review = {"post_id": row["post_id"], "stage": stage, "cache_key": fingerprint, "cache_hit": False,
              "state": "CONTRACT_PASS" if not errors else "FAILED", "errors": errors, "new_api_calls": record.get("api_calls", 1),
              "reused_from": record.get("reused_from"),
              "record_path": rel(target / "result.json"), "payload": payload, "usage": record.get("usage"),
              "elapsed_s": record.get("elapsed_s"), "http_status": record.get("http_status"),
              "semantic_acceptance": "NOT_MEASURED"}
    save(target / "local-review.json", review, exclusive=True)
    return review


def report():
    manifest = read(OUT / "manifest.json")
    reviews = [read(p) for p in (OUT / "calls").glob("*/local-review.json")]
    raw_records = [read(p) for p in (OUT / "calls").glob("*/result.json")]
    summaries = {}
    for stage in ("baseline", "candidate", "post-pack"):
        rs = [r for r in reviews if r["stage"] == stage]
        usage = {k: sum((r.get("usage") or {}).get(k, 0) for r in rs) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        cached = sum((r.get("usage") or {}).get("prompt_tokens_details", {}).get("cached_tokens", 0) for r in rs)
        summaries[stage] = {"records": len(rs), "contract_pass": sum(r["state"] == "CONTRACT_PASS" for r in rs),
                            "failures": sum(r["state"] != "CONTRACT_PASS" for r in rs), "token_usage": usage,
                            "reported_cached_tokens": cached, "usage_unavailable": sum(r.get("usage") is None for r in rs)}
        summaries[stage]["locally_reused_records"] = sum(bool(r.get("reused_from")) for r in rs)
        summaries[stage]["new_request_tokens"] = sum((r.get("usage") or {}).get("total_tokens", 0) for r in rs if r.get("new_api_calls", 1))
    summary = {"planned_posts": 100, "closed_model_requests": sum(r.get("api_calls", 1) for r in raw_records), "stages": summaries,
               "semantic_acceptance": "NOT_MEASURED", "updated_at": datetime.now(timezone.utc).isoformat()}
    save(OUT / "progress.json", summary)
    results = [r["payload"] for r in reviews if r["stage"] == "post-pack" and r["state"] == "CONTRACT_PASS"]
    (OUT / "model-outputs.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in results), encoding="utf-8")
    failures = [{k: r[k] for k in ("post_id", "stage", "errors", "record_path")} for r in reviews if r["state"] != "CONTRACT_PASS"]
    save(OUT / "failures.json", failures)
    by_id = {}
    for r in reviews:
        by_id.setdefault(r["post_id"], {})[r["stage"]] = r
    cards = []
    for row in manifest["rows"]:
        post = read(ROOT / row["input_path"])
        rendered = html.escape(json.dumps({"input": post, "stages": by_id.get(row["post_id"], {})}, ensure_ascii=False, indent=2))
        cards.append(f'<details id="{row["post_id"]}"><summary>{html.escape(post["title"])} · {row["post_id"]}</summary><pre>{rendered}</pre></details>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AUTO016 V2.3复核</title><style>body{background:#101722;color:#e2e8f0;font:16px system-ui;margin:24px}summary{padding:16px;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:#182435}details{border:1px solid #42516a;margin:8px 0}</style><h1>AUTO016 V2.3 · 固定100帖</h1><p>结构与引用检查不代表语义准确；展开查看原文、候选、旧版和新版输出。原始模型说明未重新核验。</p>' + "".join(cards) + '</html>'
    (OUT / "review.html").write_text(page, encoding="utf-8")
    return summary


def main():
    global OUT, PACKETS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "dry-run", "probe", "run", "report"])
    parser.add_argument("--run-id", default="v23-run2", choices=["v23-run2"])
    parser.add_argument("--workers", type=int, default=3, choices=[1, 2, 3])
    args = parser.parse_args()
    OUT = BASE / args.run_id
    PACKETS = CHANGE / "delegations" / args.run_id
    if args.command == "prepare":
        prepare()
        return
    if args.command == "report":
        print(json.dumps(report(), ensure_ascii=False))
        return
    m = audit()
    for row in m["rows"]:
        for stage in ("baseline", "candidate"):
            _, packet = packet_for(row, stage)
            delegate.prepare_task(ROOT, packet)
    if args.command == "dry-run":
        print("200 explicit baseline/candidate packets valid; 0 API calls; post-pack prepared only after valid candidate")
        return
    model, base, _ = delegate.load_connection(SETTINGS, ENV)
    if model != MODEL:
        raise ValueError("configured model differs from authorized Qwen")
    endpoint = hashlib.sha256(base.encode()).hexdigest()
    short = sorted(m["rows"], key=lambda r: (ROOT / r["input_path"]).stat().st_size)
    probe = [next(r for r in short if not r["images"]), next(r for r in short if r["images"])]
    probe_ids = {r["post_id"] for r in probe}
    if args.command == "run":
        for r in probe:
            for stage in ("baseline", "candidate", "post-pack"):
                record = OUT / "calls" / f"{stage}-{r['post_id']}" / "local-review.json"
                if not record.exists() or read(record)["state"] != "CONTRACT_PASS":
                    raise ValueError("probe not fully passed; refuse batch")
    selected = probe if args.command == "probe" else [r for r in m["rows"] if r["post_id"] not in probe_ids]
    start = time.time()
    def process_row(row):
        candidate = None
        results = []
        for stage in ("baseline", "candidate", "post-pack"):
            result = call_stage(row, stage, candidate, endpoint)
            results.append(result)
            if stage == "candidate":
                candidate = result["payload"]
            print(json.dumps({"post_id": row["post_id"], "stage": stage, "state": result["state"], "cache_hit": result["cache_hit"], "errors": result["errors"][:3], "usage": result["usage"]}, ensure_ascii=False), flush=True)
            if result["state"] != "CONTRACT_PASS":
                break
        return results
    if args.command == "probe":
        for row in selected:
            results = process_row(row)
            report()
            if results[-1]["state"] != "CONTRACT_PASS":
                print("Stopped on recorded probe failure; no retries or batch.", flush=True)
                return
    else:
        queue = iter(selected)
        pending = {}
        failures = 0
        stopped = False
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            def fill():
                while not stopped and len(pending) < args.workers:
                    try:
                        row = next(queue)
                    except StopIteration:
                        return
                    pending[pool.submit(process_row, row)] = row
            fill()
            while pending:
                done, _ = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
                for future in done:
                    row = pending.pop(future)
                    try:
                        results = future.result()
                        failed = results[-1]["state"] != "CONTRACT_PASS"
                        failures = failures + 1 if failed else 0
                        if failures >= 3 or any(r.get("http_status") in {400, 401, 403, 429} for r in results):
                            stopped = True
                    except Exception as e:
                        stopped = True
                        save(OUT / "controller-error.json", {"post_id": row["post_id"], "exception_type": type(e).__name__, "no_retry": True})
                report()
                fill()
        if stopped:
            print("Circuit stopped; no retries; pending work remains.", flush=True)
            return
    save(OUT / (args.command + "-timing.json"), {"elapsed_s": time.time()-start, "new_run_finished_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps(report(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
