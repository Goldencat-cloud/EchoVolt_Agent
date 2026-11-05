import sqlite3, json
db = sqlite3.connect(r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/data/stock/db/ingestion.sqlite3")
for n, sql in [("total", "SELECT COUNT(*) FROM posts WHERE quality_state='review_required'"),
    ("segments=0", "SELECT COUNT(*) FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=0"),
    ("segments=1", "SELECT COUNT(*) FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=1"),
    ("segs>=3", "SELECT COUNT(*) FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)>=3"),
    ("seg1 img", "SELECT COUNT(*) FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=1 AND json_extract(content_segments_json,'$[0].kind')='img'")]:
    print(n, ":", db.execute(sql).fetchone()[0])
print("sample seg1:", db.execute("SELECT json_extract(content_segments_json,'$[0].kind'), substr(content_segments_json,1,80) FROM posts WHERE quality_state='review_required' AND json_array_length(content_segments_json)=1 LIMIT 2").fetchall())
