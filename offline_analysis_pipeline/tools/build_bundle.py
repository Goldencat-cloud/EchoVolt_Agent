"""Maintainer-only snapshot builder. Inputs explicit; never modifies source trees."""
import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    for name in ['source','ingestion','collaboration','handover','stock','live']:
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--reference-dir',required=True,type=Path)
    a=p.parse_args(); root=Path(__file__).resolve().parents[1]
    if (root/'bundle-manifest.json').exists(): raise SystemExit('refuse rebuild existing bundle')
    mounts=[]; provenance=[]

    def add(src,dest,workspace=None,compress=False):
        src=Path(src); dest=root/dest
        if not src.is_file(): raise FileNotFoundError(src)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists(): raise FileExistsError(dest)
        if compress:
            with src.open('rb') as inp,dest.open('wb') as raw:
                with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as out: shutil.copyfileobj(inp,out)
        else: shutil.copyfile(src,dest)
        sha=hashlib.sha256(src.read_bytes()).hexdigest()
        provenance.append({'path':dest.relative_to(root).as_posix(),'source':str(src),'source_sha256':sha,'encoding':'gzip' if compress else 'identity'})
        if workspace: mounts.append({'source':dest.relative_to(root).as_posix(),'target':workspace,'encoding':'gzip' if compress else 'identity','sha256':sha})

    def tree(src,dest,workspace=None,compress_data=False):
        for f in sorted(Path(src).rglob('*')):
            if not f.is_file() or any(x in f.parts for x in ['.venv','__pycache__','node_modules','.git','.openai','.data-app-offline']): continue
            if f.name in {'.env','writer.lock'} or f.suffix in {'.pyc','.log'}: continue
            if Path(src)==a.ingestion and 'evidence' in f.relative_to(src).parts: continue
            rel=f.relative_to(src).as_posix(); gz=compress_data and f.suffix in {'.jsonl','.csv','.js','.json'} and f.stat().st_size>1024*1024
            add(f,dest+'/'+rel+('.gz' if gz else ''),(workspace+'/'+rel) if workspace else None,gz)

    tree(a.ingestion,'01_ingestion')
    # Runtime evidence/data are deliberately not copied by the source-tree scan.

    with zipfile.ZipFile(a.handover) as z:
        for entry in z.infolist():
            parts=entry.filename.split('/')
            if len(parts)<4 or not parts[1].startswith(('02_','03_')) or not entry.filename.endswith(('.py','.md')): continue
            stage='02_cleaning' if parts[1].startswith('02_') else '03_media'
            rel='/'.join(parts[2:]); dest=root/stage/'handover'/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(entry) as inp,dest.open('xb') as out: shutil.copyfileobj(inp,out)
            provenance.append({'path':dest.relative_to(root).as_posix(),'source':str(a.handover)+'!'+entry.filename,'source_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'encoding':'identity'})

    for name in ['auto016_run_v23.py','auto016_single_v23_200.py','auto016_full_v23.py','auto016_repair_v23.py','post_contract_v23.py','modular_post_extraction.py','qwen_delegate.py']:
        add(a.source/'tools'/name,'04_extraction/tools/'+name,'tools/'+name)
    ch='openspec/changes/auto-016-modular-post-extraction'
    for sub in ['prompts','schemas']:
        tree(a.source/ch/sub,'04_extraction/'+sub,ch+'/'+sub)
    for name in ['manifest.json']:
        add(a.source/'collaboration/result/auto016-modular-post-extraction'/name,'04_extraction/reference/'+name,'collaboration/result/auto016-modular-post-extraction/'+name)
    base='collaboration/result/auto016-modular-post-extraction/'
    tree(a.source/base/'single-v23-full-repair1','04_extraction/results',base+'single-v23-full-repair1',True)
    tree(a.source/base/'single-v23-full/inputs','04_extraction/frozen_inputs',base+'single-v23-full/inputs',True)
    for name in ['manifest.json','failures.json','all-results.jsonl','final-report.json','full-v2.3.md','output.schema.json','output.wire.schema.json']:
        src=a.source/base/'single-v23-full'/name; gz=src.stat().st_size>1024*1024
        add(src,'04_extraction/upstream/'+name+('.gz' if gz else ''),base+'single-v23-full/'+name,gz)
    norm='collaboration/result/auto018-product-entity-normalization'
    for name in ['normalize_taxonomy.py','test_taxonomy.py','aliases.json','README.md','verification.json','next-analysis-research.md']:
        add(a.source/norm/'v2'/name,'05_normalization/'+name,norm+'/v2/'+name)
    add(a.source/norm/'v1/normalize_entities.py','05_normalization/helpers/normalize_entities.py',norm+'/v1/normalize_entities.py')
    for name in ['catalog.json','corpus-name-anchors.json']:
        add(a.source/norm/'v1/final'/name,'05_normalization/helpers/'+name,norm+'/v1/final/'+name)
    tree(a.source/norm/'v2/delivery-r3','05_normalization/results',norm+'/v2/delivery-r3',True)
    tree(a.source/norm/'report-v1','06_reporting',norm+'/report-v1',True)
    tree(a.source/'collaboration/data','data/legacy_metadata','collaboration/data',True)
    add(a.reference_dir/'su7_配置明细_长表.csv','data/reference/su7_parameters.csv','data/reference/su7_parameters.csv')
    add(a.reference_dir/'user_profiles.csv','data/reference/user_profiles.csv','data/reference/user_profiles.csv')
    for stage in ['auto006','auto007','auto008']:
        src=a.collaboration/'collaboration/result'/stage
        if stage=='auto006':
            tree(src/'source/tools','03_media/auto006/tools','tools',False)
            tree(src/'source/openspec/changes/auto-006-qwen-full-image-extraction/prompts','03_media/auto006/prompts','openspec/changes/auto-006-qwen-full-image-extraction/prompts')
            tree(src/'source/openspec/changes/auto-006-qwen-full-image-extraction/schema','03_media/auto006/schema','openspec/changes/auto-006-qwen-full-image-extraction/schema')
            add(src/'results/results_final.jsonl','03_media/auto006/results_final.jsonl.gz','collaboration/result/auto006/results/results_final.jsonl',True)
        elif stage=='auto007': tree(src/'outputs','03_media/auto007','collaboration/result/auto007/outputs',True)
        else: tree(src,'03_media/auto008','collaboration/result/auto008',True)
    tree(a.collaboration/'collaboration/experiments/auto-008-post-integrated-summary/a008','03_media/integration','collaboration/experiments/auto-008-post-integrated-summary/a008')
    # Consistent SQLite backups; no old redundant backup copies or WAL files.
    for label,src in [('stock',a.stock),('live_test',a.live)]:
        dest=root/'data'/label; (dest/'db').mkdir(parents=True,exist_ok=True)
        with sqlite3.connect((src/'db/ingestion.sqlite3').as_uri()+'?mode=ro',uri=True) as inp:
            with sqlite3.connect(dest/'db/ingestion.sqlite3') as out:
                inp.backup(out); out.execute('VACUUM')
        db=dest/'db/ingestion.sqlite3'
        mounts.append({'source':db.relative_to(root).as_posix(),'target':'data/'+label+'/db/ingestion.sqlite3','encoding':'identity','sha256':hashlib.sha256(db.read_bytes()).hexdigest()})
        for f in sorted((src/'raw').rglob('*')):
            if f.is_file():
                rel=f.relative_to(src).as_posix()
                add(f,'data/'+label+'/'+rel+'.gz','data/'+label+'/'+rel,True)
    for name in ['live-integration-20261021.md','unit-tests-author-fields.json','exclusion-127-20261021.json']:
        add(a.ingestion/'evidence'/name,'docs/evidence/'+name)
    for change in ['auto-016-modular-post-extraction','auto-018-product-entity-normalization','auto-019-offline-analysis-operators','auto-020-forum-evidence-model']:
        for name in ['proposal.md','design.md','tasks.md']:
            src=a.source/'openspec/changes'/change/name
            if src.is_file(): add(src,'docs/reference/'+change+'/'+name)
    (root/'bundle-manifest.json').write_text(json.dumps({'version':1,'mounts':mounts,'provenance':provenance,'privacy':'private repository only; forum and user snapshots included'},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': main()
