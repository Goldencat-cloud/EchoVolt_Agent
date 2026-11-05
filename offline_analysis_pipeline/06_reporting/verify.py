"""Bounded report checks and same-source Markdown companion."""
import csv
import hashlib
import json
import re
from pathlib import Path
from analyze import HERE, ROOT, SOURCE, MAPPING, INPUTS, norm


def main():
    a=HERE/'analysis'
    read=lambda name:json.loads((a/name).read_text(encoding='utf-8'))
    snapshot=json.loads((HERE/'app/src/data.json').read_text(encoding='utf-8'))
    p=read('profiles.json'); s=read('summary.json'); cases=read('reviewed-cases.json')
    checks={}
    checks['original_file_hashes_unchanged']=all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in read('input-manifest.json')['files'].items())
    checks['frozen_post_hashes_unchanged']=all(hashlib.sha256((INPUTS/(k+'.json')).read_bytes()).hexdigest()==v for k,v in read('input-manifest.json')['frozen_posts'].items())
    checks['aspect_claims_reconcile']=sum(r['claims'] for r in p['产品体验或风险'])==3356
    checks['sentiments_reconcile']=all(r['claims']==r['positive']+r['negative']+r['neutral']+r['other'] for group in p.values() for r in group)
    checks['comfort_percentage']=round(131/302*100,1)==43.4
    checks['source_counts']=sum(len(json.loads(line)['claims']) for line in SOURCE.open(encoding='utf-8') if line.strip())==26936
    checks['selected_case_coverage']=len(cases)==11 and len({c['key'].split(':')[0] for c in cases})==10
    checks['case_urls_safe']=all(c['url'].startswith('https://club.autohome.com.cn/') and '?' not in c['url'] and '#' not in c['url'] for c in cases)
    checks['snapshot_bindings']=snapshot['queries']['aspects']['rows']==p['产品体验或风险'] and snapshot['queries']['evidence']['rows']==cases
    checks['core_unique']=len({r['key'] for r in read('core-claims.json')})==297
    # Independent membership and denominator reconstruction from original Claims + mapping.
    mp={(r['post_id'],r['local_product_id']):r for r in map(json.loads,MAPPING.open(encoding='utf-8'))}
    eligible=[]
    for line in SOURCE.open(encoding='utf-8'):
        post=json.loads(line); pid=post['post_id']
        blocks={b['block_id']:b for b in json.loads((INPUTS/(pid+'.json')).read_text(encoding='utf-8'))['blocks']}
        for c in post['claims']:
            if c['comparison'] or c['claim_type'] not in ['产品体验与评价','故障与风险']:
                continue
            main=[mp[(pid,t['product_id'])] for t in c['target_products'] if t['role']=='主要讨论对象']
            if not main or not all(t['brand']=='小米' and t['series']=='SU7' and t['status']=='mapped' for t in main):
                continue
            valid=bool(c['evidence'])
            for e in c['evidence']:
                b=blocks.get(e['block_id'],{}); image=e['source_type']=='image_summary'
                valid=valid and b.get('type')==('image' if image else 'text') and bool(e['quote']) and norm(e['quote']) in norm(b.get('summary' if image else 'text',''))
            if valid: eligible.append((pid,c))
    checks['independent_eligible_counts']=len(eligible)==3356 and len({pid for pid,c in eligible})==1810
    checks['independent_comfort_counts']=sum(c['aspect']=='空间与舒适性' and c['sentiment']=='负面' for pid,c in eligible)==131
    assert all(checks.values()), checks
    writeup=(HERE/'app/src/content/report/SU7Report.jsx').read_text(encoding='utf-8')
    blocks=dict(re.findall(r'^(\w+):`(.*?)`[,\n]',writeup,re.M|re.S))
    text=['# '+snapshot['title'],'\n小米 SU7 · 汽车之家 · 离线需求分析初版\n']
    for name in ['summary','volume','polarity','pre']:
        text.append(blocks[name])
    text.append('## 属性与情感精确计数\n\n|方面|帖数|表达|正面|负面|负面占比|\n|---|---:|---:|---:|---:|---:|')
    for r in p['产品体验或风险']:
        text.append(f"|{r['aspect']}|{r['posts']}|{r['claims']}|{r['positive']}|{r['negative']}|{r['negativeShare']:.1%}|")
    text.append(blocks['cases'])
    for c in cases:
        text.extend(['### '+c['case'],c['observation'],'改进假设：'+c['need'],'表达性质：'+c['source_status'],
                     '> '+c['quote'].replace('\n','\n> '),'证据边界：'+c['boundary'],f"[原帖：{c['title']}]({c['url']}) · {c['date']} · {c['blocks']}"])
    for name in ['actions','cohort','scope','methods']: text.append(blocks[name])
    (HERE/'SU7需求分析报告.md').write_text('\n\n'.join(text),encoding='utf-8')
    with (a/'aspect-sentiment.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(p['产品体验或风险'][0])); writer.writeheader(); writer.writerows(p['产品体验或风险'])
    (a/'verification.json').write_text(json.dumps({'checks':checks,'topic_model_run':False,'human_semantic_acceptance':'not_measured'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2)); print('Report Markdown exported from authored report prose and identical rows/cases.')


if __name__=='__main__':main()
