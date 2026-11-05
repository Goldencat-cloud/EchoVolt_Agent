"""Spot-check 3 review_required posts against the live site (3 requests, bounded)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.contracts import JobConfig
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.normalize.pages import post_page
from autoinsight_ingestion.storage import Repository

STOCK = Path(r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/data/stock")

db = __import__("sqlite3").connect(STOCK / "db" / "ingestion.sqlite3")
db.row_factory = __import__("sqlite3").Row
one_img = db.execute("SELECT post_id, source_url FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=1 AND json_extract(content_segments_json,'$[0].kind')='image' LIMIT 1").fetchone()
many_img = db.execute("SELECT post_id, source_url FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)>=3 LIMIT 1").fetchone()
empty = db.execute("SELECT post_id, source_url FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=0 LIMIT 1").fetchone()
picks = [one_img, many_img, empty]
labels = ["single-image", "multi-image", "no-media"]

config = JobConfig.parse({"mode": "collect", "kind": "posts", "series_id": "6962", "allow_network": True,
                          "max_requests": 4, "max_attempts": 1, "timeout_seconds": 12})
report = []
with Repository(STOCK) as store:
    transport = Transport(store, store.begin_run({"purpose": "spot_check_3_posts"}), config)
    for label, row in zip(labels, picks):
        pid, url = row["post_id"], row["source_url"]
        dbrow = db.execute("SELECT body_text, content_segments_json FROM posts WHERE post_id=?", (pid,)).fetchone()
        stored = json.loads(dbrow["content_segments_json"] or "[]")
        stored_text = dbrow["body_text"] or ""
        try:
            raw = transport.get(url)
            record = post_page(raw["text"], pid, url, raw["retrieved_at"])
            live_segs = record.data["segments"]
            live_text = record.data["text_content"] or ""
            live_imgs = sum(1 for s in live_segs if s["kind"] == "image")
            live_vids = sum(1 for s in live_segs if s["kind"] == "video")
            entry = {"label": label, "post_id": pid, "http_status": raw["provenance"]["http_status"],
                     "live_text_len": len(live_text), "live_text_head": live_text[:60],
                     "live_imgs": live_imgs, "live_vids": live_vids,
                     "stored_text_len": len(stored_text), "stored_segments": len(stored),
                     "stored_imgs": sum(1 for s in stored if s["kind"] == "image"),
                     "verdict": None}
            if live_text.strip():
                entry["verdict"] = "HAS_TEXT_ONLINE -> stored record was incomplete (legacy miss)"
            elif live_imgs > 0:
                entry["verdict"] = "pure-image post confirmed (no text online)"
            else:
                entry["verdict"] = "no text and no images online -> post body truly empty or removed"
        except Exception as exc:
            entry = {"label": label, "post_id": pid, "error_code": getattr(exc, "code", str(exc))}
        report.append(entry)
        print(json.dumps(entry, ensure_ascii=False))
print("requests_used:", transport.used)
