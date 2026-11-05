# -*- coding: utf-8 -*-
"""下载 CSV 中所有图片到本地，并建立 image_id 与样本、顺序的映射。

输出：
1. data/images/{post_id}/        图片文件，按帖子分子目录，命名为 {image_id}.{ext}
2. data/processed/image_manifest.csv          图片清单（image_id <-> post_id/seq/url/本地路径）
3. 原CSV副本 *_with_imgid.csv     追加 image_ids / image_local_paths 两列（顺序与 images 列一致，未改动原有列）

image_id 规则：img_{post_id}_{seq:03d}，seq 为该帖内按 images 列出现顺序的 1 起始序号。
支持断点续跑：已存在且非空的文件跳过下载；同一 URL 只下载一次，其余 occurrence 复制文件。
"""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent.parent
CSV_IN = BASE / "data" / "processed" / "汽车之家_小米SU7_深度清洗_clean.csv"
IMG_DIR = BASE / "data" / "images"
MANIFEST_OUT = BASE / "data" / "processed" / "image_manifest.csv"
CSV_OUT = BASE / "data" / "processed" / "汽车之家_小米SU7_深度清洗_clean_imgid.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://club.autohome.com.cn/",
}
MAX_WORKERS = 32
RETRIES = 3
TIMEOUT = 20


def sniff_ext(content: bytes, content_type: str) -> str:
    if content.startswith(b"\x89PNG"):
        return "png"
    if content.startswith(b"\xff\xd8"):
        return "jpg"
    if content.startswith(b"GIF8"):
        return "gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if content.startswith(b"<"):
        return "html"  # 防盗页等，标记为异常
    ct = content_type.lower()
    for token, ext in (("png", "png"), ("jpeg", "jpg"), ("jpg", "jpg"),
                       ("gif", "gif"), ("webp", "webp")):
        if token in ct:
            return ext
    return "jpg"


def download_one(url: str, dest: Path) -> dict:
    """下载到 dest，返回 {"ok": bool, "ext": str, "size": int, "error": str}"""
    if dest.exists() and dest.stat().st_size > 0:
        return {"ok": True, "ext": dest.suffix.lstrip("."), "size": dest.stat().st_size, "error": ""}
    last_err = ""
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=False)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
            else:
                content = resp.content
                ext = sniff_ext(content, resp.headers.get("Content-Type", ""))
                if ext == "html":
                    last_err = "got html (anti-bot?)"
                elif len(content) < 1024:
                    last_err = f"too small: {len(content)}B"
                else:
                    final = dest.with_suffix(f".{ext}")
                    final.parent.mkdir(parents=True, exist_ok=True)
                    final.write_bytes(content)
                    return {"ok": True, "ext": ext, "size": len(content), "error": ""}
        except Exception as e:  # noqa: BLE001
            last_err = repr(e)
    return {"ok": False, "ext": "", "size": 0, "error": f"{last_err} (attempt {attempt})"}


def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(CSV_IN, encoding="utf-8-sig", dtype={"post_id": str})
    print(f"rows: {len(df)}")

    # 1) 构建 (image_id, post_id, seq, url) 列表 + 帖内顺序列表
    records = []          # 顺序记录，用于 manifest
    post_image_ids = []   # 每行的 image_ids 列表
    seen_url = {}         # url -> (image_id, 已落盘路径)，避免重复下载
    tasks = []            # 需要真正下载的任务

    for _, row in df.iterrows():
        post_id = str(row["post_id"])
        try:
            urls = json.loads(row.get("images") or "[]")
        except (json.JSONDecodeError, TypeError):
            urls = []
        ids, paths = [], []
        for seq, url in enumerate(urls, start=1):
            url = str(url).strip()
            image_id = f"img_{post_id}_{seq:03d}"
            ids.append(image_id)
            if url in seen_url:
                paths.append(str(seen_url[url][1]))
                records.append({"image_id": image_id, "post_id": post_id, "seq": seq,
                                "url": url, "dup_of": seen_url[url][0],
                                "status": "dup", "local_path": str(seen_url[url][1]),
                                "size": "", "error": ""})
                continue
            # 先占位扩展名 jpg，实际扩展名下载后确定；按帖子分子目录存放
            dest = IMG_DIR / post_id / f"{image_id}.jpg"
            seen_url[url] = (image_id, dest)
            tasks.append((url, dest, image_id, post_id, seq))
            paths.append(str(dest))

        post_image_ids.append({"post_id": post_id, "ids": ids, "paths": paths})

    print(f"unique downloads: {len(tasks)}, total occurrences: {sum(len(p['ids']) for p in post_image_ids)}")

    # 2) 并发下载
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(download_one, url, dest): (url, dest, image_id, post_id, seq)
                for url, dest, image_id, post_id, seq in tasks}
        done = 0
        for fut in as_completed(futs):
            url, dest, image_id, post_id, seq = futs[fut]
            r = fut.result()
            results[image_id] = (url, dest, post_id, seq, r)
            done += 1
            if done % 50 == 0 or done == len(futs):
                print(f"  downloaded {done}/{len(futs)}")

    # 3) 修正实际落盘路径（扩展名可能变化），处理 dup 复制
    for url, (first_id, dest) in list(seen_url.items()):
        r = results.get(first_id, (url, dest, None, None, {"ok": False}))[4]
        if r.get("ok"):
            actual = dest.with_suffix(f".{r['ext']}")
            if actual != dest and dest.exists():
                dest.unlink()
            seen_url[url] = (first_id, actual)

    for rec in records:
        if rec["status"] == "dup":
            first_id = rec["dup_of"]
            first_r = results.get(first_id)
            if first_r and first_r[4].get("ok"):
                dup_dest = IMG_DIR / rec["post_id"] / f"{rec['image_id']}.{first_r[4]['ext']}"
                dup_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(seen_url[url][1], dup_dest)
                rec["local_path"] = str(dup_dest)
                rec["status"] = "ok(dup-copy)"
            else:
                rec["status"] = "failed"
                rec["error"] = "source download failed"

    # 4) 生成 manifest（unique 下载记录 + dup 记录合并）
    manifest_rows = []
    for url, dest, image_id, post_id, seq in tasks:
        r = results[image_id][4]
        if r["ok"]:
            actual = dest.with_suffix(f".{r['ext']}")
            status = "ok"
        else:
            actual = dest
            status = "failed"
        manifest_rows.append({"image_id": image_id, "post_id": post_id, "seq": seq,
                              "url": url, "local_path": str(actual),
                              "status": status, "size": r["size"], "error": r["error"]})
    for rec in records:
        manifest_rows.append(rec)
    manifest = pd.DataFrame(manifest_rows).sort_values(["post_id", "seq"])
    manifest.to_csv(MANIFEST_OUT, index=False, encoding="utf-8-sig")

    # 5) 帖内 image_ids 列表回填（保持与 images 列同序），路径用实际落盘路径
    actual_path_by_id = {r["image_id"]: r["local_path"] for r in manifest_rows
                         if str(r["status"]).startswith("ok")}
    for p in post_image_ids:
        p["paths"] = [actual_path_by_id.get(i, str(IMG_DIR / p["post_id"] / f"{i}.jpg")) for i in p["ids"]]
    id_map = {p["post_id"]: (p["ids"], p["paths"]) for p in post_image_ids}
    df["image_ids"] = df["post_id"].map(lambda p: json.dumps(id_map.get(p, ([], []))[0], ensure_ascii=False))
    df["image_local_paths"] = df["post_id"].map(lambda p: json.dumps(id_map.get(p, ([], []))[1], ensure_ascii=False))
    df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")

    ok = (manifest["status"].str.startswith("ok")).sum()
    failed = len(manifest) - ok
    print(f"\nDone. total={len(manifest)} ok={ok} failed={failed}")
    print(f"manifest -> {MANIFEST_OUT}")
    print(f"csv      -> {CSV_OUT}")
    if failed:
        print("\nfailed rows:")
        print(manifest[manifest["status"] == "failed"][["image_id", "url", "error"]].to_string(index=False))


if __name__ == "__main__":
    main()
