"""User-authorized exact-ID removal; raw inputs and non-post business data stay intact."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from autoinsight_ingestion.storage import Repository
from autoinsight_ingestion.contracts import canonical,digest


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',action='append',required=True)
    p.add_argument('--report',required=True)
    args=p.parse_args()
    policy=json.loads((Path(__file__).resolve().parents[1]/'configs/excluded-stock-posts.json').read_text(encoding='utf-8'))
    ids=policy['excluded_post_ids']
    if len(ids)!=127 or len(set(ids))!=127 or not all(i.isdigit() for i in ids):
        raise ValueError('unexpected_removal_scope')
    results=[]
    for name in args.data_root:
        root=Path(name).resolve()
        if not (root/'db/ingestion.sqlite3').is_file(): raise ValueError('database_missing')
        with Repository(root) as store:
            placeholders=','.join('?' for _ in ids)
            before=store.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
            matched=store.db.execute('SELECT COUNT(*) FROM posts WHERE post_id IN ('+placeholders+')',ids).fetchone()[0]
            if matched not in (0,127): raise ValueError('unexpected_partial_removal_scope')
            run=store.begin_run(dict(mode='maintenance',action='exclude_stock_posts',policy_sha256=digest(policy)))
            with store.transaction() as db:
                removed=db.execute('DELETE FROM posts WHERE post_id IN ('+placeholders+')',ids).rowcount
                remaining=db.execute('SELECT COUNT(*) FROM posts WHERE post_id IN ('+placeholders+')',ids).fetchone()[0]
                if remaining: raise ValueError('removal_failed')
            after=store.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
            store.finish_run(run,'succeeded',dict(posts_before=before,removed_posts=removed,posts_after=after))
            checks=store.verify()
            if not checks['ok']: raise ValueError('integrity_failed')
        manifest_path=root/'backup-manifest.json'
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['files']['db/ingestion.sqlite3']=hashlib.sha256((root/'db/ingestion.sqlite3').read_bytes()).hexdigest()
            manifest_path.write_text(canonical(manifest),encoding='utf-8')
        results.append(dict(data_root=str(root),removed_posts=removed,posts_before=before,posts_after=after,remaining_excluded_posts=remaining,integrity_ok=checks['ok']))
    report=Path(args.report)
    with report.open('x',encoding='utf-8') as f:
        json.dump(dict(policy_sha256=digest(policy),raw_sources_modified=False,results=results),f,ensure_ascii=False,indent=2)
    print(canonical(dict(results=results,raw_sources_modified=False)))


if __name__=='__main__': main()
