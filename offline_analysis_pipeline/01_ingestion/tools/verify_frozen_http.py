"""Replay a separate copy of smoke-test material, with external sockets disabled."""
import argparse
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.contracts import canonical, digest, implementation_fingerprint
from autoinsight_ingestion.ingest import replay
from autoinsight_ingestion.storage import Repository


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-data", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("external network forbidden")):
        with Repository(args.input_data) as original:
            original.backup(out / "backup")
        Repository.restore(out / "backup", out / "replay-data")
        with Repository(out / "replay-data") as store:
            baseline = digest(store.logical_export())
            ids = [r[0] for r in store.db.execute("SELECT snapshot_id FROM source_snapshots ORDER BY snapshot_id")]
            results = []
            for rid in ids:
                try:
                    results.append(replay(store, rid))
                except Exception as e:
                    results.append({"response_id": rid, "error_code": getattr(e, "code", "replay_failed")})
            first = digest(store.logical_export())
            second_errors=[]
            for rid in ids:
                try:
                    replay(store, rid)
                except Exception as e:
                    second_errors.append({'response_id':rid,'error_code':getattr(e,'code','replay_failed')})
            repeat_same = first == digest(store.logical_export())
            checks = store.verify()
            posts = [dict(r) for r in store.db.execute("SELECT post_id,parser_version,quality_state FROM posts")]
    report = {"implementation": implementation_fingerprint(), "external_network_calls": 0,
              "replay_results": results, "repeated_replay_unchanged": repeat_same, "checks": checks,
              "live_business_rows_unchanged":baseline==first,"second_pass_errors":second_errors,
              "post_states": posts,
              "limitations": ["Saved source assertions, not independent semantic acceptance", "Initial live run is retained unchanged", "No fresh external requests"]}
    unexpected=[r for r in results if r.get('error_code') and r['error_code']!='cannot_replay_failed_http_response']
    report['unexpected_replay_errors']=len(unexpected)
    report['replay_acceptance_passed']=checks['ok'] and repeat_same and not unexpected
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(canonical({"ok": report['replay_acceptance_passed'], "unexpected_replay_errors":len(unexpected), "replayed_responses": len(ids), "post_states": posts}))


if __name__ == "__main__":
    main()
