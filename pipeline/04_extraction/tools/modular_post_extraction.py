"""AUTO-016: single-post evidence-first extraction utilities and runner.

The default mode is deterministic preparation/validation. ``--run`` enables
Qwen calls only for an explicit sampled input and keeps every stage cached.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Any, Iterable

EXTRACTION = Path(__file__).resolve().parents[1]      # 04_extraction
PIPELINE = EXTRACTION.parent                          # pipeline（管道根）
ROOT = PIPELINE.parent                                # 仓库根
DEFAULT_INPUT = PIPELINE / "03_media" / "source_metadata" / "004_A4_图片策展_主链路终版.csv"
DEFAULT_SEED = 20261016
STAGES = ("candidate", "post_pack")
PROMPT_DIR = EXTRACTION / "prompts"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_json(value: str, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def make_blocks(row: dict[str, str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    title = row.get("title", "")
    if title:
        blocks.append({"block_id": "T0", "type": "title", "text": title})
    content = parse_json(row.get("multimodal_content", ""), [])
    local_paths = parse_json(row.get("image_local_paths", ""), [])
    if not isinstance(local_paths, list):
        local_paths = []
    if not isinstance(content, list):
        content = []
    text_index = 1
    image_index = 0
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        value = item.get("v", item.get("text", item.get("summary", "")))
        if kind == "text":
            blocks.append({"block_id": f"T{text_index}", "type": "text", "text": str(value or "")})
            text_index += 1
        elif kind == "img":
            local_path = local_paths[image_index] if image_index < len(local_paths) else None
            blocks.append({"block_id": f"I{image_index}", "type": "image", "summary": "", "source": str(value or ""), "local_path": local_path})
            image_index += 1
    if not blocks and row.get("text_content"):
        blocks.append({"block_id": "T0", "type": "text", "text": row["text_content"]})
    return blocks


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    post_id = str(row.get("post_id", ""))
    blocks = make_blocks(row)
    return {
        "post_id": post_id,
        "created_at": row.get("created_at") or None,
        "title": row.get("title") or None,
        "blocks": blocks,
        "source_file": "004_A4_图片策展_主链路终版.csv",
    }


def load_posts(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [normalize_row(row) for row in csv.DictReader(handle) if row.get("post_id")]


def sample_posts(posts: Iterable[dict[str, Any]], n: int = 100, seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    ordered = sorted(posts, key=lambda item: item["post_id"])
    if n > len(ordered):
        raise ValueError(f"sample size {n} exceeds {len(ordered)} posts")
    rng = random.Random(seed)
    return rng.sample(ordered, n)


def input_hash(post: dict[str, Any]) -> str:
    return sha256({k: post[k] for k in ("post_id", "created_at", "title", "blocks")})


def cache_key(post: dict[str, Any], stage: str, prompt_version: str, schema_version: str, model: str, image_config: dict[str, Any] | None = None) -> str:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    return sha256({"input_hash": input_hash(post), "stage": stage, "prompt_version": prompt_version,
                   "schema_version": schema_version, "model": model, "image_config": image_config or {}})


def prompt_fingerprint(stage: str) -> str:
    path = PROMPT_DIR / ("candidate-v1.md" if stage == "candidate" else "post-pack-v1.md")
    return sha256(path.read_bytes() + b"\n" + (PROMPT_DIR / "source-v2.1.md").read_bytes())


def block_index(post: dict[str, Any]) -> dict[str, str]:
    return {block["block_id"]: str(block.get("summary", "") if block.get("type") == "image" else block.get("text", "")) for block in post.get("blocks", []) if block.get("type") in {"text", "image"}}


def validate_evidence(post: dict[str, Any], evidence: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, list):
        return ["evidence_not_array"]
    index = block_index(post)
    for position, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{position}]_not_object")
            continue
        block_id, quote = item.get("block_id"), item.get("quote")
        if block_id not in index:
            errors.append(f"evidence[{position}]_unknown_block")
        elif not isinstance(quote, str) or not quote or quote not in index[block_id]:
            errors.append(f"evidence[{position}]_non_contiguous_quote")
        expected = next(("image_summary" if b.get("type") == "image" else "text" for b in post.get("blocks", []) if b.get("block_id") == block_id), None)
        if item.get("source_type") not in {"text", "image_summary"} or item.get("source_type") != expected:
            errors.append(f"evidence[{position}]_invalid_source_type")
    return errors


def validate_candidates(post: dict[str, Any], payload: Any) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        return ["candidates_not_array"]
    errors: list[str] = []
    seen: set[str] = set()
    allowed = {"experience", "problem", "need", "evaluation", "comparison", "event_mention", "author_fact", "information", "technical", "industry", "other"}
    for i, candidate in enumerate(payload["candidates"]):
        if not isinstance(candidate, dict):
            errors.append(f"candidate[{i}]_not_object")
            continue
        cid = candidate.get("candidate_id")
        if not isinstance(cid, str) or not cid or cid in seen:
            errors.append(f"candidate[{i}]_duplicate_or_missing_id")
        seen.add(cid)
        if candidate.get("kind") not in allowed:
            errors.append(f"candidate[{i}]_invalid_kind")
        errors.extend(f"candidate[{i}]_{err}" for err in validate_evidence(post, candidate.get("evidence")))
    return errors


def validate_post_pack(post: dict[str, Any], payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["post_pack_not_object"]
    errors: list[str] = []
    import jsonschema
    for error in jsonschema.Draft202012Validator(load_schema("post-pack-v1.json")).iter_errors(payload):
        errors.append("schema:" + "/".join(map(str, error.path)) + ":" + error.validator)
    if payload.get("post_id") != post["post_id"]:
        errors.append("post_id_mismatch")
    for field in ("products", "claims", "events", "user_context"):
        if field not in payload:
            errors.append(f"missing_{field}")
    for field in ("claims", "events"):
        values = payload.get(field, [])
        if not isinstance(values, list):
            errors.append(f"{field}_not_array")
            continue
        for i, value in enumerate(values):
            if isinstance(value, dict):
                errors.extend(f"{field}[{i}]_{err}" for err in validate_evidence(post, value.get("evidence")))
    return errors


@dataclass
class CacheRecord:
    key: str
    stage: str
    state: str
    cache_hit: bool
    started_at: str
    elapsed_s: float
    usage: dict[str, Any]
    error: str | None = None


class StageCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def read(self, key: str) -> dict[str, Any] | None:
        path = self.path(key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if value.get("validated") is True else None

    def write(self, key: str, value: dict[str, Any]) -> None:
        temp = self.path(key).with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path(key))


def stage_prompt(stage: str, post: dict[str, Any], candidate: dict[str, Any] | None = None) -> str:
    prompt_file = PROMPT_DIR / ("candidate-v1.md" if stage == "candidate" else "post-pack-v1.md")
    base = prompt_file.read_text(encoding="utf-8").strip()
    taxonomy = (PROMPT_DIR / "source-v2.1.md").read_text(encoding="utf-8-sig")
    if stage == "candidate":
        return base + "\n\n" + taxonomy + "\n\n输入帖子：\n" + canonical(post)
    return base + "\n\n" + taxonomy + "\n\n输入：\n" + canonical({"post": post, "candidates": candidate or {}})


def run_qwen_json(prompt: str, schema: dict[str, Any], settings: Path, env_file: Path, model: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the existing configured Qwen connection without changing its settings."""
    from tools import qwen_delegate

    configured_model, base, key = qwen_delegate.load_connection(settings, env_file)
    if configured_model != model:
        model = configured_model
    payload = {"model": model, "messages": [{"role": "system", "content": "只输出符合 schema 的合法 JSON。"}, {"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 4096, "stream": False,
               "response_format": {"type": "json_schema", "json_schema": {"name": "post_extraction", "strict": True, "schema": schema}}}
    started = time.perf_counter()
    response, status = qwen_delegate.call_api(base, key, payload, timeout=300)
    content = response["choices"][0]["message"].get("content", "")
    parsed = json.loads(content)
    return parsed, {"http_status": status, "elapsed_s": time.perf_counter() - started, "usage": qwen_delegate.safe_usage(response.get("usage", {})), "model": response.get("model", model)}


def load_schema(name: str) -> dict[str, Any]:
    path = EXTRACTION / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def adapt_v21(post: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Preserve every original V2.1 field; reject lossy or invalid packages."""
    errors = validate_post_pack(post, pack)
    if errors:
        raise ValueError("invalid V2.1 package: " + str(errors[:3]))
    return json.loads(json.dumps(pack, ensure_ascii=False))


def process_post(post: dict[str, Any], cache: StageCache, settings: Path, env_file: Path, model: str = "qwen3.8-27b", allow_api: bool = False) -> dict[str, Any]:
    """Run or prepare both stages for one post; never overwrites valid cache."""
    result: dict[str, Any] = {"post_id": post["post_id"], "input_hash": input_hash(post), "stages": {}}
    candidate_key = cache_key(post, "candidate", prompt_fingerprint("candidate"), "candidate-v1", model)
    candidate = cache.read(candidate_key)
    if candidate is None:
        if not allow_api:
            result["stages"]["candidate"] = {"state": "PENDING", "cache_key": candidate_key, "skip_reason": "api_disabled"}
            return result
        payload, usage = run_qwen_json(stage_prompt("candidate", post), load_schema("candidate-v1.json"), settings, env_file, model)
        errors = validate_candidates(post, payload)
        if errors:
            raise ValueError(f"candidate quality gate failed: {errors[:3]}")
        candidate = {"validated": True, "stage": "candidate", "payload": payload, "usage": usage, "cache_key": candidate_key, "created_at": datetime.now(timezone.utc).isoformat()}
        cache.write(candidate_key, candidate)
    result["stages"]["candidate"] = {"state": "CACHED" if candidate else "PENDING", "cache_key": candidate_key, "usage": candidate.get("usage", {}) if candidate else {}}
    candidate_payload = candidate["payload"]
    post_key = cache_key(post, "post_pack", prompt_fingerprint("post_pack"), "post-pack-v1", model)
    pack = cache.read(post_key)
    if pack is None:
        if not allow_api:
            result["stages"]["post_pack"] = {"state": "PENDING", "cache_key": post_key, "skip_reason": "api_disabled"}
            return result
        payload, usage = run_qwen_json(stage_prompt("post_pack", post, candidate_payload), load_schema("post-pack-v1.json"), settings, env_file, model)
        errors = validate_post_pack(post, payload)
        if errors:
            raise ValueError(f"post pack quality gate failed: {errors[:3]}")
        pack = {"validated": True, "stage": "post_pack", "payload": payload, "usage": usage, "cache_key": post_key, "created_at": datetime.now(timezone.utc).isoformat()}
        cache.write(post_key, pack)
    result["stages"]["post_pack"] = {"state": "CACHED" if pack else "PENDING", "cache_key": post_key, "usage": pack.get("usage", {}) if pack else {}}
    result["v21"] = adapt_v21(post, pack["payload"])
    return result


def prepare_sample(input_path: Path, output_dir: Path, n: int = 100, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    posts = load_posts(input_path)
    sample = sample_posts(posts, n, seed)
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for post in sample:
        (inputs / f"{post['post_id']}.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"change_id": "auto-016-modular-post-extraction", "input_file": str(input_path), "input_sha256": sha256(input_path.read_bytes()),
                "sample_size": n, "seed": seed, "post_ids": [p["post_id"] for p in sample], "created_at": datetime.now(timezone.utc).isoformat(),
                "posts": [{"post_id": p["post_id"], "input_hash": input_hash(p), "blocks": len(p["blocks"])} for p in sample]}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=EXTRACTION / "results" / "modular-post-extraction")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("command", choices=("prepare", "validate-sample", "plan-run"))
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare_sample(args.input, args.output, args.sample_size, args.seed)
        print(json.dumps({"state": "prepared", "sample_size": manifest["sample_size"], "seed": manifest["seed"], "output": str(args.output)}, ensure_ascii=False))
        return 0
    if args.command == "plan-run":
        manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
        cache = StageCache(args.output / "cache")
        planned = []
        for post_id in manifest["post_ids"]:
            post = json.loads((args.output / "inputs" / f"{post_id}.json").read_text(encoding="utf-8"))
            planned.append(process_post(post, cache, ROOT / "local-config/settings.json", ROOT / "local-config/.env", allow_api=False))
        (args.output / "run-plan.json").write_text(json.dumps({"state": "planned", "items": planned}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"state": "planned", "posts": len(planned), "api_calls": 0, "cache_dir": str(args.output / "cache")}, ensure_ascii=False))
        return 0
    manifest_path = args.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    posts = [json.loads((args.output / "inputs" / f"{post_id}.json").read_text(encoding="utf-8")) for post_id in manifest["post_ids"]]
    errors = {p["post_id"]: validate_evidence(p, []) for p in posts}
    print(json.dumps({"state": "validated", "posts": len(posts), "errors": errors}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
