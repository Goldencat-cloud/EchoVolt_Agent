"""Replay stock legacy_csv snapshots through the updated parser (legacy-4); same provenance+retrieved_at -> same snapshot_id."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/data/stock")
sys.path.insert(0, r"d:/Desktop/Competitions/new_energy_data_analysis_agent/offline_analysis_pipeline/01_ingestion/src")
from autoinsight_ingestion.storage import Repository
from autoinsight_ingestion.ingest import import_bytes

db = sqlite3 = __import__("sqlite3").connect(ROOT / "db" / "ingestion.sqlite3")
rows = db.execute("SELECT relative_path, provenance_json, retrieved_at FROM source_snapshots WHERE material_kind='legacy_csv' ORDER BY retrieved_at").fetchall()
db.close()
print(f"replaying {len(rows)} legacy_csv snapshots in retrieved_at order")
totals = {}
with Repository(ROOT) as store:
    for rel, prov, rat in rows:
        content = gzip.decompress((ROOT / (rel + ".gz")).read_bytes())
        provenance = json.loads(prov)
        member = provenance.get("member", "")
        series_id = "6962" if any(k in member for k in ("配置明细", "车型清单")) else ""
        if "车系库" in member:
            kind = "series"
        elif "车型清单" in member:
            kind = "models"
        elif "配置明细" in member:
            kind = "parameters"
        elif "user_profiles" in member:
            kind = "users"
        else:
            kind = "posts"
        result = import_bytes(store, content, kind, provenance, series_id=series_id, retrieved_at=rat)
        stats = {k: v for k, v in result.items() if isinstance(v, (int, float))}
        totals.setdefault(kind, []).append((member.split("/")[-1], stats))
        print(kind, member.split("/")[-1], json.dumps(stats))
    checks = store.verify()
print("verify ok:", checks["ok"], "| counts:", json.dumps(checks.get("counts", {}), ensure_ascii=False)[:200])
