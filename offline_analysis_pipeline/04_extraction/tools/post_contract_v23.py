"""Validate the approved V2.3 post output, without API calls or old-data coercion."""
import json
import copy
import re
import unicodedata
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "openspec/changes/auto-016-modular-post-extraction/schemas/post-output-v2.3.json"


def normalise_for_contract(output):
    """Apply the approved deterministic fallback before contract checks.

    Neutral claims have no sentiment intensity. If the model emits a legacy
    value, coerce it to null at the runner boundary; do not infer semantics.
    The raw API response remains in each call directory's response.json.
    """
    value = copy.deepcopy(output)
    for claim in value.get("claims", []):
        if claim.get("sentiment") == "中性":
            claim["sentiment_intensity"] = None
    return value


def _normalise_citation(value):
    """Normalise harmless formatting drift without rewriting model output."""
    value = unicodedata.normalize("NFKC", value).replace("\u3000", " ")
    value = re.sub(r"\s+", "", value)
    return value.replace("……", "…")


def _strip_format_punctuation(value):
    """Remove only Unicode separators/punctuation for a format-only check.

    Letters, numbers and symbols (for example +, %, ℃) remain significant.
    """
    value = unicodedata.normalize("NFKC", value)
    return "".join(
        char for char in value
        if not char.isspace() and not unicodedata.category(char).startswith(("P", "Z"))
    )


def _citation_matches(quote, original):
    if quote in original:
        return True
    normal_quote, normal_original = _normalise_citation(quote), _normalise_citation(original)
    if normal_quote and normal_quote in normal_original:
        return True
    format_quote = _strip_format_punctuation(quote)
    if format_quote and format_quote in _strip_format_punctuation(original):
        return True
    # Accept a model-added ellipsis only when its non-empty pieces occur in
    # order in the same source block. This is a validator fallback, not a
    # mutation of the returned evidence.
    parts = [p for p in re.split(r"(?:\.\.\.|…)", normal_quote) if p]
    if len(parts) < 2:
        return False
    cursor = 0
    for part in parts:
        position = normal_original.find(part, cursor)
        if position < 0:
            return False
        cursor = position + len(part)
    return True


def validate(post, output):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [f"schema:{'/'.join(map(str, e.path))}:{e.validator}" for e in jsonschema.Draft202012Validator(schema).iter_errors(output)]
    if errors:
        return errors
    if output["post_id"] != post["post_id"]:
        errors.append("post_id_mismatch")
    blocks = {b["block_id"]: b for b in post["blocks"]}

    def evidence(items, path):
        for i, item in enumerate(items):
            block = blocks.get(item["block_id"])
            if block is None or block.get("type") not in {"text", "image"}:
                errors.append(f"{path}/{i}:unknown_or_invalid_block")
                continue
            expected = "image_summary" if block["type"] == "image" else "text"
            original = block.get("summary" if expected == "image_summary" else "text", "")
            if item["source_type"] != expected:
                errors.append(f"{path}/{i}:source_type_mismatch")
            if not item["quote"] or not _citation_matches(item["quote"], original):
                errors.append(f"{path}/{i}:non_contiguous_quote")

    for group in ("products", "claims", "events"):
        ids = [record["id"] for record in output[group]]
        if len(ids) != len(set(ids)):
            errors.append(group + ":duplicate_id")
        for record in output[group]:
            evidence(record["evidence"], group + "/" + record["id"] + "/evidence")
    products = {p["id"] for p in output["products"]}
    events = {e["id"] for e in output["events"]}
    for event in output["events"]:
        if not set(event["related_product_ids"]) <= products:
            errors.append(event["id"] + ":unknown_product")
    evidence(output["user_context"]["evidence"], "user_context/evidence")
    for claim in output["claims"]:
        cid = claim["id"]
        for ref in claim["target_products"]:
            if ref["product_id"] not in products:
                errors.append(cid + ":unknown_target")
        if claim["related_event_id"] is not None and claim["related_event_id"] not in events:
            errors.append(cid + ":unknown_event")
        if (claim["related_event_id"] is None) != (claim["event_relation"] is None):
            errors.append(cid + ":event_link_pair_mismatch")
        direction, intensity = claim["sentiment"], claim["sentiment_intensity"]
        if direction == "中性" and intensity is not None:
            errors.append(cid + ":neutral_intensity_mismatch")
        elif direction == "不明确" and intensity != "无法判断":
            errors.append(cid + ":unknown_intensity_mismatch")
        elif direction not in {"中性", "不明确"} and intensity is None:
            errors.append(cid + ":emotional_intensity_missing")
        context = claim["usage_context"]
        if context is not None:
            evidence(context["evidence"], cid + "/usage_context/evidence")
        comparison = claim["comparison"]
        if comparison is None:
            continue
        participants = set(comparison["product_ids"])
        if not participants <= products:
            errors.append(cid + ":comparison_unknown_product")
        seen = set()
        for i, relation in enumerate(comparison["relations"]):
            subject, obj = relation["subject_product_id"], relation["object_product_id"]
            if subject == obj:
                errors.append(cid + ":comparison_self_relation")
            if not {subject, obj} <= participants:
                errors.append(cid + ":comparison_participant_mismatch")
            # Normalize inverses to reject the same statement written twice.
            kind = relation["relation"]
            if kind == "弱于":
                subject, obj, kind = obj, subject, "优于"
            if kind in {"相当", "存在差异但方向不明", "无法判断"}:
                subject, obj = sorted((subject, obj))
            key = (subject, obj, relation["aspect"])
            if key in seen:
                errors.append(cid + ":comparison_duplicate_or_conflicting_pair")
            seen.add(key)
            evidence(relation["evidence"], f"{cid}/comparison/{i}/evidence")
    return errors
