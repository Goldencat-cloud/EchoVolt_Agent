"""Repair deterministic AUTO-016 V2.3 failures and rerun unresolved posts once."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools import auto016_run_v23 as shared
from tools.post_contract_v23 import _citation_matches, normalise_for_contract, validate


ROOT = shared.ROOT
CHANGE = shared.CHANGE
SOURCE = shared.BASE / "single-v23-full"
OUT = shared.BASE / "single-v23-full-repair1"
PACKETS = CHANGE / "delegations/single-v23-full-repair1"
KEY_SOURCE_FILES = (
    "manifest.json",
    "failures.json",
    "all-results.jsonl",
    "final-report.json",
    "full-v2.3.md",
    "output.schema.json",
    "output.wire.schema.json",
)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value, exclusive: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def hash_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_value(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evidence_map(output):
    result = {}

    def add(items, prefix):
        for index, item in enumerate(items):
            result[f"{prefix}/{index}"] = item

    for group in ("products", "claims", "events"):
        for record in output[group]:
            add(record["evidence"], f"{group}/{record['id']}/evidence")
    add(output["user_context"]["evidence"], "user_context/evidence")
    for claim in output["claims"]:
        if claim["usage_context"] is not None:
            add(claim["usage_context"]["evidence"], f"{claim['id']}/usage_context/evidence")
        if claim["comparison"] is not None:
            for index, relation in enumerate(claim["comparison"]["relations"]):
                add(relation["evidence"], f"{claim['id']}/comparison/{index}/evidence")
    return result


def repair_payload(post, payload, errors, identity_verified=False):
    """Return a repaired copy and audit entries, or ``None`` when not safe."""
    value = copy.deepcopy(payload)
    audit = []
    allowed = {"post_id_mismatch"}
    if any(error not in allowed and not error.endswith(":non_contiguous_quote") for error in errors):
        return None, [{"rule": "unsupported_contract_error", "errors": errors}]

    if "post_id_mismatch" in errors:
        if not identity_verified:
            return None, [{"rule": "post_id_identity_not_verified"}]
        audit.append({"rule": "verified_post_id", "path": "post_id", "before": value["post_id"], "after": post["post_id"]})
        value["post_id"] = post["post_id"]

    blocks = {block["block_id"]: block for block in post["blocks"]}
    mapped = evidence_map(value)
    for error in errors:
        if not error.endswith(":non_contiguous_quote"):
            continue
        path = error.rsplit(":", 1)[0]
        item = mapped.get(path)
        if item is None:
            return None, audit + [{"rule": "evidence_path_not_found", "path": path}]
        declared = blocks.get(item["block_id"])
        if declared is not None:
            declared_text = declared.get("summary" if declared["type"] == "image" else "text", "")
            if _citation_matches(item["quote"], declared_text):
                audit.append({"rule": "unicode_punctuation_format", "path": path, "block_id": item["block_id"]})
                continue
        matches = []
        for block_id, block in blocks.items():
            original = block.get("summary" if block["type"] == "image" else "text", "")
            if _citation_matches(item["quote"], original):
                matches.append(block_id)
        if len(matches) != 1:
            return None, audit + [{"rule": "block_match_not_unique", "path": path, "candidate_block_ids": matches}]
        before = {"block_id": item["block_id"], "source_type": item["source_type"]}
        target = blocks[matches[0]]
        item["block_id"] = matches[0]
        item["source_type"] = "image_summary" if target["type"] == "image" else "text"
        audit.append({"rule": "unique_block_reassignment", "path": path, "before": before,
                      "after": {"block_id": item["block_id"], "source_type": item["source_type"]}})

    remaining = validate(post, value)
    if remaining:
        return None, audit + [{"rule": "post_repair_validation_failed", "errors": remaining}]
    return value, audit


def identity_verified(post_id, row, post, review, result):
    input_path = ROOT / row["input_path"]
    input_record = next((item for item in result.get("inputs", []) if item.get("path") == row["input_path"]), None)
    return all((
        row["post_id"] == post_id,
        post["post_id"] == post_id,
        review.get("post_id") == post_id,
        row["input_sha256"] == hash_file(input_path),
        input_record is not None,
        input_record.get("sha256") == row["input_sha256"],
        result.get("task_id") == "a016-single-" + post_id,
        result.get("change_id") == CHANGE.name,
        isinstance(result.get("request_fingerprint"), str),
        isinstance(review.get("cache_key"), str),
    ))


def packet(row):
    return {
        "task_id": "a016-repair-" + row["post_id"],
        "change_id": CHANGE.name,
        "task_refs": ["7.4"],
        "prompt_file": shared.rel(OUT / "full-v2.3.md"),
        "context_files": [row["input_path"]],
        "schema_file": shared.rel(OUT / "output.wire.schema.json"),
        "response_type": "json",
        **shared.PARAMS,
    }


def source_snapshot(failure_ids):
    calls = {}
    for post_id in failure_ids:
        directory = SOURCE / "calls" / post_id
        calls[post_id] = {
            item.name: hash_file(item)
            for item in directory.iterdir()
            if item.is_file()
        }
    return {
        "key_files": {name: hash_file(SOURCE / name) for name in KEY_SOURCE_FILES},
        "failed_calls": calls,
    }


def verify_source_snapshot(snapshot):
    for name, expected in snapshot["key_files"].items():
        if hash_file(SOURCE / name) != expected:
            raise ValueError(f"original source changed: {name}")
    for post_id, files in snapshot["failed_calls"].items():
        for name, expected in files.items():
            if hash_file(SOURCE / "calls" / post_id / name) != expected:
                raise ValueError(f"original call changed: {post_id}/{name}")


def prepare():
    if OUT.exists():
        raise ValueError("refuse overwrite existing repair directory")
    manifest = read(SOURCE / "manifest.json")
    rows = {row["post_id"]: row for row in manifest["rows"]}
    failures = read(SOURCE / "failures.json")
    failure_ids = [record["post_id"] for record in failures]
    if len(failure_ids) != 554 or len(set(failure_ids)) != 554:
        raise ValueError("unexpected failure population")
    all_records = [json.loads(line) for line in (SOURCE / "all-results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    passed_ids = {record["post_id"] for record in all_records if record["state"] == "CONTRACT_PASS"}
    if len(all_records) != 9701 or len(passed_ids) != 9147 or passed_ids.intersection(failure_ids):
        raise ValueError("original pass/failure partition changed")

    OUT.mkdir(parents=True, exist_ok=False)
    PACKETS.mkdir(parents=True, exist_ok=True)
    for name in ("full-v2.3.md", "output.schema.json", "output.wire.schema.json"):
        shutil.copyfile(SOURCE / name, OUT / name)
    snapshot = source_snapshot(failure_ids)
    save(OUT / "original-snapshot.json", snapshot, exclusive=True)

    prepared_rows = []
    counts = {"deterministic_repair": 0, "rerun_once": 0}
    for failure in failures:
        post_id = failure["post_id"]
        row = rows[post_id]
        post = read(ROOT / row["input_path"])
        review_path = SOURCE / "calls" / post_id / "local-review.json"
        result_path = SOURCE / "calls" / post_id / "result.json"
        review = read(review_path)
        result = read(result_path)
        fixed = None
        audit = []
        if review.get("payload") is not None:
            fixed, audit = repair_payload(
                post,
                review["payload"],
                failure["errors"],
                identity_verified(post_id, row, post, review, result),
            )
        decision = "deterministic_repair" if fixed is not None else "rerun_once"
        counts[decision] += 1
        item = {
            "post_id": post_id,
            "input_path": row["input_path"],
            "input_sha256": row["input_sha256"],
            "original_errors": failure["errors"],
            "original_review_sha256": hash_file(review_path),
            "original_result_sha256": hash_file(result_path),
            "original_payload_sha256": hash_value(review.get("payload")),
            "decision": decision,
            "audit": audit,
        }
        if fixed is not None:
            repaired_path = OUT / "repaired" / f"{post_id}.json"
            save(repaired_path, fixed, exclusive=True)
            item.update(repaired_path=shared.rel(repaired_path), repaired_payload_sha256=hash_value(fixed))
        else:
            task = packet(row)
            packet_path = PACKETS / f"{post_id}.json"
            save(packet_path, task, exclusive=True)
            item["packet_path"] = shared.rel(packet_path)
        prepared_rows.append(item)

    repair_manifest = {
        "experiment": "single-v23-full-repair1",
        "source_run": shared.rel(SOURCE),
        "source_manifest_sha256": hash_file(SOURCE / "manifest.json"),
        "source_failures_sha256": hash_file(SOURCE / "failures.json"),
        "planned_failures": 554,
        "original_contract_pass": 9147,
        "counts": counts,
        "model": shared.MODEL,
        "parameters": shared.PARAMS,
        "max_reruns_per_post": 1,
        "workers_max": 3,
        "semantic_accuracy": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": prepared_rows,
    }
    save(OUT / "manifest.json", repair_manifest, exclusive=True)
    report()
    print(json.dumps(counts, ensure_ascii=False), flush=True)


def audit():
    manifest = read(OUT / "manifest.json")
    verify_source_snapshot(read(OUT / "original-snapshot.json"))
    if len(manifest["rows"]) != 554 or len({row["post_id"] for row in manifest["rows"]}) != 554:
        raise ValueError("repair manifest population changed")
    for row in manifest["rows"]:
        if hash_file(ROOT / row["input_path"]) != row["input_sha256"]:
            raise ValueError("repair input changed")
        post = read(ROOT / row["input_path"])
        if row["decision"] == "deterministic_repair":
            payload = read(ROOT / row["repaired_path"])
            if hash_value(payload) != row["repaired_payload_sha256"] or validate(post, payload):
                raise ValueError("repaired payload invalid")
        else:
            task = read(ROOT / row["packet_path"])
            if task != packet({"post_id": row["post_id"], "input_path": row["input_path"]}):
                raise ValueError("rerun packet changed")
            shared.delegate.prepare_task(ROOT, task)
    return manifest


def execute_rerun(row, endpoint):
    task = read(ROOT / row["packet_path"])
    prepared = shared.delegate.prepare_task(ROOT, task)
    fingerprint = shared.digest({
        "task": task,
        "inputs": prepared["inputs"],
        "parameters": prepared["parameters"],
        "model": shared.MODEL,
        "endpoint": endpoint,
        "messages": prepared["messages"],
    })
    destination = OUT / "calls" / row["post_id"]
    if destination.exists():
        review_path = destination / "local-review.json"
        if not review_path.exists():
            raise ValueError("uncertain interrupted rerun; no second request")
        review = read(review_path)
        if review["cache_key"] != fingerprint:
            raise ValueError("cached rerun request changed")
        return review
    model, base, _ = shared.delegate.load_connection(shared.SETTINGS, shared.ENV)
    if model != shared.MODEL or hashlib.sha256(base.encode()).hexdigest() != endpoint:
        raise ValueError("connection changed")
    record = shared.delegate.dispatch(ROOT, task, shared.rel(destination), shared.SETTINGS, shared.ENV)
    payload = read(destination / "response.json") if record["state"] == "REVIEW_REQUIRED" else None
    if payload is not None:
        payload = normalise_for_contract(payload)
    errors = validate(read(ROOT / row["input_path"]), payload) if payload is not None else [record.get("error", "api_failed")]
    if record.get("inputs_changed_after_request"):
        errors.append("inputs_changed_after_request")
    review = {
        "post_id": row["post_id"],
        "state": "CONTRACT_PASS" if not errors else "FAILED",
        "cache_key": fingerprint,
        "schema_parsed": payload is not None,
        "payload": payload,
        "errors": errors,
        "original_errors": row["original_errors"],
        "usage": record.get("usage"),
        "elapsed_s": record.get("elapsed_s"),
        "http_status": record.get("http_status"),
        "error_detail": record.get("error_detail"),
        "semantic_acceptance": "NOT_MEASURED",
    }
    save(destination / "local-review.json", review, exclusive=True)
    return review


def run(workers=3):
    if workers > 3:
        raise ValueError("workers exceed approved maximum")
    manifest = audit()
    model, base, _ = shared.delegate.load_connection(shared.SETTINGS, shared.ENV)
    if model != shared.MODEL:
        raise ValueError("model mismatch")
    endpoint = hashlib.sha256(base.encode()).hexdigest()
    queue = iter(row for row in manifest["rows"] if row["decision"] == "rerun_once" and not (OUT / "calls" / row["post_id"]).exists())
    pending = {}
    stopped = False
    consecutive_transport_failures = 0
    started = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        def fill():
            while not stopped and len(pending) < workers:
                try:
                    row = next(queue)
                except StopIteration:
                    return
                pending[pool.submit(execute_rerun, row, endpoint)] = row

        fill()
        while pending:
            done, _ = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
            for future in done:
                row = pending.pop(future)
                try:
                    review = future.result()
                    transport = review["errors"] == ["api_transport_or_json_error"]
                    consecutive_transport_failures = consecutive_transport_failures + 1 if transport else 0
                    if review.get("http_status") in {400, 401, 403, 429} or consecutive_transport_failures >= 3:
                        stopped = True
                    print(json.dumps({"post_id": row["post_id"], "state": review["state"],
                                      "errors": review["errors"][:3]}, ensure_ascii=False), flush=True)
                except Exception as error:
                    stopped = True
                    save(OUT / f"controller-error-{row['post_id']}.json", {
                        "post_id": row["post_id"],
                        "exception_type": type(error).__name__,
                        "no_retry": True,
                    })
            report()
            fill()
    save(OUT / "timing.json", {
        "elapsed_s": time.time() - started,
        "circuit_stopped": stopped,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    print(json.dumps(report(), ensure_ascii=False), flush=True)


def report():
    manifest = read(OUT / "manifest.json")
    if (OUT / "original-snapshot.json").exists():
        verify_source_snapshot(read(OUT / "original-snapshot.json"))
    original_text = (SOURCE / "all-results.jsonl").read_text(encoding="utf-8")
    original_lines = [line for line in original_text.splitlines(keepends=True) if line.strip()]
    source_records = {json.loads(line)["post_id"]: (line, json.loads(line)) for line in original_lines}
    rows = {row["post_id"]: row for row in manifest["rows"]}
    merged_lines = []
    passed_payloads = []
    resolutions = []
    rerun_reviews = {}
    if (OUT / "calls").exists():
        rerun_reviews = {path.parent.name: read(path) for path in (OUT / "calls").glob("*/local-review.json")}

    for line in original_lines:
        source = json.loads(line)
        post_id = source["post_id"]
        row = rows.get(post_id)
        if row is None:
            merged_lines.append(line)
            if source["state"] == "CONTRACT_PASS":
                passed_payloads.append(source["payload"])
            continue
        if row["decision"] == "deterministic_repair":
            payload = read(ROOT / row["repaired_path"])
            final = {**source, "state": "CONTRACT_PASS", "payload": payload, "errors": [],
                     "resolution": {"type": "deterministic_repair", "source_post_id": post_id,
                                    "audit": row["audit"]}}
        elif post_id in rerun_reviews:
            review = rerun_reviews[post_id]
            final = {**source, "state": review["state"], "payload": review["payload"], "errors": review["errors"],
                     "usage": review.get("usage"),
                     "resolution": {"type": "rerun_once", "source_post_id": post_id}}
        else:
            final = {**source, "resolution": {"type": "rerun_pending", "source_post_id": post_id}}
        merged_lines.append(json.dumps(final, ensure_ascii=False) + "\n")
        if final["state"] == "CONTRACT_PASS":
            passed_payloads.append(final["payload"])
        resolutions.append({"post_id": post_id, "decision": row["decision"], "state": final["state"],
                            "errors": final.get("errors", []), "audit": row["audit"]})

    merged_ids = [json.loads(line)["post_id"] for line in merged_lines]
    if len(merged_ids) != 9701 or len(set(merged_ids)) != 9701:
        raise ValueError("merged coverage invalid")
    unchanged_pass = all(
        merged_lines[index] == original_lines[index]
        for index, (_, record) in enumerate(source_records.values())
        if record["state"] == "CONTRACT_PASS"
    )
    if not unchanged_pass:
        raise ValueError("original pass record changed")
    (OUT / "merged-all-results.jsonl").write_text("".join(merged_lines), encoding="utf-8")
    (OUT / "contract-passed.jsonl").write_text(
        "".join(json.dumps(payload, ensure_ascii=False) + "\n" for payload in passed_payloads), encoding="utf-8"
    )
    save(OUT / "resolutions.json", resolutions)
    rerun_planned = sum(row["decision"] == "rerun_once" for row in manifest["rows"])
    summary = {
        "planned_posts": 9701,
        "original_contract_pass": 9147,
        "deterministic_repairs": sum(row["decision"] == "deterministic_repair" for row in manifest["rows"]),
        "rerun_planned": rerun_planned,
        "rerun_closed": len(rerun_reviews),
        "rerun_contract_pass": sum(review["state"] == "CONTRACT_PASS" for review in rerun_reviews.values()),
        "rerun_failures": sum(review["state"] != "CONTRACT_PASS" for review in rerun_reviews.values()),
        "rerun_pending": rerun_planned - len(rerun_reviews),
        "final_contract_pass": len(passed_payloads),
        "final_failures_or_pending": 9701 - len(passed_payloads),
        "original_pass_records_byte_unchanged": unchanged_pass,
        "source_snapshot_valid": True,
        "semantic_accuracy": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save(OUT / "progress.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "dry-run", "run", "report"))
    parser.add_argument("--workers", type=int, default=3, choices=(1, 2, 3))
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        prepare()
    elif arguments.command == "dry-run":
        manifest = audit()
        print(json.dumps(manifest["counts"], ensure_ascii=False))
    elif arguments.command == "run":
        run(arguments.workers)
    else:
        print(json.dumps(report(), ensure_ascii=False))


if __name__ == "__main__":
    main()
