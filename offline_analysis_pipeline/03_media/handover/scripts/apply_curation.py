"""按 image-curation 标记结果执行隔离与语料更新（用户指令：1/2 类移入隔离目录）。

  apply   冗余+低相似图移入 data/images_removed/{post_id}/，写处理日志，
          生成剔除后的新 CSV（*_curated.csv：image_ids / image_local_paths /
          multimodal_content 同步剔除被移除图片）
  restore 按 remove_log.csv 全量移回（撤销隔离）

注意：本脚本来自用户对标记结果的处置指令，超出 change 的"只标记"范围
（proposal Non-goals 已由用户决定推翻）；文件移动可经 restore 完全恢复。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import curate_images as c

POSTS_CSV = PROJECT_ROOT / "data" / "processed" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid.csv"
CURATED_CSV = PROJECT_ROOT / "data" / "processed" / "汽车之家_小米SU7_深度清洗_clean_valid_imgid_curated.csv"
REMOVED_DIR = PROJECT_ROOT / "data" / "images_removed"
LOG_CSV = c.OUT_DIR / "remove_log.csv"


def _build_removal_set() -> pd.DataFrame:
    """冗余 ∪ 低相似 → 移除清单（去重；原因合并）。"""
    dup = pd.read_csv(c.DUP_CSV)
    sim = pd.read_csv(c.SIM_CSV)
    dup_ids = set(dup.loc[dup["visual_dup"] == True, "image_id"])  # noqa: E712
    sim_ids = set(sim.loc[sim["low_text_sim"] == True, "image_id"])  # noqa: E712
    rows = []
    for image_id in sorted(dup_ids | sim_ids):
        reason = "+".join(
            name for name, ids in [("visual_dup", dup_ids), ("low_text_sim", sim_ids)]
            if image_id in ids
        )
        rows.append({"image_id": image_id, "reason": reason})
    return pd.DataFrame(rows)


def cmd_apply() -> None:
    removal = _build_removal_set()
    man = pd.read_csv(c.MANIFEST_CSV).set_index("image_id")
    REMOVED_DIR.mkdir(parents=True, exist_ok=True)

    log_rows: list[dict] = []
    for row in removal.itertuples(index=False):
        image_id = row.image_id
        if image_id not in man.index:
            log_rows.append({"image_id": image_id, "reason": row.reason,
                             "status": "not_in_manifest", "source_path": "", "moved_to": ""})
            continue
        src = Path(man.loc[image_id, "local_path"])
        post_id = str(man.loc[image_id, "post_id"])
        dst_dir = REMOVED_DIR / post_id
        dst = dst_dir / src.name
        if not src.exists():
            log_rows.append({"image_id": image_id, "reason": row.reason,
                             "status": "source_missing", "source_path": str(src), "moved_to": ""})
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        if dst.exists():  # 幂等：之前已移过
            log_rows.append({"image_id": image_id, "reason": row.reason,
                             "status": "already_removed", "source_path": str(src), "moved_to": str(dst)})
            continue
        shutil.move(str(src), str(dst))
        log_rows.append({"image_id": image_id, "reason": row.reason,
                         "status": "moved", "source_path": str(src), "moved_to": str(dst)})

    log = pd.DataFrame(log_rows, columns=["image_id", "reason", "status", "source_path", "moved_to"])
    log.to_csv(LOG_CSV, index=False, encoding="utf-8-sig")
    moved = int((log["status"] == "moved").sum())
    print(f"[apply] 移除清单 {len(removal)} 张 | 实际移动 {moved} | 已移过 {int((log['status'] == 'already_removed').sum())} | 源缺失 {int((log['status'] == 'source_missing').sum())}")
    print(f"[apply] 日志 -> {LOG_CSV.name}")

    # ---- 生成剔除后的新 CSV ----
    removed_ids = set(removal["image_id"])
    removed_urls = set(man.loc[list(removed_ids & set(man.index)), "url"]) if removed_ids else set()
    df = pd.read_csv(POSTS_CSV, dtype={"post_id": str})

    def clean_list_col(v: str) -> str:
        try:
            items = json.loads(v)
        except (TypeError, json.JSONDecodeError):
            return v
        kept = [x for x in items if Path(x).stem not in removed_ids and x not in removed_ids]
        return json.dumps(kept, ensure_ascii=False)

    def clean_multimodal(v: str) -> str:
        try:
            segs = json.loads(v)
        except (TypeError, json.JSONDecodeError):
            return v
        kept = [s for s in segs if not (s.get("type") == "img" and s.get("v") in removed_urls)]
        return json.dumps(kept, ensure_ascii=False)

    df["image_ids"] = df["image_ids"].map(clean_list_col)
    df["image_local_paths"] = df["image_local_paths"].map(clean_list_col)
    df["multimodal_content"] = df["multimodal_content"].map(clean_multimodal)
    df["image_count"] = df["image_ids"].map(lambda v: len(json.loads(v)) if pd.notna(v) else 0)
    df.to_csv(CURATED_CSV, index=False, encoding="utf-8-sig")

    n_kept = df["image_ids"].map(lambda v: len(json.loads(v)) if pd.notna(v) else 0).sum()
    print(f"[apply] 新语料 -> {CURATED_CSV.name}（{len(df)} 行，保留图片 {n_kept} 张）")


def cmd_restore() -> None:
    if not LOG_CSV.exists():
        print("[restore] 无日志文件")
        return
    log = pd.read_csv(LOG_CSV)
    n = 0
    for row in log.itertuples(index=False):
        if row.status not in ("moved", "already_removed") or not row.moved_to:
            continue
        src, dst = Path(row.moved_to), Path(row.source_path)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            n += 1
    print(f"[restore] 已移回 {n} 张")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apply", help="隔离移除 + 生成新 CSV")
    sub.add_parser("restore", help="按日志全量移回（撤销）")
    args = parser.parse_args()
    if args.cmd == "apply":
        cmd_apply()
    else:
        cmd_restore()


if __name__ == "__main__":
    main()
