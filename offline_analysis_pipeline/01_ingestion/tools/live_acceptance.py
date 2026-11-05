"""Real-site acceptance: bounded probe, ~N-post window, product params; writes verification.json."""
import argparse
import http.client
import json
import secrets
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.api import make_server
from autoinsight_ingestion.contracts import canonical, date_boundary, implementation_fingerprint, JobConfig
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.jobs import JobService
from autoinsight_ingestion.normalize.pages import forum_list
from autoinsight_ingestion.storage import Repository


class _StatsOnly(Exception):
    """Sentinel to skip collection and recompute statistics only."""


def wait_job(service, jid, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = service.status(jid)
        if result["state"] not in {"pending", "running", "cancelling"}:
            return result
        time.sleep(0.2)
    service.action(jid, "cancel")
    service.queue.join()
    return service.status(jid)


def submit_job(port, token, key, config, extra):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    client.request("POST", "/v1/ingestion/jobs", canonical({"config": config, **extra}),
                   {"Authorization": "Bearer " + token, "Idempotency-Key": key, "Content-Type": "application/json"})
    response = client.getresponse()
    body = json.loads(response.read())
    status = response.status
    client.close()
    return status, body


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--allow-network", action="store_true", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--credential-file")
    p.add_argument("--series-id", default="6962")
    p.add_argument("--target-count", type=int, default=30)
    p.add_argument("--max-requests", type=int, default=120)
    p.add_argument("--product-budget", type=int, default=8)
    p.add_argument("--stats-only", action="store_true", help="Skip collection; recompute statistics from existing data")
    args = p.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    posts_result = {}
    with Repository(out / "data") as store:
        service = JobService(store, allow_network=True, credential_path=args.credential_file)
        token = secrets.token_hex(24)
        server = make_server(service, port=0, token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if args.stats_only:
                raise _StatsOnly()
            # Probe: one list request to locate the lower bound for the target window.
            probe_config = JobConfig.parse(dict(mode="collect", kind="posts", series_id=args.series_id,
                                                allow_network=True, max_requests=1, max_attempts=1, timeout_seconds=12))
            probe_run = store.begin_run(probe_config.public())
            window_start = None
            probe = {"status": "failed"}
            try:
                raw = Transport(store, probe_run, probe_config).get(
                    f"https://club.m.autohome.com.cn/Adaptive/Forum/GetTopicListPartial2021?bbs=c&bbsid={args.series_id}&pageindex=1&sort=Lastest&qaType=-1",
                    validator=forum_list)
                items = [x for x in raw["parsed"] if not x.get("is_pinned")]
                chosen = items[args.target_count - 1] if len(items) >= args.target_count else items[-1]
                stamp = date_boundary(chosen["published_raw"].replace("/", "-"))
                window_start = stamp.isoformat()
                probe = {"status": "succeeded", "list_items": len(items),
                         "pinned_skipped": len(raw["parsed"]) - len(items),
                         "lower_bound_post": chosen["post_id"],
                         "lower_bound_time": chosen["published_raw"],
                         "lower_bound_precision": "second" if len(chosen["published_raw"]) > 10 else "day",
                         "page1_covers_target": len(items) >= args.target_count}
                store.mark_parsed(raw["response_id"], summary={"items": len(raw["parsed"])})
                store.finish_run(probe_run, "succeeded", {"requests": 1})
            except Exception as exc:
                probe = {"status": "failed", "error_code": getattr(exc, "code", str(exc))}
                store.finish_run(probe_run, "partial", probe)
            reports.append({"kind": "probe", **probe})

            if probe["status"] == "succeeded":
                posts_budget = args.max_requests - 1 - args.product_budget
                posts_config = {"mode": "collect", "kind": "posts", "series_id": args.series_id,
                                "max_requests": posts_budget, "max_pages": 4, "timeout_seconds": 12,
                                "max_attempts": 1, "rps": 1.0, "allow_network": True, "start": window_start}
                status, created = submit_job(server.server_port, token, "accept-posts", posts_config, {})
                if status == 202:
                    dup_status, dup = submit_job(server.server_port, token, "accept-posts", posts_config, {})
                    idempotent = dup.get("job_id") == created["job_id"]
                    posts_result = wait_job(service, created["job_id"])
                    reports.append({"kind": "posts", "api_status": status, "duplicate_same_job": idempotent, **posts_result})
                else:
                    reports.append({"kind": "posts", "api_status": status, **created})

                if (posts_result.get("result") or {}).get("error_code") in {"blocked", "blocked_or_rate_limited"}:
                    reports.append({"kind": "product_json", "skipped": "blocked"})
                else:
                    product_config = {"mode": "collect", "kind": "product_json", "series_id": args.series_id,
                                      "max_requests": args.product_budget, "max_pages": 1, "timeout_seconds": 12,
                                      "max_attempts": 1, "rps": 1.0, "allow_network": True}
                    status, created = submit_job(server.server_port, token, "accept-product", product_config, {})
                    if status == 202:
                        reports.append({"kind": "product_json", "api_status": status,
                                        **wait_job(service, created["job_id"])})
                    else:
                        reports.append({"kind": "product_json", "api_status": status, **created})
        except _StatsOnly:
            pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            service.close()

        attempts = store.db.execute("SELECT COUNT(*) FROM collection_runs,json_each(attempts_json)").fetchone()[0]
        http_statuses = {str(r[0]): r[1] for r in store.db.execute(
            "SELECT json_extract(value,'$.http_status'),COUNT(*) FROM collection_runs,json_each(attempts_json) GROUP BY 1")}
        cred_states = {str(r[0]): r[1] for r in store.db.execute(
            "SELECT json_extract(provenance_json,'$.credentials'),COUNT(*) FROM source_snapshots GROUP BY 1")}
        redirects = [r[0] for r in store.db.execute(
            "SELECT provenance_json FROM source_snapshots WHERE provenance_json LIKE '%redirect_target%'")]
        posts_total = store.db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        pub_ok = store.db.execute("SELECT COUNT(*) FROM posts WHERE published_at IS NOT NULL AND published_at!=''").fetchone()[0]
        order_status = {str(r[0]): r[1] for r in store.db.execute(
            "SELECT content_order_status, COUNT(*) FROM posts GROUP BY 1")}
        with_segments = store.db.execute(
            "SELECT COUNT(*) FROM posts WHERE content_segments_json IS NOT NULL AND json_array_length(content_segments_json)>0").fetchone()[0]
        users_total = store.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        users_with_profile = store.db.execute(
            "SELECT COUNT(*) FROM users WHERE follower_count IS NOT NULL OR following_count IS NOT NULL OR ip_location IS NOT NULL").fetchone()[0]
        params_total = store.db.execute("SELECT COUNT(*) FROM product_parameters").fetchone()[0]
        specs_total = store.db.execute("SELECT COUNT(*) FROM product_specs").fetchone()[0]
        failure_codes = {str(r[0]): r[1] for r in store.db.execute(
            "SELECT error_code, COUNT(*) FROM collection_failures GROUP BY 1 ORDER BY 2 DESC LIMIT 10")}
        checkpoints = [dict(r) for r in store.db.execute(
            "SELECT scope_key, covered_from, checked_until, updated_at FROM collection_checkpoints")]
        checks = store.verify()
        posts_report = next((r for r in reports if r.get("kind") == "posts"), {})

    report = {
        "implementation": implementation_fingerprint(),
        "credential_file": bool(args.credential_file),
        "target_count": args.target_count,
        "request_budget": args.max_requests,
        "actual_requests": attempts,
        "within_budget": attempts <= args.max_requests,
        "api_jobs": reports,
        "posts": {"total": posts_total, "published_at_parsed": pub_ok,
                  "publication_parse_rate": round(pub_ok / posts_total, 3) if posts_total else 0.0,
                  "with_segments": with_segments, "order_status": order_status},
        "users": {"total": users_total, "with_home_fields": users_with_profile},
        "products": {"specs": specs_total, "parameters": params_total},
        "http_statuses": http_statuses, "snapshot_credential_states": cred_states,
        "redirects_recorded": len(redirects),
        "redirect_targets": [json.loads(r).get("redirect_target") for r in redirects][:10],
        "failure_codes": failure_codes, "checkpoints": checkpoints,
        "idempotent_duplicate_same_job": posts_report.get("duplicate_same_job"),
        "storage_checks": {"ok": checks["ok"], "counts": checks.get("counts", {})},
        "limitations": ["Single forum page window per probe", "max_attempts=1, no retry",
                        "Cookie values never persisted; only provided/absent state recorded"],
    }
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(canonical({"actual_requests": attempts, "within_budget": attempts <= args.max_requests,
                     "posts": posts_total, "publication_parse_rate": report["posts"]["publication_parse_rate"],
                     "users": users_total, "users_with_home_fields": users_with_profile,
                     "parameters": params_total, "checkpoint_advanced": bool(checkpoints),
                     "idempotent": report["idempotent_duplicate_same_job"], "storage_ok": checks["ok"]}))


if __name__ == "__main__":
    main()
