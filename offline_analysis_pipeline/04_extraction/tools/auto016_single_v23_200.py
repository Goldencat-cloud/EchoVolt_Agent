"""Authorized full-V2.3 single-call new-200 experiment; no implicit retries."""
import argparse
import concurrent.futures as cf
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import random
import shutil
import time

from tools import auto016_run_v23 as shared

ROOT, CHANGE = shared.ROOT, shared.CHANGE
OUT = shared.BASE / 'single-v23-200'
PACKETS = CHANGE / 'delegations/single-v23-200'
SEED = 2026101603


def packet(row):
    return {'task_id': 'a016-single-' + row['post_id'], 'change_id': CHANGE.name,
            'task_refs': ['5.2'], 'prompt_file': shared.rel(OUT / 'full-v2.3.md'),
            'context_files': [row['input_path']], 'schema_file': shared.rel(OUT / 'output.wire.schema.json'),
            'response_type': 'json', **shared.PARAMS}


def prepare():
    if OUT.exists():
        raise ValueError('refuse overwrite existing experiment')
    original_prompt = shared.PROMPTS / 'full-v2.3.md'
    previous = shared.BASE / 'v23-run2/manifest.json'
    source_hashes = {str(p): shared.hash_file(p) for p in (shared.SOURCE, shared.META, previous, original_prompt)}
    excluded = {r['post_id'] for r in shared.read(previous)['rows']}
    sources = {}
    with shared.SOURCE.open(encoding='utf-8-sig') as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                if record['post_id'] in sources:
                    raise ValueError('duplicate source post ID')
                sources[record['post_id']] = record
    ids = random.Random(SEED).sample(sorted(set(sources) - excluded), 200)
    with shared.META.open(encoding='utf-8-sig', newline='') as f:
        metadata = {}
        for r in csv.DictReader(f):
            if r['post_id'] in ids:
                if r['post_id'] in metadata:
                    raise ValueError('duplicate metadata ID')
                metadata[r['post_id']] = r
    if set(metadata) != set(ids):
        raise ValueError('metadata join incomplete')
    OUT.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(original_prompt, OUT / 'full-v2.3.md')
    shutil.copyfile(shared.SCHEMAS / 'post-output-v2.3.json', OUT / 'output.schema.json')
    shared.save(OUT / 'output.wire.schema.json', shared.wire_schema(shared.read(OUT / 'output.schema.json')), exclusive=True)
    rows = []
    for pid in ids:
        source = sources[pid]['post_input']
        if source['title'] != metadata[pid]['title']:
            raise ValueError('title mismatch')
        blocks = [{'block_id': 'T0', 'type': 'text', 'text': source['title']}]
        mapping = [{'block_id': 'T0', 'source_index': -1, 'original_id': 'title',
                    'content_sha256': shared.digest(source['title'])}]
        counts = {'text': 1, 'image': 0}
        for index, b in enumerate(source['sequence']):
            kind = b['type']
            if kind not in counts:
                raise ValueError('unexpected block type')
            key = 'text' if kind == 'text' else 'summary'
            if not isinstance(b[key], str) or not b[key].strip():
                raise ValueError('empty integrated block')
            block = {'block_id': ('T' if kind == 'text' else 'I') + str(counts[kind]), 'type': kind, key: b[key]}
            counts[kind] += 1
            blocks.append(block)
            mapping.append({'block_id': block['block_id'], 'source_index': index, 'content_sha256': shared.digest(b[key])})
        path = OUT / 'inputs' / (pid + '.json')
        shared.save(path, {'post_id': pid, 'title': source['title'], 'created_at': metadata[pid]['created_at'] or None, 'blocks': blocks}, exclusive=True)
        row = {'post_id': pid, 'input_path': shared.rel(path), 'input_sha256': shared.hash_file(path),
               'images': counts['image'], 'mapping': mapping, 'source_record_sha256': shared.digest(sources[pid])}
        rows.append(row)
        shared.save(PACKETS / (pid + '.json'), packet(row), exclusive=True)
    assets = [OUT / 'full-v2.3.md', OUT / 'output.schema.json', OUT / 'output.wire.schema.json',
              Path(__file__), ROOT / 'tools/qwen_delegate.py', ROOT / 'tools/post_contract_v23.py',
              ROOT / 'tools/auto016_run_v23.py', shared.SCHEMAS / 'post-output-v2.3.json']
    for path in PACKETS.glob('*.json'):
        assets.append(path)
    manifest = {'experiment': 'single-v23-200', 'seed': SEED, 'sample_size': 200, 'source_posts': len(sources),
                'excluded_posts': sorted(excluded), 'rows': rows, 'source_hashes': source_hashes,
                'assets': {shared.rel(p): shared.hash_file(p) for p in assets},
                'image_posts': sum(r['images'] > 0 for r in rows), 'model': shared.MODEL,
                'parameters': shared.PARAMS, 'prompt_unmodified': True, 'no_retries': True,
                'sampling': 'simple random 200 without replacement, excluding preceding 100',
                'input_policy': 'complete integrated sequence; title copied as first text block T0; existing image summaries',
                'wire_policy': 'uniqueItems removed only from decoding schema; canonical local validator retained'}
    if any(shared.hash_file(Path(p)) != h for p, h in source_hashes.items()):
        raise ValueError('source changed while freezing')
    shared.save(OUT / 'manifest.json', manifest, exclusive=True)
    print('PREPARED', len(rows), 'image_posts', manifest['image_posts'], flush=True)


def audit():
    shared.OUT = OUT
    return shared.audit()


def execute(row, endpoint):
    task = packet(row)
    if shared.read(PACKETS / (row['post_id'] + '.json')) != task:
        raise ValueError('packet mismatch')
    prepared = shared.delegate.prepare_task(ROOT, task)
    fingerprint = shared.digest({'task': task, 'inputs': prepared['inputs'], 'parameters': prepared['parameters'],
                                 'model': shared.MODEL, 'endpoint': endpoint, 'messages': prepared['messages']})
    dest = OUT / 'calls' / row['post_id']
    if dest.exists():
        review_file = dest / 'local-review.json'
        if not review_file.exists():
            raise ValueError('uncertain interrupted request; no retry')
        r = shared.read(review_file)
        if r['cache_key'] != fingerprint:
            raise ValueError('cached request changed')
        if r.get('payload') is not None and shared.read(dest / 'response.json') != r['payload']:
            raise ValueError('cached raw output changed')
        return r
    model, base, _ = shared.delegate.load_connection(shared.SETTINGS, shared.ENV)
    if model != shared.MODEL or hashlib.sha256(base.encode()).hexdigest() != endpoint:
        raise ValueError('connection changed')
    record = shared.delegate.dispatch(ROOT, task, shared.rel(dest), shared.SETTINGS, shared.ENV)
    payload = shared.read(dest / 'response.json') if record['state'] == 'REVIEW_REQUIRED' else None
    if payload is not None:
        payload = shared.normalise_for_contract(payload)
    errors = shared.validate_v23(shared.read(ROOT / row['input_path']), payload) if payload is not None else [record.get('error', 'api_failed')]
    if record.get('inputs_changed_after_request'):
        errors.append('inputs_changed_after_request')
    review = {'post_id': row['post_id'], 'state': 'CONTRACT_PASS' if not errors else 'FAILED',
              'cache_key': fingerprint, 'schema_parsed': payload is not None, 'payload': payload,
              'errors': errors, 'usage': record.get('usage'), 'elapsed_s': record.get('elapsed_s'),
              'http_status': record.get('http_status'), 'semantic_acceptance': 'NOT_MEASURED'}
    shared.save(dest / 'local-review.json', review, exclusive=True)
    print(row['post_id'], review['state'], errors[:2], flush=True)
    return review


def report():
    m = shared.read(OUT / 'manifest.json')
    rows = [shared.read(p) for p in (OUT / 'calls').glob('*/local-review.json')]
    lookup = {r['post_id']: r for r in rows}
    # Re-run the current local contract against saved payloads. Historical
    # local-review.json files may have been produced under an older schema.
    input_paths = {row['post_id']: ROOT / row['input_path'] for row in m['rows']}
    for review in rows:
        payload = review.get('payload')
        if payload is None or review['post_id'] not in input_paths:
            continue
        payload = shared.normalise_for_contract(payload)
        review['payload'] = payload
        current_errors = shared.validate_v23(shared.read(input_paths[review['post_id']]), payload)
        review['errors'] = current_errors
        review['state'] = 'CONTRACT_PASS' if not current_errors else 'FAILED'
    ordered = [lookup[r['post_id']] for r in m['rows'] if r['post_id'] in lookup]
    records = [shared.read(p) for p in (OUT / 'calls').glob('*/result.json')]
    summary = {'planned_posts': 200, 'closed_posts': len(rows), 'actual_requests': sum(r.get('api_calls', 1) for r in records),
               'schema_parsed': sum(r['schema_parsed'] for r in rows),
               'contract_pass': sum(r['state'] == 'CONTRACT_PASS' for r in rows),
               'failures': sum(r['state'] != 'CONTRACT_PASS' for r in rows), 'pending': 200-len(rows),
               'tokens': {k: sum((r.get('usage') or {}).get(k, 0) for r in rows) for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']},
               'cached_tokens': sum((r.get('usage') or {}).get('prompt_tokens_details', {}).get('cached_tokens', 0) for r in rows),
               'usage_unknown': sum(r.get('usage') is None for r in rows), 'semantic_accuracy': None,
               'updated_at': datetime.now(timezone.utc).isoformat()}
    shared.save(OUT / 'progress.json', summary)
    for name, selected in [('model-outputs.jsonl', [r for r in ordered if r['schema_parsed']]),
                           ('contract-passed.jsonl', [r for r in ordered if r['state'] == 'CONTRACT_PASS'])]:
        (OUT / name).write_text(''.join(json.dumps(r['payload'], ensure_ascii=False)+'\n' for r in selected), encoding='utf-8')
    shared.save(OUT / 'failures.json', [{k: r[k] for k in ['post_id', 'errors', 'schema_parsed']} for r in ordered if r['state'] != 'CONTRACT_PASS'])
    review_rows = []
    for row in m['rows']:
        post = shared.read(ROOT / row['input_path'])
        review_rows.append({'post_id': row['post_id'], 'input': post, 'result': lookup.get(row['post_id'])})
    data = json.dumps(review_rows, ensure_ascii=False).replace('<', '\\u003c')
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AUTO016 · 200条质量复核</title>
<style>
:root{--bg:#0b1220;--panel:#121d30;--panel2:#17263d;--line:#2a3c59;--text:#e7eef8;--muted:#94a8c3;--blue:#63a4ff;--green:#36d399;--red:#ff6b81;--amber:#f6c453}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,"Microsoft YaHei",sans-serif}header{position:sticky;top:0;z-index:5;background:rgba(11,18,32,.97);border-bottom:1px solid var(--line);padding:18px 24px;backdrop-filter:blur(8px)}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 10px}.sub{color:var(--muted);margin-bottom:14px}.metrics{display:flex;gap:10px;flex-wrap:wrap}.metric{min-width:112px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 12px}.metric b{display:block;font-size:20px}.metric small{color:var(--muted)}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.toolbar input,.toolbar select,.toolbar button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px 10px}.toolbar input{min-width:250px;flex:1}.toolbar button{cursor:pointer}.toolbar button:hover{border-color:var(--blue)}main{display:grid;grid-template-columns:270px minmax(360px,1fr) minmax(400px,1.15fr);gap:12px;max-width:1800px;margin:0 auto;padding:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;min-width:0}.panel-head{padding:12px 14px;border-bottom:1px solid var(--line);color:var(--muted)}#list{max-height:calc(100vh - 210px);overflow:auto}.item{padding:10px 12px;border-bottom:1px solid rgba(42,60,89,.65);cursor:pointer}.item:hover,.item.active{background:var(--panel2)}.item .id{color:var(--blue);font-weight:600}.item .title{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge{display:inline-block;border-radius:999px;padding:2px 7px;font-size:12px;margin-top:4px}.pass{background:rgba(54,211,153,.14);color:var(--green)}.fail{background:rgba(255,107,129,.14);color:var(--red)}.muted{color:var(--muted)}.content{padding:14px}.block{border:1px solid var(--line);border-radius:8px;margin:0 0 9px;background:#0f1a2b}.block-head{padding:6px 9px;color:var(--muted);font-size:12px;border-bottom:1px solid var(--line)}.block-body{padding:9px;white-space:pre-wrap;overflow-wrap:anywhere}.block.image{border-left:3px solid #a78bfa}.block.text{border-left:3px solid var(--blue)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1423;border:1px solid var(--line);border-radius:8px;padding:12px;max-height:70vh;overflow:auto;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.issues{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.issue{border:1px solid rgba(255,107,129,.5);color:#ffb1bd;background:rgba(255,107,129,.1);border-radius:6px;padding:4px 7px;font-size:12px}.empty{padding:28px;color:var(--muted);text-align:center}@media(max-width:1100px){main{grid-template-columns:230px 1fr}.right{grid-column:1/-1}}@media(max-width:720px){header{padding:14px}main{display:block;padding:10px}.panel{margin-bottom:10px}#list{max-height:260px}.toolbar input{min-width:0;width:100%}}
</style><header><h1>AUTO016 · V2.3 · 200条质量复核</h1><div class="sub">当前规则重评估：程序契约用于发现结构和证据回挂问题，不等于语义准确率；原始模型输出只读展示。</div><div class="metrics"><div class="metric"><b id="mTotal">0</b><small>总条数</small></div><div class="metric"><b id="mPass">0</b><small>契约通过</small></div><div class="metric"><b id="mFail">0</b><small>存在问题</small></div><div class="metric"><b id="mParsed">0</b><small>已解析</small></div><div class="metric"><b id="mTokens">-</b><small>总 Token</small></div></div><div class="toolbar"><input id="search" placeholder="搜索 post_id、标题、正文或问题…"><select id="filter"><option value="all">全部</option><option value="pass">契约通过</option><option value="fail">存在问题</option><option value="unparsed">未解析</option></select><button id="prev">上一条</button><button id="next">下一条</button><span id="counter" class="muted"></span></div></header><main><section class="panel"><div class="panel-head">帖子列表 · <span id="listCount"></span></div><div id="list"></div></section><section class="panel"><div class="panel-head">输入内容 · 标题已作为 T0 普通文本块</div><div class="content" id="input"></div></section><section class="panel right"><div class="panel-head" id="resultHead">模型输出与质量门</div><div class="content"><div id="issues" class="issues"></div><details open><summary>解析结果 JSON</summary><pre id="output"></pre></details><details><summary>运行元数据</summary><pre id="meta"></pre></details></div></section></main><script id="data" type="application/json">'''+data+'''</script><script>
const rows=JSON.parse(document.getElementById('data').textContent),summary='''+summary_json+''';let visible=[],pos=0;const $=id=>document.getElementById(id),j=x=>JSON.stringify(x,null,2);function result(r){return r.result||{state:'PENDING',errors:['pending'],schema_parsed:false}}function match(r,q){const x=result(r);return !q||j(r.input).toLowerCase().includes(q)||j(x).toLowerCase().includes(q)}function refresh(){const q=$('search').value.trim().toLowerCase(),f=$('filter').value;visible=rows.filter(r=>{const x=result(r),ok=f==='all'||(f==='pass'&&x.state==='CONTRACT_PASS')||(f==='fail'&&x.state==='FAILED')||(f==='unparsed'&&!x.schema_parsed);return ok&&match(r,q)});pos=Math.min(pos,Math.max(0,visible.length-1));renderList();show()}function renderList(){$('listCount').textContent=visible.length+' 条';$('list').innerHTML=visible.map((r,i)=>{const x=result(r),ok=x.state==='CONTRACT_PASS';return '<div class="item '+(i===pos?'active':'')+'" data-i="'+i+'"><div class="id">'+r.post_id+'</div><div class="title">'+esc(r.input.title||'无标题')+'</div><span class="badge '+(ok?'pass':'fail')+'">'+(ok?'通过':'问题 '+(x.errors||[]).length)+'</span></div>'}).join('')||'<div class="empty">没有匹配记录</div>';document.querySelectorAll('.item').forEach(e=>e.onclick=()=>{pos=Number(e.dataset.i);renderList();show()})}function show(){const r=visible[pos];if(!r){$('input').innerHTML='<div class="empty">请选择记录</div>';$('output').textContent='';$('meta').textContent='';$('issues').innerHTML='';$('counter').textContent='0 / 0';return}const x=result(r);$('counter').textContent=(pos+1)+' / '+visible.length+' · '+r.post_id;$('resultHead').textContent=r.post_id+' · '+(x.state==='CONTRACT_PASS'?'契约通过':'需检查');$('input').innerHTML=(r.input.blocks||[]).map(b=>{const isTitle=b.type==='text'&&b.text===r.input.title;return '<div class="block '+b.type+'"><div class="block-head">'+esc(b.block_id)+' · '+esc(b.type)+(isTitle?' · 标题':'')+'</div><div class="block-body">'+esc(b.text||b.summary||'')+'</div></div>'}).join('');$('output').textContent=j(x.payload||null);$('meta').textContent=j({state:x.state,schema_parsed:x.schema_parsed,errors:x.errors||[],elapsed_s:x.elapsed_s,http_status:x.http_status,usage:x.usage,semantic_acceptance:x.semantic_acceptance});$('issues').innerHTML=(x.errors||[]).map(e=>'<span class="issue">'+esc(e)+'</span>').join('')||'<span class="badge pass">无程序质量门问题</span>'}function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function move(d){if(!visible.length)return;pos=Math.max(0,Math.min(visible.length-1,pos+d));renderList();show()}$('search').oninput=()=>{pos=0;refresh()};$('filter').onchange=()=>{pos=0;refresh()};$('prev').onclick=()=>move(-1);$('next').onclick=()=>move(1);const parsed=rows.filter(r=>result(r).schema_parsed).length,passed=rows.filter(r=>result(r).state==='CONTRACT_PASS').length;$('mTotal').textContent=rows.length;$('mParsed').textContent=parsed;$('mPass').textContent=passed;$('mFail').textContent=rows.length-passed;$('mTokens').textContent=(summary.tokens?.total_tokens||0).toLocaleString();refresh();</script></html>'''
    (OUT / 'review.html').write_text(page, encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'dry-run', 'probe', 'run', 'report'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
        return
    manifest = audit()
    if args.command == 'report':
        print(report())
        return
    for row in manifest['rows']:
        shared.delegate.prepare_task(ROOT, packet(row))
    if args.command == 'dry-run':
        print('200 packets valid; zero API calls')
        return
    model, base, _ = shared.delegate.load_connection(shared.SETTINGS, shared.ENV)
    if model != shared.MODEL:
        raise ValueError('model mismatch')
    endpoint = hashlib.sha256(base.encode()).hexdigest()
    probe = min(manifest['rows'], key=lambda r: (ROOT / r['input_path']).stat().st_size)
    if args.command == 'probe':
        result = execute(probe, endpoint)
        shared.save(OUT / 'probe.json', {'post_id': probe['post_id'], 'schema_parsed': result['schema_parsed'], 'state': result['state']})
        print(report())
        return
    if not shared.read(OUT / 'probe.json')['schema_parsed']:
        raise ValueError('probe transport/schema failed; no batch')
    start = time.time()
    queue = iter(manifest['rows'])
    pending = {}
    stopped, streak = False, 0
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        def fill():
            while not stopped and len(pending) < 3:
                try:
                    row = next(queue)
                except StopIteration:
                    return
                pending[pool.submit(execute, row, endpoint)] = row
        fill()
        while pending:
            done, _ = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
            for future in done:
                row = pending.pop(future)
                try:
                    r = future.result()
                    streak = streak + 1 if not r['schema_parsed'] else 0
                    if r.get('http_status') in {400, 401, 403, 429} or streak >= 3:
                        stopped = True
                except Exception as exc:
                    stopped = True
                    shared.save(OUT / ('controller-error-'+row['post_id']+'.json'), {'type': type(exc).__name__, 'no_retry': True})
            report()
            fill()
    audit()
    shared.save(OUT / 'timing.json', {'elapsed_s': time.time()-start, 'circuit_stopped': stopped,
                                    'finished_at': datetime.now(timezone.utc).isoformat()})
    print('STOPPED' if stopped else 'CLOSED', json.dumps(report(), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
