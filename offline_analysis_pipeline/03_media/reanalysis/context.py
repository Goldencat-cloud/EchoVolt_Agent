# -*- coding: utf-8 -*-
"""Near-anchor text selection, budget accounting, and bounded one-shot expansion.

The model is fed ONLY the post title + text fragments near the target image's
anchor (within a text-token budget). If the model signals it needs more, the
program selects relevant REMAINING same-post text at most once. All token
accounting uses the labelled conservative estimator (see tokens.py).
"""
from . import tokens as tok
from .config import (
    INITIAL_TEXT_TOKEN_BUDGET,
    EXPANSION_NEW_TOKEN_BUDGET,
    TOTAL_TEXT_TOKEN_BUDGET,
)


def _text_segments(mm):
    """[(index, text)] for non-empty text entries, in post order."""
    segs = []
    for i, e in enumerate(mm):
        if isinstance(e, dict) and e.get("type") == "text":
            v = e.get("v") or ""
            if v.strip():
                segs.append((i, v))
    return segs


def _proximity_order(segs, anchor_idx):
    """Order segment indices by closeness to the anchor (nearest first).

    Equal-distance ties put the 'before' side first. Returns
    ``[(index, text, side, distance), ...]`` nearest-first.
    """
    cand = []
    for idx, text in segs:
        if idx < anchor_idx:
            side, dist = "before", anchor_idx - idx
        elif idx > anchor_idx:
            side, dist = "after", idx - anchor_idx
        else:
            continue
        cand.append((dist, 0 if side == "before" else 1, idx, text, side))
    cand.sort(key=lambda t: (t[0], t[1]))
    return [(idx, text, side, dist) for dist, _, idx, text, side in cand]


def _largest_prefix_fit(text, remaining):
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tok.estimate_tokens(text[:mid]) <= remaining:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _smallest_suffix_fit(text, remaining):
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if tok.estimate_tokens(text[mid:]) <= remaining:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _fit_near_portion(text, remaining, side):
    """Return (char_start, char_end, portion) of the anchor-near side that fits.

    'after' -> anchor-near is the PREFIX; 'before' -> the SUFFIX.
    """
    if side == "after":
        end = _largest_prefix_fit(text, remaining)
        if end < 1:
            return None
        return 0, end, text[:end]
    start = _smallest_suffix_fit(text, remaining)
    if len(text) - start < 1:
        return None
    return start, len(text), text[start:]


def select_initial_context(entry, budget=INITIAL_TEXT_TOKEN_BUDGET):
    """Pick title + near-anchor text fragments within the text-token budget.

    Selection is by proximity (nearest first); returned fragments are presented
    in post order (ascending mm index). A fragment that does not fit is reduced
    to its anchor-near portion; the trimmed char range is recorded.
    """
    mm = entry["mm"]
    anchor = entry["anchor_idx"]
    title = entry.get("title") or ""
    order = _proximity_order(_text_segments(mm), anchor)

    fragments = {}
    used = tok.estimate_tokens(title)
    for idx, text, side, _dist in order:
        if used >= budget:
            break
        remaining = budget - used
        t = tok.estimate_tokens(text)
        if t <= remaining:
            fragments[idx] = {"side": side, "char_start": 0, "char_end": len(text), "text": text}
            used += t
        else:
            portion = _fit_near_portion(text, remaining, side)
            if portion:
                cs, ce, pt = portion
                fragments[idx] = {
                    "side": side, "char_start": cs, "char_end": ce, "text": pt, "trimmed": True,
                }
                used += tok.estimate_tokens(pt)
            break  # the nearest segment cannot fit -> farther ones are worse

    frags_sorted = [dict({"mm_index": idx}, **fragments[idx]) for idx in sorted(fragments)]
    return {
        "round": "initial",
        "title": title,
        "source_url": entry.get("source_url") or "",
        "anchor_idx": anchor,
        "fragments": frags_sorted,
        "tokens_title": tok.estimate_tokens(title),
        "tokens_used": used,
        "tokens_budget": budget,
        "estimated": True,
        "method": tok.TOKEN_METHOD,
        "selected_mm_indexes": sorted(fragments),
    }


# High-frequency Chinese function characters (particles/pronouns/conjunctions/
# auxiliaries) that would otherwise cause spurious single-char overlap in the
# expansion relevance matcher. Deliberately small and conservative.
_STOP_CJK = set(
    "的一了是不在有和这那他她它们你我您自己其之与及或而且但就被把到从对于等个"
    "么吗呢吧啊哦嗯呀嘛很太最更挺又还都也再才便只刚已经曾经常往往每"
)


def _tokenize_for_match(s):
    toks = []
    buf = ""
    for ch in s:
        if tok._is_cjk(ord(ch)):
            if buf:
                toks.append(buf.lower())
                buf = ""
            if ch not in _STOP_CJK:
                toks.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                toks.append(buf.lower())
                buf = ""
    if buf:
        toks.append(buf.lower())
    return toks


def select_expansion(entry, initial_bundle, query,
                      new_budget=EXPANSION_NEW_TOKEN_BUDGET,
                      total_budget=TOTAL_TEXT_TOKEN_BUDGET):
    """Select relevant REMAINING same-post text for a one-shot expansion.

    Scores remaining text segments by lexical overlap with ``query``; takes the
    most relevant within the new budget (respecting the total budget). Returns
    an expansion bundle, or ``None`` if no relevant remaining fragment fits
    (=> the caller records the semantic result as insufficient evidence).
    """
    mm = entry["mm"]
    anchor = entry["anchor_idx"]
    used = initial_bundle["tokens_used"]
    remaining_budget = min(total_budget - used, new_budget)
    if remaining_budget <= 0:
        return None
    already = set(initial_bundle["selected_mm_indexes"])
    segs = [(i, t) for (i, t) in _text_segments(mm) if i not in already]
    if not segs:
        return None
    qtoks = set(_tokenize_for_match(query or ""))
    if not qtoks:
        return None
    scored = []
    for idx, text in segs:
        overlap = len(qtoks & set(_tokenize_for_match(text)))
        if overlap > 0:
            scored.append((-overlap, abs(idx - anchor), idx, text))
    if not scored:
        return None
    scored.sort()

    fragments = {}
    new_used = 0
    for _neg, _dist, idx, text in scored:
        if new_used >= remaining_budget:
            break
        rem = remaining_budget - new_used
        t = tok.estimate_tokens(text)
        side = "before" if idx < anchor else "after"
        if t <= rem:
            fragments[idx] = {"side": side, "char_start": 0, "char_end": len(text), "text": text}
            new_used += t
        else:
            portion = _fit_near_portion(text, rem, side)
            if portion:
                cs, ce, pt = portion
                fragments[idx] = {
                    "side": side, "char_start": cs, "char_end": ce, "text": pt, "trimmed": True,
                }
                new_used += tok.estimate_tokens(pt)
    if not fragments:
        return None
    frags_sorted = [dict({"mm_index": idx}, **fragments[idx]) for idx in sorted(fragments)]
    return {
        "round": "expansion",
        "query": query,
        "fragments": frags_sorted,
        "tokens_new": new_used,
        "tokens_budget_new": new_budget,
        "estimated": True,
        "method": tok.TOKEN_METHOD,
        "selected_mm_indexes": sorted(fragments),
    }


def combined_bundle(initial, exp):
    """Merge initial + expansion fragments (post order) for the round-2 payload."""
    combo = dict(initial)
    combo["round"] = "initial+expansion"
    combo["fragments"] = sorted(
        initial["fragments"] + exp["fragments"], key=lambda f: f["mm_index"]
    )
    combo["tokens_used"] = initial["tokens_used"] + exp["tokens_new"]
    return combo


def render_context_for_prompt(bundle):
    """Render a context bundle to the text block sent to the model."""
    lines = ["帖子标题：" + (bundle.get("title") or "（无）")]
    if bundle.get("source_url"):
        lines.append("帖子来源(source_url)：" + bundle["source_url"])
    for fr in bundle["fragments"]:
        tag = "前文" if fr["side"] == "before" else "后文"
        note = "（节选）" if fr.get("trimmed") else ""
        lines.append("[%s·段%d]%s %s" % (tag, fr["mm_index"], note, fr["text"]))
    return "\n".join(lines)


def provided_text_blob(*bundles):
    """Concatenation of all provided text (titles + fragments) for citation checks."""
    parts = []
    for b in bundles:
        if not b:
            continue
        if b.get("title"):
            parts.append(b["title"])
        for fr in b["fragments"]:
            parts.append(fr["text"])
    return "\n".join(parts)
