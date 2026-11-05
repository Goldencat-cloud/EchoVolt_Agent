# -*- coding: utf-8 -*-
"""从两个 CSV 中剔除下载失败（404 死链）的图片引用，结果写入新文件（不覆盖原文件）。

处理逻辑（对每个受影响 post 的行）：
- images 列：从 JSON 列表中删除失败 URL
- multimodal_content / clean_multimodal 列：删除 {"type":"img","v":<失败URL>} 条目，text 条目与剩余图片顺序保持不变
- image_count 列：同步更新为剩余图片数（若可解析为数值）

输出：原文件名 + `_valid` 后缀的新 CSV。
"""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
MANIFEST = BASE / "data" / "processed" / "image_manifest.csv"
CSV_FILES = [
    BASE / "data" / "processed" / "汽车之家_小米SU7_深度清洗_clean.csv",
    BASE / "data" / "processed" / "汽车之家_小米SU7_深度清洗语料.csv",
]


def main():
    m = pd.read_csv(MANIFEST, encoding="utf-8-sig")
    failed = m[m["status"] == "failed"]
    dead_by_post = failed.groupby("post_id")["url"].apply(set).to_dict()
    print(f"failed images: {len(failed)}, affected posts: {len(dead_by_post)}")

    for csv_path in CSV_FILES:
        if not csv_path.exists():
            print(f"skip (not found): {csv_path.name}")
            continue
        out_path = csv_path.with_name(csv_path.stem + "_valid.csv")

        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype={"post_id": str})
        removed_total = 0
        touched_rows = 0

        for idx, row in df.iterrows():
            post_id = str(row["post_id"])
            if post_id not in dead_by_post:
                continue
            dead = dead_by_post[post_id]

            # images 列
            try:
                urls = json.loads(row.get("images") or "[]")
            except (json.JSONDecodeError, TypeError):
                urls = []
            new_urls = [u for u in urls if str(u).strip() not in dead]
            removed_total += len(urls) - len(new_urls)
            df.at[idx, "images"] = json.dumps(new_urls, ensure_ascii=False)

            # multimodal_content / clean_multimodal 列
            for col in ("multimodal_content", "clean_multimodal"):
                if col not in df.columns:
                    continue
                try:
                    items = json.loads(row.get(col) or "[]")
                except (json.JSONDecodeError, TypeError):
                    items = []
                new_items = [it for it in items
                             if not (isinstance(it, dict) and it.get("type") == "img"
                                     and str(it.get("v", "")).strip() in dead)]
                removed_total += len(items) - len(new_items)
                df.at[idx, col] = json.dumps(new_items, ensure_ascii=False)

            # image_count 列
            if "image_count" in df.columns:
                try:
                    df.at[idx, "image_count"] = float(len(new_urls))
                except (ValueError, TypeError):
                    pass

            touched_rows += 1

        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"{csv_path.name}: touched {touched_rows} rows, removed {removed_total} img refs -> {out_path.name}")


if __name__ == "__main__":
    main()
