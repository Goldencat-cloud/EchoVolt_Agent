# -*- coding: utf-8 -*-
"""Map an image URL within a post to its authoritative ``image_id`` via the 003
manifest, keyed on ``(post_id, url)``. Never guesses by title or enumeration
order. Ambiguous pairs (same post+url -> multiple image_ids) are surfaced, not
resolved by guesswork."""
from collections import defaultdict


def build_pair_map(manifest_rows):
    """Return ``(pair_map, ambiguous_pairs)``.

    ``pair_map`` maps ``(post_id, url) -> image_id`` for uniquely-mapped pairs.
    ``ambiguous_pairs`` is the set of ``(post_id, url)`` keys that map to more
    than one ``image_id`` (caller must not guess for these)."""
    temp = defaultdict(set)
    for r in manifest_rows:
        pid = r.get("post_id")
        url = r.get("url")
        iid = r.get("image_id")
        if not pid or not url or not iid:
            continue
        temp[(pid, url)].add(iid)
    pair_map = {}
    ambiguous = set()
    for key, ids in temp.items():
        if len(ids) == 1:
            pair_map[key] = next(iter(ids))
        else:
            ambiguous.add(key)
    return pair_map, ambiguous


def map_url(pair_map, post_id, url):
    """Return the authoritative image_id for (post_id, url), or None."""
    if url is None:
        return None
    return pair_map.get((post_id, url))
