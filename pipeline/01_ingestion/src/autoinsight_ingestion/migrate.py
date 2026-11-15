"""Explicit, read-only v1 snapshot migration into a brand-new v2 directory."""
import hashlib
import json
import sqlite3
from pathlib import Path

from .contracts import IngestionError,relative_path
from .storage import Repository
from .ingest import import_bytes,replay


def migrate_v1(source,target):
    source,target=Path(source).resolve(),Path(target).resolve()
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise IngestionError('migration_target_must_be_new_and_separate')
    database=source/'db/ingestion.sqlite3'
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    old=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True); old.row_factory=sqlite3.Row
    try:
        if old.execute('PRAGMA user_version').fetchone()[0]!=1: raise IngestionError('migration_requires_v1')
        rows=old.execute('SELECT s.*,b.relative_path,r.config_json,t.run_id original_run FROM source_responses s JOIN raw_blobs b ON b.sha256=s.blob_hash JOIN tasks t USING(task_id) JOIN runs r USING(run_id) ORDER BY CASE json_extract(r.config_json,\'$.kind\') WHEN \'series\' THEN 0 ELSE 1 END,s.retrieved_at,s.response_id').fetchall()
        # Validate every source before creating any destination files.
        for row in rows:
            if hashlib.sha256(relative_path(source,row['relative_path']).read_bytes()).hexdigest()!=row['blob_hash']:
                raise IngestionError('legacy_blob_corrupt')
        results=[]; http=[]; runs={}
        with Repository(target) as store:
            for row in rows:
                config=json.loads(row['config_json']); provenance=json.loads(row['provenance_json'])
                content=relative_path(source,row['relative_path']).read_bytes()
                if row['material_kind']=='http_body':
                    if row['original_run'] not in runs: runs[row['original_run']]=store.begin_run(config)
                    run=runs[row['original_run']]
                    task=store.task(run,'migrate',row['response_id'])
                    http.append(store.response(task,content,provenance,row['retrieved_at'],'http_body'))
                else:
                    results.append(import_bytes(store,content,config['kind'],provenance,series_id=config.get('series_id',''),retrieved_at=row['retrieved_at']))
            for rid in http:
                try: results.append(replay(store,rid))
                except IngestionError as exc: results.append(dict(response_id=rid,error_code=exc.code))
            for run in runs.values(): store.finish_run(run,'partial',{'migration':'raw_http_preserved'})
            checks=store.verify()
    finally: old.close()
    unchanged=before==hashlib.sha256(database.read_bytes()).hexdigest()
    if not unchanged: raise IngestionError('source_database_changed_during_migration')
    return dict(source_database_sha256=before,source_unchanged=unchanged,snapshots=len(rows),results=results,checks=checks)
