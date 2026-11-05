# -*- coding: utf-8 -*-
"""Phase 1 (offline, deterministic, no model): build the per-post integration
record. Holds the exact model input + its hash + fingerprint, plus the audit-only
records (per-image source/fallback, video exclusions, mapping anomalies)."""
import json

from . import loader
from . import sequence as seqmod
from . import prompt as promptmod
from . import tokens
from . import util


def build_integration(post_row, pair_map, t006, t007,
                      prompt_text, prompt_sha256, prompt_version,
                      schema_version, chunk_policy_version,
                      model, params, params_fp):
    post_id = str(post_row.get("post_id"))
    title = post_row.get("title") or ""
    source_url = post_row.get("source_url") or ""
    mm = loader.parse_mm(post_row.get("multimodal_content"))

    sequence, image_sources, videos_excluded, anomalies = seqmod.build_sequence(
        mm, post_id, pair_map, t006, t007)

    post_input = {"title": title, "sequence": sequence}
    post_input_json = json.dumps(post_input, ensure_ascii=False)
    post_input_sha256 = util.sha256_text(post_input_json)

    user_content = promptmod.render_user(post_input_json)
    est_prompt = tokens.estimate_tokens(prompt_text)
    est_user = tokens.estimate_tokens(user_content)
    est_input_total = est_prompt + est_user

    fingerprint = util.make_fingerprint(
        post_id, post_input_sha256, prompt_sha256, prompt_version,
        model, params_fp, schema_version, chunk_policy_version)

    return {
        "post_id": post_id,
        "source_url": source_url,
        "title": title,
        "has_images": any(b["type"] == "image" for b in sequence),
        "mm_total_blocks": len(mm),
        "text_block_count": sum(1 for b in sequence if b["type"] == "text"),
        "image_position_count": len(image_sources),
        "video_position_count": len(videos_excluded),
        "sequence": sequence,
        "post_input": post_input,
        "post_input_json": post_input_json,
        "post_input_sha256": post_input_sha256,
        "fingerprint": fingerprint,
        "image_sources": image_sources,
        "videos_excluded": videos_excluded,
        "anomalies": anomalies,
        "est_prompt_tokens": est_prompt,
        "est_user_tokens": est_user,
        "est_input_tokens": est_input_total,
        "est_method": tokens.TOKEN_METHOD,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "model": model,
        "params": params,
        "params_fingerprint": params_fp,
        "schema_version": schema_version,
        "chunk_policy_version": chunk_policy_version,
    }


def build_all_integrations(posts, pair_map, t006, t007,
                           prompt_text, prompt_sha256, prompt_version,
                           schema_version, chunk_policy_version,
                           model, params, params_fp):
    return [
        build_integration(p, pair_map, t006, t007, prompt_text, prompt_sha256,
                          prompt_version, schema_version, chunk_policy_version,
                          model, params, params_fp)
        for p in posts
    ]
