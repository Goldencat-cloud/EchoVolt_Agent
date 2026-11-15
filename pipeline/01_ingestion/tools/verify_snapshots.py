"""Read-only supplied-ZIP ingestion and portable replay acceptance exercise."""
import argparse
import hashlib
import json
import socket
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.contracts import canonical, digest, implementation_fingerprint
from autoinsight_ingestion.ingest import import_bytes, read_input, replay
from autoinsight_ingestion.storage import Repository


def find_member(archive, predicate):
    with zipfile.ZipFile(archive) as z:
        matches = [n for n in z.namelist() if predicate(n)]
    if len(matches) != 1:
        raise ValueError("input_selection_not_unique")
    return matches[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mcp-zip", required=True)
    p.add_argument("--handover-zip", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_hashes = {}
    for path in [args.mcp_zip, args.handover_zip]:
        with open(path, "rb") as f:
            source_hashes[Path(path).name] = hashlib.file_digest(f, "sha256").hexdigest()
    selections = [
        (args.mcp_zip, lambda n: n == "mcp/car_config/output/车系库.csv", "series", ""),
        (args.mcp_zip, lambda n: n == "mcp/car_config/su7_车型清单.csv", "models", "6962"),
        (args.mcp_zip, lambda n: n == "mcp/car_config/su7_配置明细_长表.csv", "parameters", "6962"),
        (args.mcp_zip, lambda n: "/forum_posts/output/合并完整_" in n and n.endswith(".csv"), "posts", ""),
        (args.mcp_zip, lambda n: n == "mcp/user_profile/user_profiles.csv", "users", ""),
        (args.handover_zip, lambda n: "/01_采集/data/001_" in n and n.endswith(".csv"), "posts", ""),
    ]
    imports = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("external network forbidden")):
        with Repository(out / "original") as store:
            for archive, predicate, kind, series_id in selections:
                member = find_member(archive, predicate)
                content, provenance = read_input(archive, member)
                provenance['source_priority']=10 if archive==args.handover_zip else 20
                result = import_bytes(store, content, kind, provenance, series_id=series_id)
                imports.append({"archive": Path(archive).name, "member": member, "kind": kind, **result})
            baseline = store.logical_export()
            baseline_hash = digest(baseline)
            initial = store.verify()
            for row in imports:
                replay(store, row["response_id"])
            repeat_unchanged = baseline_hash == digest(store.logical_export())
            store.backup(out / "backup")
            entity_counts = {t:store.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['posts','users','product_specs','product_parameters']}
        Repository.restore(out / "backup", out / "恢复 目录")
        with Repository(out / "恢复 目录") as restored:
            restore_unchanged = baseline_hash == digest(restored.logical_export())
            # No archive or old absolute path is passed to replay.
            for row in imports:
                replay(restored, row["response_id"])
            restored_replay_unchanged = baseline_hash == digest(restored.logical_export())
            restored_checks = restored.verify()
    after = {}
    for path in [args.mcp_zip, args.handover_zip]:
        with open(path, "rb") as f:
            after[Path(path).name] = hashlib.file_digest(f, "sha256").hexdigest()
    report = {"implementation": implementation_fingerprint(), "source_hashes": source_hashes,
              "source_hashes_unchanged": source_hashes == after, "imports": imports,
              "initial_checks": initial, "current_record_counts": entity_counts,
              "repeated_import_unchanged": repeat_unchanged, "restored_export_unchanged": restore_unchanged,
              "restored_replay_unchanged": restored_replay_unchanged, "restored_checks": restored_checks,
              "logical_export_sha256": baseline_hash, "external_network_calls": 0,
              "limitations": ["Historical dates without a proven acquisition anchor remain unknown", "Observed versions are not additional posts or people", "Same-machine directory migration only; no second physical computer test", "Not semantic acceptance or live collection validation"]}
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = all([initial["ok"], restored_checks["ok"], repeat_unchanged, restore_unchanged, restored_replay_unchanged, source_hashes == after])
    print(canonical({"ok": passed, "entity_counts": entity_counts, "checks": initial["counts"]}))
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
