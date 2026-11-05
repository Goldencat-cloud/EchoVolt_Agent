"""Run the approved full V2.3 single-post extraction over all frozen inputs."""
from __future__ import annotations

import concurrent.futures as cf
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools import auto016_run_v23 as shared
from tools import auto016_single_v23_200 as single

ROOT = shared.ROOT
BASE = shared.BASE
OUT = BASE / "single-v23-full"
PACKETS = shared.CHANGE / "delegations/single-v23-full"
SOURCE = shared.SOURCE


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    else:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def build_input(record):
    source = record["post_input"]
    title = source["title"]
    blocks = [{"block_id": "T0", "type": "text", "text": title}]
    text_i, image_i = 1, 0
    dropped_images = 0
    for item in source["sequence"]:
        kind = item["type"]
        if kind == "text":
            key, block_id = "text", f"T{text_i}"
            text_i += 1
        elif kind == "image":
            if not isinstance(item.get("summary"), str) or not item["summary"].strip():
                # Preserve the post while excluding an image with no usable
                # integrated summary; sending a fabricated placeholder would
                # create false evidence.
                dropped_images += 1
                continue
            key, block_id = "summary", f"I{image_i}"
            image_i += 1
        else:
            raise ValueError(f"unexpected block type: {kind}")
        value = item[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"empty {kind} block for {record['post_id']}")
        blocks.append({"block_id": block_id, "type": kind, key: value})
    return {"post_id": record["post_id"], "title": title,
            "created_at": record.get("created_at"), "blocks": blocks}, image_i, dropped_images


def prepare():
    if OUT.exists():
        raise ValueError("refuse overwrite existing full-run directory")
    single.OUT, single.PACKETS = OUT, PACKETS
    records = {}
    with SOURCE.open(encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                if record["post_id"] in records:
                    raise ValueError("duplicate source post ID")
                records[record["post_id"]] = record
    OUT.mkdir(parents=True, exist_ok=False)
    PACKETS.mkdir(parents=True, exist_ok=True)
    prompt = shared.PROMPTS / "full-v2.3.md"
    schema = shared.SCHEMAS / "post-output-v2.3.json"
    shutil.copyfile(prompt, OUT / "full-v2.3.md")
    shutil.copyfile(schema, OUT / "output.schema.json")
    save(OUT / "output.wire.schema.json", shared.wire_schema(read(schema)), exclusive=True)
    rows = []
    for pid in sorted(records):
        post, images, dropped_images = build_input(records[pid])
        input_path = OUT / "inputs" / f"{pid}.json"
        save(input_path, post, exclusive=True)
        row = {"post_id": pid, "input_path": shared.rel(input_path),
               "input_sha256": shared.hash_file(input_path), "images": images,
               "source_record_sha256": shared.digest(records[pid]),
               "dropped_image_summaries": dropped_images}
        rows.append(row)
        save(PACKETS / f"{pid}.json", single.packet(row), exclusive=True)
    manifest = {"experiment": "single-v23-full", "sample_size": len(rows),
                "sample_source": "all frozen records from auto008 model_inputs.jsonl",
                "rows": rows, "source_sha256": shared.hash_file(SOURCE),
                "prompt_sha256": shared.hash_file(OUT / "full-v2.3.md"),
                "schema_sha256": shared.hash_file(OUT / "output.schema.json"),
                "model": shared.MODEL, "parameters": shared.PARAMS,
                "dropped_image_summaries": sum(r["dropped_image_summaries"] for r in rows),
                "prompt_as_system": True, "stable_prompt_prefix": True,
                "no_retries": True, "created_at": datetime.now(timezone.utc).isoformat()}
    save(OUT / "manifest.json", manifest, exclusive=True)
    print(json.dumps({"prepared": len(rows), "image_posts": sum(r["images"] > 0 for r in rows)}, ensure_ascii=False), flush=True)


def summary():
    reviews = [read(p) for p in (OUT / "calls").glob("*/local-review.json")]
    usage = [r.get("usage") or {} for r in reviews]
    result = {"planned_posts": len(read(OUT / "manifest.json")["rows"]),
              "closed_posts": len(reviews), "actual_requests": sum(r.get("api_calls", 1) for r in reviews),
              "schema_parsed": sum(bool(r.get("schema_parsed")) for r in reviews),
              "contract_pass": sum(r.get("state") == "CONTRACT_PASS" for r in reviews),
              "failures": sum(r.get("state") != "CONTRACT_PASS" for r in reviews),
              "pending": len(read(OUT / "manifest.json")["rows"]) - len(reviews),
              "tokens": {k: sum(v.get(k, 0) for v in usage) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
              "cached_tokens": sum(v.get("prompt_tokens_details", {}).get("cached_tokens", 0) for v in usage),
              "usage_unknown": sum(not r.get("usage") for r in reviews),
              "semantic_accuracy": None, "updated_at": datetime.now(timezone.utc).isoformat()}
    save(OUT / "progress.json", result)
    return result


def run(workers=3):
    single.OUT, single.PACKETS = OUT, PACKETS
    manifest = read(OUT / "manifest.json")
    model, base, _ = shared.delegate.load_connection(shared.SETTINGS, shared.ENV)
    if model != shared.MODEL:
        raise ValueError("model mismatch")
    endpoint = hashlib.sha256(base.encode()).hexdigest()
    started = time.time()
    stopped = False
    # Resume only never-started posts. A call directory without a review may
    # represent an accepted remote request interrupted locally; never resend it.
    interrupted = [r["post_id"] for r in manifest["rows"]
                   if (OUT / "calls" / r["post_id"]).exists()
                   and not (OUT / "calls" / r["post_id"] / "local-review.json").exists()]
    save(OUT / "interrupted-requests.json", {"post_ids": interrupted, "no_retry": True})
    queue = iter(r for r in manifest["rows"] if not (OUT / "calls" / r["post_id"]).exists())
    save(OUT / "runtime.json", {"workers": workers, "started_at": datetime.now(timezone.utc).isoformat(),
                               "interrupted_not_retried": interrupted})
    pending = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        def fill():
            while not stopped and len(pending) < workers:
                try:
                    row = next(queue)
                except StopIteration:
                    return
                pending[pool.submit(single.execute, row, endpoint)] = row
        fill()
        while pending:
            done, _ = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
            for future in done:
                row = pending.pop(future)
                try:
                    result = future.result()
                    if result.get("http_status") in {400, 401, 403, 429}:
                        stopped = True
                    print(json.dumps({"post_id": row["post_id"], "state": result.get("state"),
                                      "cache": (result.get("usage") or {}).get("prompt_tokens_details", {}).get("cached_tokens", 0),
                                      "errors": result.get("errors", [])[:2]}, ensure_ascii=False), flush=True)
                except Exception as exc:
                    stopped = True
                    save(OUT / f"controller-error-{row['post_id']}.json",
                         {"post_id": row["post_id"], "exception_type": type(exc).__name__, "no_retry": True})
            summary()
            fill()
    final = summary()
    save(OUT / "timing.json", {"elapsed_s": time.time() - started, "circuit_stopped": stopped,
                                "finished_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps(final, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        run(args.workers)
