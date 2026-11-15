"""Explicit, seven-request maximum real-site smoke test through the local HTTP API."""
import argparse
import csv
import http.client
import io
import json
import secrets
import sys
import threading
import time
import zipfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.api import make_server
from autoinsight_ingestion.contracts import canonical, implementation_fingerprint, JobConfig, date_boundary
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.normalize.pages import forum_list
from autoinsight_ingestion.jobs import JobService
from autoinsight_ingestion.storage import Repository


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--allow-network", action="store_true", required=True)
    p.add_argument("--mcp-zip", required=True)
    p.add_argument("--output", required=True)
    p.add_argument('--author-card-only',action='store_true',help='One user-card request through the API, no forum collection')
    p.add_argument('--integration',action='store_true',help='Discover a narrow current window; total maximum 16 requests')
    p.add_argument('--complete-existing',action='store_true',help='Finish remaining branches of an interrupted integration harness')
    args = p.parse_args()
    if args.complete_existing and not args.integration: p.error('--complete-existing requires --integration')
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=args.complete_existing)
    with zipfile.ZipFile(args.mcp_zip) as z:
        uid = next(csv.DictReader(io.StringIO(z.read("mcp/user_profile/user_profiles.csv").decode("utf-8-sig"))))["user_id"]
    reports = []
    discovery = {}; window = {}; budget_total = 1 if args.author_card_only else (16 if args.integration else 7)
    with Repository(out / "data") as store:
        service = JobService(store, allow_network=True)
        token = secrets.token_hex(24)
        server = make_server(service, port=0, token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            plan=[('users',1,{'user_ids':[uid]})] if args.author_card_only else [("posts", 2, {}), ("users", 1, {"user_ids": [uid]}), ("product_json", 4, {})]
            if args.complete_existing:
                previous=store.db.execute("SELECT run_id,state,counts_json,request_json FROM collection_runs WHERE idempotency_key='live-posts'").fetchone()
                if previous is None: raise RuntimeError('missing_prior_post_job')
                reports.append({'kind':'posts','job_id':previous[0],'state':previous[1],'counts':json.loads(previous[2]),'duplicate_submission_same_job':None,'limitation':'First harness stopped after duplicate submission; response not persisted'})
                discovery={'status':'previously_completed','harness_recovered':True}
                plan=[('users',3,{'user_ids':[uid]}),('product_json',4,{})]
            elif args.integration:
                cfg=JobConfig.parse(dict(mode='collect',kind='posts',series_id='6962',allow_network=True,max_requests=1,max_attempts=1,timeout_seconds=12))
                run=store.begin_run(cfg.public())
                try:
                    raw=Transport(store,run,cfg).get('https://club.m.autohome.com.cn/Adaptive/Forum/GetTopicListPartial2021?bbs=c&bbsid=6962&pageindex=1&sort=Lastest&qaType=-1',validator=forum_list)
                    items=[x for x in raw['parsed'] if not x.get('is_pinned')]
                    latest=items[0]; stamp=date_boundary(latest['published_raw'].replace('/','-'))
                    if len(latest['published_raw'])==10: raise ValueError('discovery_time_precision_insufficient')
                    window={'start':stamp.isoformat(),'end':(stamp+timedelta(seconds=1)).isoformat()}
                    uid=latest.get('author_id') or uid
                    discovery={'status':'succeeded','window':window,'list_items':len(items)}
                    store.mark_parsed(raw['response_id'],summary={'items':len(raw['parsed'])})
                    store.finish_run(run,'succeeded',{'requests':1})
                    plan=[('posts',8,{}),('users',3,{'user_ids':[uid]}),('product_json',4,{})]
                except Exception as exc:
                    discovery={'status':'failed','error_code':getattr(exc,'code',str(exc))}
                    store.finish_run(run,'partial',discovery)
                    plan=[]
            for kind, budget, extra in plan:
                config = {"mode": "collect", "kind": kind, "series_id": "6962", "max_requests": budget,
                          "max_pages": 1, "timeout_seconds": 12, "max_attempts": 1, "rps": 1.0, "allow_network": True}
                if kind=='posts': config.update(window or {'start':'2026-10-01'})
                if kind=='users' and args.integration:
                    author=store.db.execute('SELECT author_id FROM posts WHERE author_id IS NOT NULL LIMIT 1').fetchone()
                    if author: uid=author[0]; extra={'user_ids':[uid]}
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                client.request("POST", "/v1/ingestion/jobs", canonical({"config": config, **extra}),
                               {"Authorization": "Bearer " + token, "Idempotency-Key": "live-" + kind, "Content-Type": "application/json"})
                response = client.getresponse(); created = json.loads(response.read()); status = response.status; client.close()
                if status != 202:
                    reports.append({"kind": kind, "api_status": status, "error_code": created.get("error_code")})
                    continue
                duplicate = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                duplicate.request('POST','/v1/ingestion/jobs',canonical({'config':config,**extra}),{'Authorization':'Bearer '+token,'Idempotency-Key':'live-'+kind,'Content-Type':'application/json'})
                dr=duplicate.getresponse(); same=json.loads(dr.read()); duplicate.close()
                idempotent=same.get('job_id')==created['job_id']
                deadline = time.monotonic() + 100
                while time.monotonic() < deadline:
                    result = service.status(created["job_id"])
                    if result["state"] not in {"pending", "running", "cancelling"}:
                        break
                    time.sleep(0.1)
                else:
                    service.action(created["job_id"], "cancel")
                    service.queue.join()
                    result = service.status(created["job_id"])
                reports.append({"kind": kind, "api_status": status, 'duplicate_submission_same_job':idempotent, **result})
                if (result.get('result') or {}).get('error_code') in {'blocked','blocked_or_rate_limited'}: break
        finally:
            server.shutdown(); server.server_close(); thread.join(); service.close()
        checks = store.verify()
        attempts = store.db.execute("SELECT COUNT(*) FROM collection_runs,json_each(attempts_json)").fetchone()[0]
        http_statuses = {str(r[0]): r[1] for r in store.db.execute("SELECT json_extract(value,'$.http_status'),COUNT(*) FROM collection_runs,json_each(attempts_json) GROUP BY 1")}
        row=store.db.execute('SELECT platform_post_count,popular_post_count,platform_reply_count,declared_vehicle,popular_post_urls_json FROM users WHERE user_id=?',(uid,)).fetchone()
        fields=['platform_post_count','popular_post_count','platform_reply_count','declared_vehicle','popular_post_urls_json']
        author_fields={k:row[i] is not None and row[i]!='' for i,k in enumerate(fields)} if row else {}
    report = {"implementation": implementation_fingerprint(), "request_budget": budget_total, "actual_requests": attempts,
              "within_budget": attempts <= budget_total, "cookies_used": False, "api_jobs": reports,'discovery':discovery,
              "http_statuses": http_statuses, "storage_checks": checks,
              'author_card_only':args.author_card_only,'author_field_presence':author_fields,
              "semantic_acceptance": "not_measured", "full_coverage": "not_proven",
              "limitations": ["One visible forum page, one user, one product series only", "No credential reuse or bypass", "Site failures retained as failures, not empty data"]}
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(canonical({"actual_requests": attempts, "within_budget": attempts <= budget_total, "states": {r["kind"]: r.get("state", "failed") for r in reports}, "storage_ok": checks["ok"]}))


if __name__ == "__main__":
    main()
