"""生成图片描述任务清单 outputs/caption_todo.csv。

输入：
  - data/processed/汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv
    （已清洗语料；images 列为 URL JSON 数组——用户指定以该文件为准）
  - data/processed/image_manifest.csv（url → image_id/local_path 映射）
  - outputs/image_curation/remove_log.csv（status=moved 的图片剔除）

过滤规则（specs/image-captioning「输入图片清单」）：
  1. 只取 curated CSV 中出现、且 manifest 中 status=ok 且无 dup_of 的图片
  2. 剔除 curation 移除（remove_log status=moved）的图片
  3. 本地文件必须存在于 data/images/；缺失者记入失败表（error_type=file_missing）

用法：
  .venv/Scripts/python.exe backend/scripts/prepare_caption_inputs.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter

from caption_store import ERROR_COLUMNS, upsert_rows

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CURATED_CSV = os.path.join(
    ROOT, "data", "processed", "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"
)
MANIFEST_CSV = os.path.join(ROOT, "data", "processed", "image_manifest.csv")
REMOVE_LOG_CSV = os.path.join(ROOT, "outputs", "image_curation", "remove_log.csv")
OUT_TODO = os.path.join(ROOT, "outputs", "caption_todo.csv")
OUT_ERRORS = os.path.join(ROOT, "outputs", "image_captions_errors.csv")


def load_curated_urls(curated_csv: str) -> list[tuple[str, str]]:
    """返回 [(post_id, url), ...]，保持原帖内顺序，URL 去重。"""
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    with open(curated_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            post_id = row["post_id"]
            try:
                urls = json.loads(row.get("images") or "[]")
            except json.JSONDecodeError:
                continue
            for url in urls:
                if not isinstance(url, str) or not url:
                    continue
                key = (post_id, url)
                if key not in seen:
                    seen.add(key)
                    pairs.append(key)
    return pairs


def load_manifest_index(manifest_csv: str) -> dict[str, dict]:
    """url → manifest 行；同一 url 多行时优先 status=ok 的规范行。"""
    by_url: dict[str, dict] = {}
    with open(manifest_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            url = row["url"]
            prev = by_url.get(url)
            if prev is None or (row["status"] == "ok" and prev["status"] != "ok"):
                by_url[url] = row
    return by_url


def load_removed_ids(remove_log_csv: str) -> set[str]:
    if not os.path.exists(remove_log_csv):
        return set()
    with open(remove_log_csv, encoding="utf-8-sig", newline="") as f:
        return {r["image_id"] for r in csv.DictReader(f) if r.get("status") == "moved"}


def build_todo(
    curated_csv: str,
    manifest_csv: str,
    remove_log_csv: str,
) -> tuple[list[dict], list[dict], Counter]:
    """返回 (todo_rows, file_missing_error_rows, 统计)。"""
    url_index = load_manifest_index(manifest_csv)
    removed_ids = load_removed_ids(remove_log_csv)

    todo: list[dict] = []
    missing_rows: list[dict] = []
    stats: Counter = Counter()

    seen_image_id: set[str] = set()
    for post_id, url in load_curated_urls(curated_csv):
        stats["curated_refs"] += 1
        mrow = url_index.get(url)
        if mrow is None:
            stats["not_in_manifest"] += 1
            continue
        image_id = mrow["image_id"]
        if image_id in seen_image_id:
            continue  # manifest url 去重后的同一张图只入队一次
        if mrow["status"] != "ok" or mrow["dup_of"].strip():
            stats["skip_dup_or_failed"] += 1
            continue
        if image_id in removed_ids:
            stats["skip_removed_by_curation"] += 1
            continue
        seen_image_id.add(image_id)
        local_path = mrow["local_path"]
        if os.path.exists(local_path):
            todo.append(
                {"image_id": image_id, "post_id": mrow["post_id"], "local_path": local_path}
            )
        else:
            stats["file_missing"] += 1
            missing_rows.append(
                {
                    "image_id": image_id,
                    "post_id": mrow["post_id"],
                    "error_type": "file_missing",
                    "detail": f"local_path not found: {local_path}",
                    "attempts": 0,
                }
            )
    return todo, missing_rows, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", default=CURATED_CSV)
    parser.add_argument("--manifest", default=MANIFEST_CSV)
    parser.add_argument("--remove-log", default=REMOVE_LOG_CSV)
    parser.add_argument("--out", default=OUT_TODO)
    parser.add_argument("--errors-out", default=OUT_ERRORS)
    args = parser.parse_args()

    todo, missing_rows, stats = build_todo(args.curated, args.manifest, args.remove_log)

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image_id", "post_id", "local_path"])
        writer.writeheader()
        writer.writerows(todo)

    if missing_rows:
        upsert_rows(args.errors_out, ERROR_COLUMNS, missing_rows)

    print("== prepare_caption_inputs 统计 ==")
    for key in (
        "curated_refs", "not_in_manifest", "skip_dup_or_failed",
        "skip_removed_by_curation", "file_missing",
    ):
        print(f"  {key}: {stats[key]}")
    print(f"  todo(写入 {args.out}): {len(todo)}")
    if missing_rows:
        print(f"  file_missing 已记入失败表: {args.errors_out}")


if __name__ == "__main__":
    main()
