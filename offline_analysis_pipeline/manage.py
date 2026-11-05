"""Offline migration utilities; stdlib only, no collection/model calls."""
import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def safe(root,name):
    p=(root/name).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('path outside migration root')
    return p


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['verify','prepare','test-ingestion','check-data'])
    p.add_argument('--workspace',type=Path,default=ROOT/'runtime/workspace')
    a=p.parse_args(); manifest=json.loads((ROOT/'bundle-manifest.json').read_text(encoding='utf-8'))
    if a.command=='verify':
        inventory=json.loads((ROOT/'FILES.sha256.json').read_text(encoding='utf-8'))
        errors=[name for name,h in inventory.items() if not safe(ROOT,name).is_file() or sha(safe(ROOT,name))!=h]
        print(json.dumps({'ok':not errors,'files':len(inventory),'errors':errors},ensure_ascii=False)); sys.exit(bool(errors))
    if a.command=='test-ingestion':
        sys.exit(subprocess.call([sys.executable,'tests/run_suite.py'],cwd=ROOT/'01_ingestion'))
    work=a.workspace.resolve()
    if a.command=='prepare':
        if work.exists(): raise SystemExit('Refuse existing workspace; choose a new --workspace')
        work.mkdir(parents=True)
        for row in manifest['mounts']:
            src=safe(ROOT,row['source']); dest=safe(work,row['target']); dest.parent.mkdir(parents=True,exist_ok=True)
            opener=gzip.open if row['encoding']=='gzip' else open
            with opener(src,'rb') as inp,dest.open('xb') as out: shutil.copyfileobj(inp,out)
            if sha(dest)!=row['sha256']: raise ValueError('materialized file hash mismatch: '+row['target'])
        print(json.dumps({'prepared_files':len(manifest['mounts']),'workspace':str(work),'network_calls':0},ensure_ascii=False))
    if a.command in {'prepare','check-data'}:
        sys.path.insert(0,str(ROOT/'01_ingestion/src'))
        from autoinsight_ingestion.storage import Repository
        result={}
        for label in ['stock','live_test']:
            data=work/'data'/label
            if not (data/'db/ingestion.sqlite3').is_file(): raise SystemExit('Run prepare before check-data')
            with Repository(data) as store: result[label]=store.verify()
        print(json.dumps(result,ensure_ascii=False)); sys.exit(not all(r['ok'] for r in result.values()))


if __name__=='__main__': main()
