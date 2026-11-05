"""image-captioning 产物表读写契约。

契约（specs/image-captioning）：
- image_captions.csv:        image_id, post_id, caption, pixels_used, model, resolution_preset, created_at
- image_captions_errors.csv: image_id, post_id, error_type, detail, attempts

两表均以 image_id 为唯一键；重复写入时保留最后一行（最新状态）。
写盘为原子替换（tmp + os.replace），供推理脚本按批追加、断点续跑使用。
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Mapping

CAPTION_COLUMNS = [
    "image_id", "post_id", "caption", "pixels_used",
    "model", "resolution_preset", "created_at",
]

ERROR_COLUMNS = ["image_id", "post_id", "error_type", "detail", "attempts"]

# 可重试的失败类型（file_missing/decode_error 一般不可重试，但 --retry-errors 语义为"全部失败项重试"）
KEY = "image_id"


def read_table(path: str | os.PathLike[str]) -> list[dict]:
    """读取产物表；不存在或为空返回 []。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def upsert_rows(
    path: str | os.PathLike[str],
    columns: list[str],
    rows: Iterable[Mapping],
) -> int:
    """按 image_id 去重合并写入（后者覆盖前者），原子替换写盘。

    返回写盘后的总行数。
    """
    existing = {r[KEY]: r for r in read_table(path)}
    for row in rows:
        rec = {c: "" for c in columns}
        rec.update({c: row[c] for c in columns if c in row})
        existing[rec[KEY]] = rec
    ordered = sorted(existing.values(), key=lambda r: r[KEY])
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(ordered)
    os.replace(tmp, path)
    return len(ordered)


def load_success_ids(path: str | os.PathLike[str]) -> set[str]:
    """产物表中已有成功描述的 image_id 集合（断点续跑跳过用）。"""
    return {r[KEY] for r in read_table(path) if (r.get("caption") or "").strip()}


def load_failure_ids(path: str | os.PathLike[str]) -> set[str]:
    """失败表中的 image_id 集合（--retry-errors 重试用）。"""
    return {r[KEY] for r in read_table(path) if (r.get("error_type") or "").strip()}


def prune_resolved_errors(
    errors_path: str | os.PathLike[str],
    success_ids: set[str],
) -> int:
    """重试成功后，从失败表移除已进入产物表的 image_id。

    返回移除的行数。
    """
    rows = read_table(errors_path)
    kept = [r for r in rows if r[KEY] not in success_ids]
    removed = len(rows) - len(kept)
    if removed:
        tmp = f"{errors_path}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ERROR_COLUMNS)
            writer.writeheader()
            writer.writerows(kept)
        os.replace(tmp, errors_path)
    return removed
