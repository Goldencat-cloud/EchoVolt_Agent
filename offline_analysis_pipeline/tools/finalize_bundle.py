"""Freeze manifest after explicit source relocation; never access credentials."""
import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--collaboration',type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'bundle-manifest.json').read_text(encoding='utf-8'))
    def add(src,dest,target):
        dst=root/dest;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        h=hashlib.sha256(dst.read_bytes()).hexdigest()
        manifest['mounts'].append(dict(source=dest,target=target,encoding='identity',sha256=h))
        manifest['provenance'].append(dict(path=dest,source=str(src),source_sha256=h,encoding='identity'))
    if a.source:
        add(a.source/'collaboration/result/auto018-product-entity-normalization/v1/final/mention-mapping.jsonl','05_normalization/helpers/mention-mapping.jsonl','collaboration/result/auto018-product-entity-normalization/v1/final/mention-mapping.jsonl')
    if a.collaboration:
        qc='human-irrelevant-removal-review-20261010-n100-s20261010.json'
        add(a.collaboration/'collaboration/qc/reviews'/qc,'03_media/reference/'+qc,'local-reference/'+qc)
        for change,sub,dest in [('auto-007-irrelevant-context-reanalysis','a007','03_media/reanalysis'),('auto-008-post-integrated-summary','prompts','03_media/integration_prompts'),('auto-008-post-integrated-summary','schema','03_media/integration_schema'),('auto-007-irrelevant-context-reanalysis','prompts','03_media/reanalysis_prompts'),('auto-007-irrelevant-context-reanalysis','schema','03_media/reanalysis_schema')]:
            base=a.collaboration/'collaboration/experiments'/change/sub
            for f in sorted(base.rglob('*')):
                if f.is_file() and '__pycache__' not in f.parts:
                    rel=f.relative_to(base).as_posix();add(f,dest+'/'+rel,'collaboration/experiments/'+change+'/'+sub+'/'+rel)
        for name in ['003_A4_图片下载_图片清单.csv','004_A4_图片策展_主链路终版.csv','002_A3_深度清洗_全量_带噪声标注.csv']:
            add(a.collaboration/'collaboration/data'/name,'03_media/source_metadata/'+name,'data/media_source/'+name)
    # Mount handover code too, so it has a stable, isolated runnable location.
    for stage in ['02_cleaning','03_media']:
        for f in (root/stage/'handover').rglob('*'):
            if f.is_file():
                source=f.relative_to(root).as_posix();target='handover/'+stage+'/'+f.relative_to(root/stage/'handover').as_posix()
                if not any(r['target']==target for r in manifest['mounts']):manifest['mounts'].append(dict(source=source,target=target,encoding='identity',sha256=''))
    for f in (root/'03_media/reference').glob('*'):
        target='local-reference/'+f.name
        if f.is_file() and not any(r['target']==target for r in manifest['mounts']):
            manifest['mounts'].append(dict(source=f.relative_to(root).as_posix(),target=target,encoding='identity',sha256=''))
    for row in manifest['mounts']:
        path=root/row['source']
        if row['encoding']=='identity':row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['relocation_note']='Runtime Python paths relocated to the materialized workspace; provenance retains historical source hashes.'
    (root/'bundle-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    files={}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(x in path.relative_to(root).parts for x in ['runtime','__pycache__','.venv','local-config']):continue
        rel=path.relative_to(root).as_posix()
        if rel=='FILES.sha256.json':continue
        if path.stat().st_size>=100*1024*1024:raise ValueError('GitHub file limit: '+rel)
        files[rel]=hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'FILES.sha256.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(files),'bytes':sum((root/f).stat().st_size for f in files)},ensure_ascii=False))


if __name__=='__main__':main()
