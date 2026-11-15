from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .. import CLEANER_VERSION, QUALITY_VERSION, SCHEMA_VERSION
from ..contracts import IngestionError, canonical, digest, now, relative_path, implementation_fingerprint, safe_metadata
from ..standard import project

TABLES = ('posts','users','product_specs','product_parameters','source_snapshots',
          'collection_runs','collection_failures','collection_checkpoints')
BUSINESS = TABLES[:4]


class WriterLock:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        if self.file.seek(0, 2) == 0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise IngestionError('data_root_in_use') from None

    def close(self):
        if not self.file.closed:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


class Repository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if (self.root / '.git').exists():
            raise IngestionError('repository_root_is_not_data_root')
        if self.root.exists() and any(self.root.iterdir()) and not (self.root/'db/ingestion.sqlite3').exists():
            raise IngestionError('nonempty_unrecognized_data_root')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = WriterLock(self.root/'writer.lock')
        self.mutex = threading.RLock()
        self._catalog = None
        try:
            (self.root/'db').mkdir(exist_ok=True)
            self.db = sqlite3.connect(self.root/'db/ingestion.sqlite3', check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA busy_timeout=5000')
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version == 1:
                raise IngestionError('legacy_database_use_new_target')
            if version not in (0, SCHEMA_VERSION):
                raise IngestionError('unsupported_database_version')
            schema = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
            if not version:
                if self.db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0]:
                    raise IngestionError('unversioned_nonempty_database')
                self.db.executescript('BEGIN IMMEDIATE;\n'+schema+f'\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')
            # Compare actual schema to the versioned source, without a ninth metadata table.
            with sqlite3.connect(':memory:') as expected:
                expected.executescript(schema)
                query = "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                if [tuple(r) for r in self.db.execute(query)] != expected.execute(query).fetchall():
                    raise IngestionError('applied_schema_changed')
        except BaseException:
            if hasattr(self, 'db'): self.db.close()
            self.lock.close()
            raise

    def close(self):
        with self.mutex:
            self.db.close(); self.lock.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    @contextmanager
    def transaction(self):
        with self.mutex:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback(); raise

    def begin_run(self, config, run_id=None):
        config = dict(config, implementation=implementation_fingerprint())
        t = now()
        with self.transaction() as db:
            if run_id:
                db.execute("UPDATE collection_runs SET config_json=?,state='running',started_at=?,updated_at=? WHERE run_id=?",
                           (canonical(config),t,t,run_id))
            else:
                run_id = uuid.uuid4().hex
                db.execute('INSERT INTO collection_runs(run_id,config_json,state,created_at,started_at,updated_at) VALUES(?,?,?,?,?,?)',
                           (run_id,canonical(config),'running',t,t,t))
        return run_id

    def finish_run(self, run_id, status, counts):
        with self.transaction() as db:
            db.execute('UPDATE collection_runs SET state=?,counts_json=?,finished_at=?,updated_at=? WHERE run_id=?',
                       (status,canonical(counts),now(),now(),run_id))

    def task(self, run_id, kind, key):
        # An in-memory request locator, not another durable task hierarchy.
        return run_id+':'+digest([kind,key])

    def save_blob(self, content):
        sha = hashlib.sha256(content).hexdigest()
        name = f'raw/sha256/{sha[:2]}/{sha}'
        path = relative_path(self.root,name); path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise IngestionError('existing_blob_corrupt')
        else:
            tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
            with tmp.open('xb') as f:
                f.write(content); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        return sha, name

    def response(self, task_id, content, provenance, retrieved_at=None, material_kind='legacy_csv'):
        provenance = safe_metadata(provenance)
        sha, name = self.save_blob(content)
        rid = digest([sha,provenance,retrieved_at,material_kind])
        run = task_id.split(':')[0]
        with self.transaction() as db:
            config = db.execute('SELECT config_json FROM collection_runs WHERE run_id=?',(run,)).fetchone()
            db.execute('INSERT OR IGNORE INTO source_snapshots(snapshot_id,run_id,sha256,relative_path,byte_count,retrieved_at,material_kind,provenance_json,parse_config_json) VALUES(?,?,?,?,?,?,?,?,?)',
                       (rid,run,sha,name,len(content),retrieved_at,material_kind,canonical(provenance),config[0]))
        return rid

    def failure(self, run_id, target, code, *, page=None, snapshot_id=None):
        fid = digest([run_id,target,code])
        with self.transaction() as db:
            db.execute("INSERT INTO collection_failures VALUES(?,?,?,?,?,?,1,'pending',?) ON CONFLICT(failure_id) DO UPDATE SET attempt_count=attempt_count+1,state='pending',snapshot_id=COALESCE(excluded.snapshot_id,snapshot_id),updated_at=excluded.updated_at",
                       (fid,run_id,target,code,page,snapshot_id,now()))

    def resolved(self, run_id, target):
        with self.transaction() as db:
            db.execute("UPDATE collection_failures SET state='resolved',updated_at=? WHERE run_id=? AND target=?",(now(),run_id,target))

    def attempt(self, run_id, url, status, error, snapshot_id, acquired):
        entry = canonical(dict(url=url,http_status=status,error_code=error,snapshot_id=snapshot_id,attempted_at=acquired))
        with self.transaction() as db:
            db.execute("UPDATE collection_runs SET attempts_json=json_insert(attempts_json,'$[#]',json(?)) WHERE run_id=?",(entry,run_id))

    def mark_parsed(self, snapshot_id, state='succeeded', summary=None):
        with self.transaction() as db:
            db.execute('UPDATE source_snapshots SET parse_state=?,summary_json=? WHERE snapshot_id=?',(state,canonical(summary or {}),snapshot_id))

    @staticmethod
    def _time(value):
        if not value: return None
        try:
            t = datetime.fromisoformat(value)
            return t.timestamp() if t.tzinfo else None
        except (ValueError,TypeError): return None

    def _upsert(self, db, table, data, keys, meta):
        where = ' AND '.join(k+'=?' for k in keys)
        old = db.execute('SELECT * FROM '+table+' WHERE '+where,tuple(data[k] for k in keys)).fetchone()
        retained={}
        if old:
            incoming, previous = self._time(meta['retrieved_at']), self._time(old['retrieved_at'])
            if previous is not None and (incoming is None or incoming < previous): return 'older_skipped'
            if incoming == previous and old['snapshot_id'] != meta['snapshot_id']:
                old_meta = json.loads(db.execute('SELECT provenance_json FROM source_snapshots WHERE snapshot_id=?',(old['snapshot_id'],)).fetchone()[0])
                new_meta = json.loads(db.execute('SELECT provenance_json FROM source_snapshots WHERE snapshot_id=?',(meta['snapshot_id'],)).fetchone()[0])
                a,b=new_meta.get('source_priority',0),old_meta.get('source_priority',0)
                if a<b: return 'older_skipped'
                if a==b and any(data[k] not in (None,'') and old[k] not in (None,'') and data[k]!=old[k]
                                for k in data if k!='field_availability_json'): return 'conflict'
            nonbusiness={'snapshot_id','source_locator','retrieved_at','parser_version','cleaner_version','quality_version','quality_state','issues_json','record_hash','retained_fields_json'}
            prior_retained=json.loads(old['retained_fields_json'])
            for k in old.keys():
                if k in nonbusiness: continue
                if k not in data or (data[k] in (None,'') and old[k] not in (None,'')):
                    data[k]=old[k]
                    if old[k] not in (None,''):
                        retained[k]=prior_retained.get(k,dict(snapshot_id=old['snapshot_id'],retrieved_at=old['retrieved_at']))
            if old['record_hash']==digest(data): return 'unchanged'
            if old['snapshot_id']==meta['snapshot_id'] and old['parser_version']==meta['parser_version']:
                raise IngestionError('unversioned_processing_change')
        row = dict(data,**meta,record_hash=digest(data),retained_fields_json=canonical(retained))
        cols = list(row)
        db.execute('INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+') ON CONFLICT('+','.join(keys)+') DO UPDATE SET '+','.join(k+'=excluded.'+k for k in cols if k not in keys),tuple(row[k] for k in cols))
        return 'updated' if old else 'inserted'

    def ingest(self, run_id, task_id, response_id, records, *, fail_after=None):
        from ..quality.batch import BatchProfile
        profile=BatchProfile()
        counts = dict(rows=0,excluded=0,inserted=0,updated=0,unchanged=0,older_skipped=0,conflict=0,incomplete_skipped=0,ready=0,review_required=0,rejected=0)
        policy_path=Path(__file__).resolve().parents[3]/'configs/excluded-stock-posts.json'
        policy=json.loads(policy_path.read_text(encoding='utf-8'))
        excluded=set(policy['excluded_post_ids'])
        issues = []
        with self.transaction() as db:
            snapshot = db.execute('SELECT * FROM source_snapshots WHERE snapshot_id=?',(response_id,)).fetchone()
            if not snapshot: raise IngestionError('response_missing')
            for record in records:
                if record.kind=='posts' and snapshot['material_kind']=='legacy_csv' and record.source_id in excluded:
                    counts['excluded']+=1
                    continue
                if record.kind == 'series': self._catalog=None
                if record.kind == 'parameters':
                    record.data.update(self.series_details(record.data.get('series_id')))
                profile.add(record)
                counts['rows'] += 1; counts[record.quality_state] += 1
                issues.extend(dict(code=c,locator=record.locator) for c in record.issues)
                if record.audit:
                    issues.append(dict(code='legacy_audit',locator=record.locator,values=record.audit))
                    if record.audit.get('legacy_error'):
                        fid=digest([run_id,record.locator,'legacy_source_error'])
                        db.execute("INSERT OR IGNORE INTO collection_failures VALUES(?,?,?,?,NULL,?,1,'pending',?)",(fid,run_id,record.locator,'legacy_source_error',response_id,now()))
                if not record.rejected:
                    table,data = project(record)
                    if table:
                        meta = dict(snapshot_id=response_id,source_locator=record.locator,retrieved_at=snapshot['retrieved_at'],parser_version=record.parser_version,cleaner_version=CLEANER_VERSION,quality_version=QUALITY_VERSION,quality_state=record.quality_state,issues_json=canonical(record.issues))
                        if table == 'users':
                            meta['retrieved_at'] = record.data.get('fetched_at') if self._time(record.data.get('fetched_at')) is not None else snapshot['retrieved_at']
                        result = self._upsert(db,table,data,{'posts':['post_id'],'users':['user_id'],'product_specs':['spec_id']}[table],meta)
                        counts[result] += 1
                        if result in {'conflict','incomplete_skipped'}:
                            issues.append(dict(code=result,locator=record.locator))
                        if table == 'product_specs':
                            for p in record.data.get('parameters',[]):
                                item = dict(spec_id=record.source_id,source_item_key=p['source_item_key'],group_name=p.get('group_name'),category=p.get('category'),parameter_name=p.get('name'),value_raw=p.get('raw_value'),source_value_json=canonical(p.get('source_value')) if p.get('source_value') is not None else None)
                                pm = dict(meta,source_locator=p.get('source_locator',record.locator))
                                self._upsert(db,'product_parameters',item,['spec_id','source_item_key'],pm)
                if fail_after and counts['rows'] >= fail_after:
                    raise IngestionError('injected_transaction_failure')
            counts['batch_quality']=profile.report()
            counts['exclusion_policy_sha256']=digest(policy)
            db.execute("UPDATE source_snapshots SET parse_state='succeeded',issues_json=?,summary_json=? WHERE snapshot_id=?",(canonical(issues),canonical(counts),response_id))
        return counts

    def series_details(self,series_id):
        if self._catalog is None:
            from ..normalize.legacy import series
            self._catalog={}
            with self.mutex:
                sources=self.db.execute("SELECT relative_path FROM source_snapshots WHERE json_extract(parse_config_json,'$.kind')='series' ORDER BY snapshot_id").fetchall()
            for row in sources:
                for rec in series(relative_path(self.root,row[0]).read_bytes()):
                    # Conflicting catalog names must not be selected by hash ordering.
                    old=self._catalog.get(rec.source_id)
                    value={k:rec.data[k] for k in ['brand_name','series_name','manufacturer_name']}
                    if old is not None and old!=value: raise IngestionError('catalog_conflict')
                    self._catalog[rec.source_id]=value
        return self._catalog.get(series_id,{})

    def verify(self):
        with self.mutex:
            errors = []
            if self.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': errors.append('sqlite_integrity')
            if list(self.db.execute('PRAGMA foreign_key_check')): errors.append('foreign_keys')
            known = set()
            for r in self.db.execute('SELECT DISTINCT sha256,relative_path,byte_count FROM source_snapshots'):
                p = relative_path(self.root,r['relative_path']); known.add(r['relative_path'])
                if not p.is_file() or p.stat().st_size != r['byte_count'] or hashlib.sha256(p.read_bytes()).hexdigest() != r['sha256']:
                    errors.append('blob_missing_or_corrupt:'+r['sha256'])
            counts = {t:self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES}
            extra = [p.relative_to(self.root).as_posix() for p in (self.root/'raw').rglob('*') if p.is_file() and p.relative_to(self.root).as_posix() not in known] if (self.root/'raw').exists() else []
            return dict(ok=not errors,errors=errors,counts=counts,unregistered_files=extra)

    def logical_export(self):
        output=[]
        with self.mutex:
            for table in BUSINESS:
                for row in self.db.execute('SELECT * FROM '+table+' ORDER BY 1,2'):
                    d=dict(row)
                    sid=d.pop('snapshot_id'); locator=d.pop('source_locator')
                    for k in ['retrieved_at','record_hash']: d.pop(k)
                    for k in list(d):
                        if k.endswith('_json') and d[k] is not None: d[k[:-5]]=json.loads(d.pop(k))
                    raw=self.db.execute('SELECT sha256 FROM source_snapshots WHERE snapshot_id=?',(sid,)).fetchone()[0]
                    output.append(dict(schema_version='ingestion-2',kind=table,source_id=d.get('post_id') or d.get('user_id') or d.get('spec_id'),raw_hash=raw,locator=locator,data=d))
        return output

    def backup(self,target):
        target=Path(target).resolve()
        if target.exists() or target.is_relative_to(self.root) or self.root.is_relative_to(target):
            raise IngestionError('backup_target_must_be_new_and_separate')
        with self.mutex:
            if not self.verify()['ok']: raise IngestionError('cannot_backup_corrupt_store')
            (target/'db').mkdir(parents=True)
            dest=sqlite3.connect(target/'db/ingestion.sqlite3')
            try: self.db.backup(dest)
            finally: dest.close()
            for row in self.db.execute('SELECT DISTINCT relative_path FROM source_snapshots'):
                dst=relative_path(target,row[0]); dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(relative_path(self.root,row[0]),dst)
            files={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
            (target/'backup-manifest.json').write_text(canonical(dict(schema_version=SCHEMA_VERSION,files=files)),encoding='utf-8')
        return dict(files=len(files),manifest_hash=digest(files))

    @classmethod
    def restore(cls,source,target):
        source,target=Path(source).resolve(),Path(target).resolve()
        if target.exists(): raise IngestionError('restore_target_exists')
        manifest=json.loads((source/'backup-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('schema_version') != SCHEMA_VERSION or 'db/ingestion.sqlite3' not in manifest.get('files',{}): raise IngestionError('invalid_backup_manifest')
        for name,sha in manifest['files'].items():
            if name != 'db/ingestion.sqlite3' and not name.startswith('raw/sha256/'): raise IngestionError('unexpected_backup_file')
            p=relative_path(source,name)
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha: raise IngestionError('backup_file_corrupt')
        for name in manifest['files']:
            dst=relative_path(target,name); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(relative_path(source,name),dst)
        with cls(target) as store:
            checks=store.verify()
            if not checks['ok']: raise IngestionError('restored_store_invalid')
        return checks

    def create_job(self,key,request):
        if not isinstance(key,str) or not 1<=len(key)<=128: raise IngestionError('invalid_idempotency_key')
        with self.transaction() as db:
            old=db.execute('SELECT run_id,request_hash FROM collection_runs WHERE idempotency_key=?',(key,)).fetchone()
            if old:
                if old[1]!=digest(request): raise IngestionError('idempotency_conflict')
                return old[0],False
            rid,t=uuid.uuid4().hex,now()
            db.execute('INSERT INTO collection_runs(run_id,idempotency_key,request_hash,request_json,config_json,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                       (rid,key,digest(request),canonical(request),canonical(request.get('config',{})),'pending',t,t))
        return rid,True

    def job(self,jid):
        with self.mutex:
            row=self.db.execute('SELECT * FROM collection_runs WHERE run_id=?',(jid,)).fetchone()
            if not row: raise IngestionError('job_not_found')
            return dict(row,job_id=row['run_id'])

    def update_job(self,jid,state,result=None,error=None,run_id=None):
        with self.transaction() as db:
            db.execute('UPDATE collection_runs SET state=?,result_json=?,error_code=?,updated_at=? WHERE run_id=?',(state,canonical(result) if result else None,error,now(),jid))

    def interrupt_jobs(self):
        with self.transaction() as db:
            db.execute("UPDATE collection_runs SET state='interrupted',updated_at=? WHERE state IN ('running','pending','cancelling')",(now(),))

    def job_action(self,jid,action):
        with self.transaction() as db:
            row=db.execute('SELECT state FROM collection_runs WHERE run_id=?',(jid,)).fetchone()
            if not row: raise IngestionError('job_not_found')
            if action=='resume':
                if row[0] not in {'failed','partial','interrupted','cancelled'}: raise IngestionError('job_state_conflict')
                db.execute("UPDATE collection_runs SET state='pending',cancel_requested=0,error_code=NULL,execution_count=execution_count+1,updated_at=? WHERE run_id=?",(now(),jid))
            elif action=='cancel':
                if row[0] in {'succeeded','failed','cancelled'}: raise IngestionError('job_state_conflict')
                db.execute("UPDATE collection_runs SET state=?,cancel_requested=1,updated_at=? WHERE run_id=?",('cancelling' if row[0]=='running' else 'cancelled',now(),jid))
            else: raise IngestionError('unknown_action')
