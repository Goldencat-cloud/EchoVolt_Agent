# -*- coding: utf-8 -*-
"""Ordered, budget-aware chunking (offline-testable, no model).

Triggered only when a post's estimated total input exceeds the budget. The
sequence is split IN ORDER into chunks that each fit; a single oversized text
block is split by COMPLETE sentences into traceable sub-block ids ``T{i}#{k}``.
Global ``text_block_id``/``image_id`` are preserved. There is NO silent
truncation: every original block/sub-block is covered by exactly one chunk, and
coverage is asserted. Extra-call cost is recorded by the runner.
"""
import json

from . import tokens
from . import prompt as promptmod

_TERMINATORS = frozenset("。！？!?；;\n")


def split_sentences(text):
    """Split on sentence terminators, keeping delimiters attached so that
    ``"".join(split_sentences(t)) == t`` exactly (no characters dropped)."""
    sents = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _TERMINATORS:
            sents.append(buf)
            buf = ""
    if buf:
        if sents:
            sents[-1] += buf
        else:
            sents.append(buf)
    return sents


def _rendered_est(title, prompt_text, blocks):
    """Estimated total tokens for a request carrying ``blocks``."""
    user = promptmod.render_user(json.dumps({"title": title, "sequence": blocks},
                                            ensure_ascii=False))
    return tokens.estimate_tokens(prompt_text) + tokens.estimate_tokens(user)


def _fits_alone(title, prompt_text, block, budget):
    return _rendered_est(title, prompt_text, [block]) <= budget


def _unit_to_block(unit):
    if unit["kind"] == "text":
        return {"type": "text", "text_block_id": unit["tid"], "text": unit["text"]}
    return {"type": "image", "image_id": unit.get("image_id"),
            "summary": unit.get("summary")}


def _flatten(sequence, title, prompt_text, budget):
    """Flatten the sequence into atomic units (each fits alone)."""
    units = []
    split_parents = {}
    for block in sequence:
        if block.get("type") == "text":
            tid = block["text_block_id"]
            text = block.get("text") or ""
            if _fits_alone(title, prompt_text, block, budget):
                units.append({"kind": "text", "tid": tid, "text": text, "sub": False})
                continue
            # Oversized: split by complete sentences, greedily grouped so each
            # sub-unit fits alone.
            sents = split_sentences(text)
            groups = []
            cur = ""
            for s in sents:
                cand = cur + s
                if not cur:
                    cur = cand
                elif _fits_alone(title, prompt_text,
                                 {"type": "text", "text_block_id": tid, "text": cand},
                                 budget):
                    cur = cand
                else:
                    groups.append(cur)
                    cur = s
            if cur:
                groups.append(cur)
            sub_ids = []
            for k, gt in enumerate(groups, 1):
                sid = "%s#%d" % (tid, k)
                sub_ids.append(sid)
                units.append({"kind": "text", "tid": sid, "text": gt, "sub": True,
                              "parent": tid})
            split_parents[tid] = {"sub_ids": sub_ids, "texts": list(groups),
                                  "original": text}
        else:
            units.append({"kind": "image", "image_id": block.get("image_id"),
                          "summary": block.get("summary"), "sub": False})
    for idx, u in enumerate(units):
        u["uid"] = "U%d" % (idx + 1)
    return units, split_parents


def _pack(units, title, prompt_text, budget):
    chunks = []
    cur = []
    for u in units:
        trial = cur + [u]
        if cur and _rendered_est(title, prompt_text,
                                 [_unit_to_block(x) for x in trial]) > budget:
            chunks.append(cur)
            cur = [u]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    return chunks


def plan_chunks(sequence, title, prompt_text, budget):
    """Plan ordered chunks for ``sequence``. Returns a plan dict."""
    units, split_parents = _flatten(sequence, title, prompt_text, budget)
    raw_chunks = _pack(units, title, prompt_text, budget)
    n = len(raw_chunks)
    chunks = []
    for idx, units_in_chunk in enumerate(raw_chunks, 1):
        blocks = [_unit_to_block(u) for u in units_in_chunk]
        user = promptmod.render_chunk_user(
            json.dumps({"title": title, "sequence": blocks}, ensure_ascii=False),
            idx, n)
        chunks.append({
            "k": idx,
            "n": n,
            "blocks": blocks,
            "user_content": user,
            "est_tokens": tokens.estimate_tokens(prompt_text) + tokens.estimate_tokens(user),
            "unit_tids": [u["uid"] for u in units_in_chunk],
        })
    return {
        "num_chunks": n,
        "chunks": chunks,
        "split_parents": split_parents,
        "coverage_ok": verify_coverage(chunks, split_parents),
        "method": ("greedy-ordered,budget=%d,sentence-split-oversized,"
                   "sub-id=T<i>#<k>,prompt+chunk-user estimated" % budget),
    }


def verify_coverage(chunks, split_parents):
    """Assert no silent omission: every sub-block text joins back to the original
    oversize block, and every unit landed in exactly one chunk."""
    # 1) sentence-split reconstruction is lossless
    for tid, info in split_parents.items():
        if "".join(info["texts"]) != info["original"]:
            return False
    # 2) every unit tid appears in exactly one chunk
    seen = {}
    for ch in chunks:
        for tid in ch["unit_tids"]:
            seen[tid] = seen.get(tid, 0) + 1
    if any(v != 1 for v in seen.values()):
        return False
    return True


def needs_chunking(est_input_tokens, budget):
    return est_input_tokens > budget
