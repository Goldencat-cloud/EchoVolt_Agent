"""图片语料治理管线（change: image-corpus-curation）。

基于 Chinese-CLIP 特征缓存的三类标记建议判定：
  encode  批量编码本地图片 -> image_features.npz（增量复用）
  judge   三类判定（读缓存，阈值可调，秒级重跑）：
            帖内视觉去冗余  -> visual_dup_groups.csv
            图-帖低相似    -> post_image_sim.csv
            广告嫌疑        -> ad_suspects.csv
  all     encode + judge + 只读自检 + 汇总统计

只读 data/images/ 与 image_manifest.csv，不删除、不修改任何数据文件。
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import clip_service  # noqa: E402  复用模型加载与编码（ADR-1）

DATA = PROJECT_ROOT / "data"
MANIFEST_CSV = DATA / "processed" / "image_manifest.csv"
POSTS_CSV = DATA / "processed" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "image_curation"

FEATURES_NPZ = OUT_DIR / "image_features.npz"
ERRORS_CSV = OUT_DIR / "encode_errors.csv"
DUP_CSV = OUT_DIR / "visual_dup_groups.csv"
SIM_CSV = OUT_DIR / "post_image_sim.csv"
ADS_CSV = OUT_DIR / "ad_suspects.csv"
TYPES_CSV = OUT_DIR / "image_content_types.csv"
SENT_NPZ = OUT_DIR / "sentence_features.npz"
SUMMARY_MD = OUT_DIR / "summary.md"

STATUS_WHITELIST = {"ok", "ok(dup-copy)"}
BATCH_SIZE = 64

# 阈值默认值（design.md ADR-4/5/7；经人工评估反馈修订：宁可错收、不误杀）
DUP_THRESHOLD = 0.94        # 照片类冗余阈值（初值 0.90，表格/模板海报误标后上调）
TEXT_DUP_THRESHOLD = 0.98   # text_graphic 类仅近重复才归组（ADR-7 保护）
TYPE_MARGIN_CUTOFF = 0.04   # text_max - photo_max >= 0.04 判为文字图（约 p83，分布实测校准）
LOW_SIM_THRESHOLD = 0.40    # 照片类低相似阈值（text_graphic 豁免后可收紧；初值 0.35）
AD_THRESHOLD = 0.52

# 广告/正常双类提示词集（ADR-5，可迭代）
AD_PROMPTS = [
    "促销海报", "优惠活动宣传图", "二维码图片", "价格表宣传单",
    "广告标语图片", "店铺宣传图", "购车优惠信息图",
]
NORMAL_PROMPTS = [
    "汽车外观照片", "汽车内饰照片", "汽车照片", "风景照",
    "生活照", "聚会照片", "美食照片",
]

# 内容类型双类提示词集（ADR-7：表格/文字图与照片分离，保护前者）
TEXT_GRAPHIC_PROMPTS = [
    "表格截图", "数据图表", "参数配置表", "报价单", "价格列表",
    "文字海报", "信息图表", "榜单截图", "聊天记录截图", "文档图片",
]
PHOTO_PROMPTS = [
    "汽车照片", "风景照片", "人物照片", "生活照", "街景照片",
    "内饰照片", "美食照片", "动物照片",
]

_SENT_SPLIT = re.compile(r"[。！？!?；;\n\r]+")
_SENT_SUBSPLIT = re.compile(r"[，,、]+")
_SENT_MAX_CHARS = 80


def _log(msg: str) -> None:
    print(f"[curate] {msg}", flush=True)


def _load_manifest() -> pd.DataFrame:
    m = pd.read_csv(MANIFEST_CSV)
    m = m[m["status"].isin(STATUS_WHITELIST) & m["local_path"].notna()].copy()
    return m.sort_values(["post_id", "seq"]).reset_index(drop=True)


def _l2(feat: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(feat, axis=-1, keepdims=True)
    return feat / np.clip(norm, 1e-8, None)


# ---------------- encode ----------------

def _encode_batch_safe(images: list) -> np.ndarray:
    """batch 64 起步，OOM 自动减半重试（design.md 风险对策）。"""
    import torch
    try:
        return np.asarray(clip_service.encode_images(images), dtype=np.float32)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
    if len(images) == 1:
        raise RuntimeError("单张图片编码仍 OOM")
    mid = len(images) // 2
    return np.concatenate([_encode_batch_safe(images[:mid]), _encode_batch_safe(images[mid:])])


def _load_cache() -> tuple[list[str], np.ndarray]:
    if FEATURES_NPZ.exists():
        data = np.load(FEATURES_NPZ, allow_pickle=False)
        return list(data["image_ids"]), data["features"]
    return [], np.zeros((0, 512), dtype=np.float16)


def cmd_encode() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    done_ids, done_feats = _load_cache()
    done = set(done_ids)
    todo = manifest[~manifest["image_id"].isin(done)]
    _log(f"manifest 可用图片 {len(manifest)}，缓存已含 {len(done)}，待编码 {len(todo)}")

    errors: list[dict] = []
    new_ids: list[str] = []
    new_feats: list[np.ndarray] = []
    batch: list = []
    batch_ids: list[str] = []

    def flush() -> None:
        if not batch:
            return
        try:
            feats = _encode_batch_safe(batch)
        except Exception as exc:  # 解码失败等 → 错误清单，不中断（spec 坏图容错）
            for image_id in batch_ids:
                errors.append({"image_id": image_id, "error": str(exc)[:200]})
            _log(f"批次失败 {len(batch_ids)} 张: {str(exc)[:80]}")
        else:
            new_ids.extend(batch_ids)
            new_feats.append(feats.astype(np.float16))
        batch.clear()
        batch_ids.clear()

    clip_service.load_model()
    for row in todo.itertuples(index=False):
        try:
            img = Image.open(row.local_path).convert("RGB")
        except Exception as exc:
            errors.append({"image_id": row.image_id, "error": str(exc)[:200]})
            continue
        batch.append(img)
        batch_ids.append(row.image_id)
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()

    all_ids = done_ids + new_ids
    all_feats = np.concatenate([done_feats] + new_feats) if new_feats else done_feats
    np.savez(FEATURES_NPZ, image_ids=np.array(all_ids), features=all_feats)
    pd.DataFrame(errors, columns=["image_id", "error"]).to_csv(ERRORS_CSV, index=False, encoding="utf-8-sig")
    _log(f"编码完成：新增 {len(new_ids)}，累计 {len(all_ids)}，坏图 {len(errors)} -> {ERRORS_CSV.name}")


# ---------------- 文本侧 ----------------

def split_sentences(title: str, clean_text: str) -> list[str]:
    """标题 + clean_text 切句：标点一级切分，超长句逗号二级切分，仍超限硬截断（ADR-3）。"""
    raw = "。".join(str(x) for x in [title, clean_text] if pd.notna(x) and str(x).strip())
    sents: list[str] = []
    for part in _SENT_SPLIT.split(raw):
        part = part.strip()
        if not part:
            continue
        if len(part) <= _SENT_MAX_CHARS:
            sents.append(part)
            continue
        for sub in _SENT_SUBSPLIT.split(part):
            sub = sub.strip()
            if not sub:
                continue
            sents.append(sub[:_SENT_MAX_CHARS])
    return sents


def _sent_hash(sent: str) -> str:
    return hashlib.md5(sent.encode("utf-8")).hexdigest()


def _load_sent_cache() -> tuple[dict[str, int], np.ndarray]:
    if SENT_NPZ.exists():
        data = np.load(SENT_NPZ, allow_pickle=False)
        sids = [str(x) for x in data["sids"]]
        return {sid: i for i, sid in enumerate(sids)}, data["features"]
    return {}, np.zeros((0, 512), dtype=np.float32)


def encode_sentences(all_sentences: list[str]) -> tuple[dict[str, int], np.ndarray]:
    """句向量缓存：相同句子（md5）全局去重后编码，增量复用（任务 3.1）。"""
    index, feats = _load_sent_cache()
    todo: dict[str, str] = {}
    for sent in all_sentences:
        sid = _sent_hash(sent)
        if sid not in index and sid not in todo:
            todo[sid] = sent
    if todo:
        clip_service.load_model()
        sids = list(todo)
        vectors = []
        for i in range(0, len(sids), BATCH_SIZE):
            chunk = [todo[s] for s in sids[i:i + BATCH_SIZE]]
            vectors.append(np.asarray(clip_service.encode_texts(chunk), dtype=np.float32))
        new_feats = np.concatenate(vectors).astype(np.float16)
        feats = np.concatenate([feats, new_feats]).astype(np.float32)
        sids = list(index.keys()) + sids
        index = {sid: i for i, sid in enumerate(sids)}
        np.savez(SENT_NPZ, sids=np.array(sids), features=feats.astype(np.float16))
        _log(f"句向量：新增 {len(todo)}，累计 {len(sids)}")
    return index, feats


# ---------------- judge: types（ADR-7 内容类型分类） ----------------

def _load_types() -> dict[str, str]:
    if TYPES_CSV.exists():
        df = pd.read_csv(TYPES_CSV)
        return dict(zip(df["image_id"], df["content_type"]))
    return {}


def cmd_judge_types() -> pd.DataFrame:
    ids, f16 = _load_cache()
    f32 = _l2(f16.astype(np.float32))
    clip_service.load_model()
    tvecs = _l2(np.asarray(clip_service.encode_texts(TEXT_GRAPHIC_PROMPTS), dtype=np.float32))
    pvecs = _l2(np.asarray(clip_service.encode_texts(PHOTO_PROMPTS), dtype=np.float32))
    # 用原始 margin（text_max - photo_max）：softmax 会把分数压到 ±0.01 失去判别力（实测）
    margin = (f32 @ tvecs.T).max(axis=1) - (f32 @ pvecs.T).max(axis=1)

    df = pd.DataFrame({
        "image_id": ids,
        "text_margin": np.round(margin, 4),
        "content_type": np.where(margin >= TYPE_MARGIN_CUTOFF, "text_graphic", "photo"),
    })
    df.to_csv(TYPES_CSV, index=False, encoding="utf-8-sig")
    _log(f"内容类型：text_graphic {int((df['content_type'] == 'text_graphic').sum())} / photo {int((df['content_type'] == 'photo').sum())} -> {TYPES_CSV.name}")
    return df


# ---------------- judge: dedupe ----------------

def _union_find(n: int) -> list[int]:
    parent = list(range(n))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)
    return parent, find, union


def cmd_judge_dedupe(threshold: float, text_threshold: float) -> pd.DataFrame:
    manifest = _load_manifest()
    ids, feats16 = _load_cache()
    fmap = {k: i for i, k in enumerate(ids)}
    f32 = _l2(feats16.astype(np.float32))
    types = _load_types()

    def pair_threshold(id_a: str, id_b: str) -> float:
        both_text = types.get(id_a) == "text_graphic" and types.get(id_b) == "text_graphic"
        return text_threshold if both_text else threshold

    rows: list[dict] = []
    for post_id, group in manifest.groupby("post_id", sort=True):
        idx = [fmap[i] for i in group["image_id"] if i in fmap]
        if len(idx) < 2:  # 单图帖豁免（spec）
            continue
        vecs = f32[idx]
        sim = vecs @ vecs.T
        parent, find, union = _union_find(len(idx))
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                if sim[i, j] >= pair_threshold(group["image_id"].iloc[i], group["image_id"].iloc[j]):
                    union(i, j)
        comps: dict[int, list[int]] = {}
        for i in range(len(idx)):
            comps.setdefault(find(i), []).append(i)
        gid = 0
        for members in comps.values():
            if len(members) < 2:
                continue
            gid += 1
            seqs = group.iloc[members]["seq"].tolist()
            keep_local = members[seqs.index(min(seqs))]
            for local_i in members:
                rows.append({
                    "image_id": group.iloc[local_i]["image_id"],
                    "post_id": post_id,
                    "group_id": f"{post_id}_g{gid}",
                    "keep": local_i == keep_local,
                    "visual_dup": local_i != keep_local,
                })
    df = pd.DataFrame(rows, columns=["image_id", "post_id", "group_id", "keep", "visual_dup"])
    df.to_csv(DUP_CSV, index=False, encoding="utf-8-sig")
    _log(f"帖内去冗余：{df['group_id'].nunique() if len(df) else 0} 组 / {int(df['visual_dup'].sum()) if len(df) else 0} 张冗余 -> {DUP_CSV.name}")
    return df


# ---------------- judge: sim ----------------

def _load_posts_text() -> dict[str, tuple[str, str]]:
    df = pd.read_csv(POSTS_CSV, usecols=["post_id", "title", "clean_text"], dtype={"post_id": str})
    return {str(r.post_id): (r.title, r.clean_text) for r in df.itertuples(index=False)}


def cmd_judge_sim(threshold: float) -> pd.DataFrame:
    manifest = _load_manifest()
    ids, feats16 = _load_cache()
    fmap = {k: i for i, k in enumerate(ids)}
    f32 = _l2(feats16.astype(np.float32))
    posts_text = _load_posts_text()
    types = _load_types()

    all_sentences: list[str] = []
    post_sents: dict[str, list[str]] = {}
    for post_id in manifest["post_id"].unique():
        title, clean_text = posts_text.get(str(post_id), ("", ""))
        sents = split_sentences(title, clean_text)
        post_sents[str(post_id)] = sents
        all_sentences.extend(sents)
    sindex, sfeats = encode_sentences(all_sentences)
    sfeats = _l2(sfeats)

    rows: list[dict] = []
    for row in manifest.itertuples(index=False):
        image_id, post_id = str(row.image_id), str(row.post_id)
        if image_id not in fmap:
            continue  # 坏图，未编码
        sents = post_sents.get(post_id, [])
        if not sents:  # 纯图帖无标题无正文 -> no_text，不产生标记（spec）
            rows.append({"image_id": image_id, "post_id": post_id,
                         "max_sim": np.nan, "sim_status": "no_text", "low_text_sim": False})
            continue
        img_vec = f32[fmap[image_id]]
        sent_ids = [_sent_hash(s) for s in sents]
        sent_vecs = sfeats[[sindex[s] for s in sent_ids]]
        max_sim = float((sent_vecs @ img_vec).max())
        if types.get(image_id) == "text_graphic":
            # 表格/文字图受保护：CLIP 读不了图内文字，天然低分不算低相似（spec / ADR-7）
            rows.append({"image_id": image_id, "post_id": post_id,
                         "max_sim": round(max_sim, 4), "sim_status": "text_graphic",
                         "low_text_sim": False})
            continue
        rows.append({"image_id": image_id, "post_id": post_id,
                     "max_sim": round(max_sim, 4), "sim_status": "ok",
                     "low_text_sim": max_sim < threshold})
    df = pd.DataFrame(rows, columns=["image_id", "post_id", "max_sim", "sim_status", "low_text_sim"])
    df.to_csv(SIM_CSV, index=False, encoding="utf-8-sig")
    _log(f"图-帖相似：{len(df)} 张，低相似 {int(df['low_text_sim'].sum())}，no_text {int((df['sim_status'] == 'no_text').sum())} -> {SIM_CSV.name}")
    return df


# ---------------- judge: ads ----------------

def cmd_judge_ads(threshold: float) -> pd.DataFrame:
    ids, feats16 = _load_cache()
    f32 = _l2(feats16.astype(np.float32))
    clip_service.load_model()
    ad_vecs = _l2(np.asarray(clip_service.encode_texts(AD_PROMPTS), dtype=np.float32))
    normal_vecs = _l2(np.asarray(clip_service.encode_texts(NORMAL_PROMPTS), dtype=np.float32))

    img = f32  # [N, 512]
    ad_max = (img @ ad_vecs.T).max(axis=1)
    normal_max = (img @ normal_vecs.T).max(axis=1)
    # softmax([ad_max, normal_max]) 稳定实现
    logits = np.stack([ad_max, normal_max], axis=1)
    logits -= logits.max(axis=1, keepdims=True)
    prob_ad = np.exp(logits[:, 0]) / np.exp(logits).sum(axis=1)

    df = pd.DataFrame({
        "image_id": ids,
        "ad_prob": np.round(prob_ad, 4),
        "ad_suspect": prob_ad >= threshold,
    })
    df.to_csv(ADS_CSV, index=False, encoding="utf-8-sig")
    _log(f"广告嫌疑：{len(df)} 张，嫌疑 {int(df['ad_suspect'].sum())} -> {ADS_CSV.name}")
    return df


# ---------------- all / 自检 / 汇总 ----------------

def _hash_images_dir() -> tuple[int, str]:
    files = sorted(p.name for p in (DATA / "images").rglob("*") if p.is_file())
    digest = hashlib.md5("\n".join(files).encode("utf-8")).hexdigest()
    return len(files), digest


def cmd_all(thresholds: dict[str, float]) -> None:
    manifest_md5_before = hashlib.md5(MANIFEST_CSV.read_bytes()).hexdigest()
    count_before, images_hash_before = _hash_images_dir()

    cmd_encode()
    df_types = cmd_judge_types()
    df_dup = cmd_judge_dedupe(thresholds["dup"], thresholds["text_dup"])
    df_sim = cmd_judge_sim(thresholds["sim"])
    df_ads = cmd_judge_ads(thresholds["ads"])

    manifest_md5_after = hashlib.md5(MANIFEST_CSV.read_bytes()).hexdigest()
    count_after, images_hash_after = _hash_images_dir()
    readonly_ok = (manifest_md5_before == manifest_md5_after
                   and count_before == count_after
                   and images_hash_before == images_hash_after)
    _log(f"只读自检：{'通过' if readonly_ok else '失败!'}（manifest md5 与 images 文件清单前后一致）")

    n_feat = len(_load_cache()[0])
    n_no_text = int((df_sim["sim_status"] == "no_text").sum())
    no_text_posts = int(df_sim[df_sim["sim_status"] == "no_text"]["post_id"].nunique())
    n_text_graphic = int((df_types["content_type"] == "text_graphic").sum())
    n_errors = 0
    if ERRORS_CSV.exists() and ERRORS_CSV.stat().st_size > 0:
        n_errors = len(pd.read_csv(ERRORS_CSV))
    summary = f"""# image-curation 汇总统计

| 指标 | 数值 |
|---|---|
| 编码图片 | {n_feat} |
| 坏图/缺失 | {n_errors} |
| 内容类型 | text_graphic {n_text_graphic} / photo {n_feat - n_text_graphic} |
| 帖内冗余组 | {int(df_dup['group_id'].nunique()) if len(df_dup) else 0} |
| 冗余图（visual_dup） | {int(df_dup['visual_dup'].sum()) if len(df_dup) else 0}（占 {int(df_dup['visual_dup'].sum()) / max(n_feat, 1) * 100:.1f}%） |
| 低相似图（low_text_sim，仅 photo 类） | {int(df_sim['low_text_sim'].sum())}（占 {int(df_sim['low_text_sim'].sum()) / max(n_feat, 1) * 100:.1f}%） |
| 广告嫌疑图（ad_suspect） | {int(df_ads['ad_suspect'].sum())}（占 {int(df_ads['ad_suspect'].sum()) / max(n_feat, 1) * 100:.1f}%） |
| no_text 图片 / 帖 | {n_no_text} / {no_text_posts} |
| 阈值（dup/text_dup/sim/ads） | {thresholds['dup']} / {thresholds['text_dup']} / {thresholds['sim']} / {thresholds['ads']} |
| 只读自检 | {'通过' if readonly_ok else '失败'} |
"""
    SUMMARY_MD.write_text(summary, encoding="utf-8")
    _log(f"汇总 -> {SUMMARY_MD.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("encode", help="批量编码图片特征（增量复用）")
    sub.add_parser("judge", help="三类判定（读缓存，秒级）")
    sub.add_parser("all", help="encode + judge + 只读自检 + 汇总")
    for p in (sub.choices["judge"], sub.choices["all"]):
        p.add_argument("--dup-threshold", type=float, default=DUP_THRESHOLD)
        p.add_argument("--text-dup-threshold", type=float, default=TEXT_DUP_THRESHOLD)
        p.add_argument("--sim-threshold", type=float, default=LOW_SIM_THRESHOLD)
        p.add_argument("--ad-threshold", type=float, default=AD_THRESHOLD)
    args = parser.parse_args()

    if args.cmd == "encode":
        cmd_encode()
    elif args.cmd == "judge":
        cmd_judge_types()
        cmd_judge_dedupe(args.dup_threshold, args.text_dup_threshold)
        cmd_judge_sim(args.sim_threshold)
        cmd_judge_ads(args.ad_threshold)
    elif args.cmd == "all":
        cmd_all({"dup": args.dup_threshold, "text_dup": args.text_dup_threshold,
                 "sim": args.sim_threshold, "ads": args.ad_threshold})


if __name__ == "__main__":
    main()
