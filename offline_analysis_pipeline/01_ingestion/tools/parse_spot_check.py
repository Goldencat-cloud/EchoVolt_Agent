"""Parse the 3 spot-check responses already saved in stock snapshots (0 new requests)."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/data/stock"
sys.path.insert(0, r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/01_ingestion/src")
from autoinsight_ingestion.normalize.pages import post_page

import gzip
db = sqlite3.connect(ROOT + r"/db/ingestion.sqlite3")
db.row_factory = sqlite3.Row
snaps = db.execute("""SELECT s.snapshot_id, s.relative_path, s.retrieved_at, s.provenance_json
FROM source_snapshots s WHERE s.material_kind='http_body' ORDER BY s.retrieved_at DESC LIMIT 3""").fetchall()
print("found", len(snaps), "spot-check snapshots")
labels = {"115642479": "single-image", "114710340": "multi-image", "109747396": "no-media"}
for s in snaps:
    url = json.loads(s["provenance_json"])["url"]
    pid = url.rstrip("/").rstrip(".html").split("/")[-1].split("-")[0]
    blob = ROOT + "/" + s["relative_path"]
    if not Path(blob).exists() and Path(blob + ".gz").exists():
        body = gzip.decompress(open(blob + ".gz", "rb").read()).decode("utf-8", errors="replace")
    else:
        body = open(blob, "rb").read().decode("utf-8", errors="replace")
    stored = json.loads(db.execute("SELECT content_segments_json FROM posts WHERE post_id=?", (pid,)).fetchone()[0] or "[]")
    stored_text = db.execute("SELECT body_text FROM posts WHERE post_id=?", (pid,)).fetchone()[0] or ""
    try:
        record = post_page(body, pid, url, s["retrieved_at"])
        segs = record.data["segments"]
        text = record.data["text_content"] or ""
        imgs = sum(1 for x in segs if x["kind"] == "image")
        vids = sum(1 for x in segs if x["kind"] == "video")
        verdict = ("HAS_TEXT_ONLINE (legacy miss!)" if text.strip()
                   else "pure-image confirmed online" if imgs else "no text & no images online")
        print(json.dumps({"label": labels.get(pid, "?"), "post_id": pid,
                          "live_text_len": len(text), "live_text_head": text[:50],
                          "live_images": imgs, "live_videos": vids,
                          "stored_text_len": len(stored_text), "stored_segments": len(stored),
                          "stored_images": sum(1 for x in stored if x["kind"] == "image"),
                          "verdict": verdict}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"post_id": pid, "parse_error": getattr(exc, "code", str(exc))}, ensure_ascii=False))
