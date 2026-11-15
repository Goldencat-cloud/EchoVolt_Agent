# -*- coding: utf-8 -*-
"""Build the ordered model sequence from a post's ``multimodal_content``.

Original order is preserved. ``text_block_id = T{orig_index}`` (sparse, where
images/videos occupy indices). Video blocks are EXCLUDED from the model sequence
(spec restricts input to text+image) and recorded in the audit. Every image URL
is walked (not just the curated ``image_ids`` array) so curated-excluded images
with existing AUTO-006/007 results are backfilled at their real positions.
Duplicate positions are kept. Unknown block types are recorded, never guessed.
"""
from . import join
from . import select


def build_sequence(mm_blocks, post_id, pair_map, t006, t007):
    """Return ``(sequence, image_sources, videos_excluded, anomalies)``.

    ``sequence`` holds only text and image blocks (the model input). Image blocks
    carry exactly ``image_id`` and ``summary`` (either may be None).
    """
    sequence = []
    image_sources = []
    videos_excluded = []
    anomalies = []

    for i, block in enumerate(mm_blocks):
        btype = block.get("type")
        value = block.get("v")

        if btype == "text":
            sequence.append({"type": "text", "text_block_id": "T%d" % i, "text": value or ""})

        elif btype == "img":
            image_id = join.map_url(pair_map, post_id, value)
            if image_id is None:
                sequence.append({"type": "image", "image_id": None, "summary": None})
                image_sources.append({
                    "pos": i, "url": value, "image_id": None, "mapped": False,
                    "source": None, "chosen_summary": None,
                    "summary_present": False, "fallback": False,
                    "note": "unmapped_url",
                })
                anomalies.append({
                    "kind": "mapping_anomaly", "pos": i, "url": value,
                    "detail": "(post_id,url) not uniquely present in the 003 manifest",
                })
            else:
                summary, source, note = select.select_summary(image_id, t006, t007)
                sequence.append({"type": "image", "image_id": image_id, "summary": summary})
                image_sources.append({
                    "pos": i, "url": value, "image_id": image_id, "mapped": True,
                    "source": source, "chosen_summary": summary,
                    "summary_present": (summary is not None),
                    "fallback": (source == "AUTO-006-fallback"), "note": note,
                })

        elif btype == "vid":
            videos_excluded.append({"pos": i})

        else:
            anomalies.append({"kind": "unknown_mm_type", "pos": i, "type": btype})

    return sequence, image_sources, videos_excluded, anomalies


def valid_text_block_ids(sequence):
    return {b["text_block_id"] for b in sequence if b.get("type") == "text"}


def valid_image_ids(sequence):
    return {b["image_id"] for b in sequence
            if b.get("type") == "image" and b.get("image_id") is not None}
