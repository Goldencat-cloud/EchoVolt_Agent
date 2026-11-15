"""Offline report preparation. No new extraction, labels or model calls."""
import collections
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent
EXTRACTION = PIPELINE / '04_extraction'
NORMALIZATION = PIPELINE / '05_normalization'
SOURCE = EXTRACTION / 'results' / 'contract-passed.jsonl.gz'
INPUTS = EXTRACTION / 'frozen_inputs'
MAPPING = NORMALIZATION / 'helpers' / 'mention-mapping.jsonl'
META = PIPELINE / '03_media' / 'source_metadata' / '004_A4_图片策展_主链路终版.csv'
OUT = HERE / 'analysis'


def load_jsonl(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def norm(text):
    return re.sub(r'\s+', '', str(text or '')).casefold()


def clean_url(url):
    p = urlsplit(url or '')
    return urlunsplit((p.scheme, p.netloc, p.path, '', '')) if p.scheme == 'https' else ''


def count(rows):
    return {'claims': len(rows), 'posts': len({r['post_id'] for r in rows})}


def aspect_rows(rows):
    result = []
    for aspect in sorted({r['aspect'] for r in rows}):
        group = [r for r in rows if r['aspect'] == aspect]
        c = collections.Counter(r['sentiment'] for r in group)
        result.append({'aspect': aspect, **count(group), 'positive': c['正面'],
                       'negative': c['负面'], 'neutral': c['中性'],
                       'other': len(group)-c['正面']-c['负面']-c['中性'],
                       'negative_posts': len({r['post_id'] for r in group if r['sentiment'] == '负面'}),
                       'negativeShare': c['负面']/len(group) if group else None})
    return sorted(result, key=lambda r: (-r['posts'], r['aspect']))


def main():
    OUT.mkdir(exist_ok=False)
    posts = load_jsonl(SOURCE)
    mappings = load_jsonl(MAPPING)
    lookup = {(r['post_id'], r['local_product_id']): r for r in mappings}
    with META.open(encoding='utf-8-sig', newline='') as f:
        metadata = {r['post_id']: r for r in csv.DictReader(f)}
    all_rows, raw_inputs, evidence_counts = [], {}, collections.Counter()
    comparison_pairs = collections.defaultdict(set)
    attr_keys = collections.Counter()
    for post in posts:
        pid = post['post_id']
        raw = json.loads((INPUTS / (pid+'.json')).read_text(encoding='utf-8-sig'))
        raw_inputs[pid] = raw
        blocks = {b['block_id']: b for b in raw['blocks']}
        for c in post['claims']:
            attr_keys.update(c.keys())
            targets = [lookup[(pid, t['product_id'])] | {'role': t['role']} for t in c['target_products']]
            su7 = [t for t in targets if t['brand'] == '小米' and t['series'] == 'SU7' and t['status'] == 'mapped']
            main_targets = [t for t in targets if t['role'] == '主要讨论对象']
            su7_main = any(t['brand'] == '小米' and t['series'] == 'SU7' and t['status'] == 'mapped' for t in main_targets)
            competing_main = any(not (t['brand'] == '小米' and t['series'] == 'SU7') for t in main_targets)
            checks = []
            for e in c['evidence']:
                block = blocks.get(e['block_id'], {})
                expected_type = 'text' if e['source_type'] == 'text' else 'image'
                text = block.get('text', '') if expected_type == 'text' else block.get('summary', '')
                checks.append(bool(e['quote']) and block.get('type') == expected_type and norm(e['quote']) in norm(text))
            evidence_ok = bool(checks) and all(checks)
            evidence_counts['passed' if evidence_ok else 'needs_review'] += 1
            row = {'key': pid+':'+c['id'], 'post_id': pid, 'claim_id': c['id'],
                   'aspect': c['aspect'], 'sentiment': c['sentiment'], 'content': c['content'],
                   'claim_type': c['claim_type'], 'ownership': post['user_context']['ownership_status'],
                   'experience': c['experience_basis'], 'journey': c['journey_stage'],
                   'statement': c['statement_type'], 'usage_context': c.get('usage_context'),
                   'comparison': c.get('comparison'), 'evidence': c['evidence'],
                   'evidence_ok': evidence_ok, 'su7_linked': bool(su7),
                   'su7_primary': su7_main and not competing_main,
                   'review_product': any(t['review_required'] for t in su7),
                   'targets': [{'brand': t['brand'], 'series': t['series'], 'role': t['role'], 'raw_name': t['raw_name']} for t in targets],
                   'date': metadata[pid]['created_at'], 'title': raw['title'],
                   'url': clean_url(metadata[pid]['source_url'])}
            all_rows.append(row)
            if su7 and c.get('comparison'):
                for t in targets:
                    if t['status'] == 'mapped' and t['brand'] and t['series'] and t['brand'] != '小米':
                        comparison_pairs[(t['brand'], t['series'])].add(pid)
    linked = [r for r in all_rows if r['su7_linked']]
    primary = [r for r in linked if r['su7_primary'] and not r['comparison'] and r['evidence_ok']]
    experiences = [r for r in primary if r['claim_type'] in ['产品体验与评价', '故障与风险']]
    firsthand = [r for r in experiences if r['experience'] == '明确亲历']
    core = [r for r in firsthand if r['ownership'] == '当前拥有' and r['journey'] in ['拥有与日常使用', '维修与售后', '交付与上手']]
    potential = [r for r in primary if r['ownership'] == '明确未拥有' and r['journey'] == '购车前' and r['claim_type'] in ['购车与交易决策', '产品体验与评价', '故障与风险']]
    ordered = [r for r in primary if r['ownership'] == '已订未提']
    competitors = [{'brand': b, 'series': s, 'posts': len(v)} for (b, s), v in comparison_pairs.items()]
    competitors.sort(key=lambda r: (-r['posts'], r['brand'], r['series']))
    # This is an analytical shortlist, not a declaration of market competitors.
    whitelist = [('小米', 'SU7')] + [(r['brand'], r['series']) for r in competitors[:8] if r['posts'] >= 10]
    brands = {b for b, s in whitelist}
    scope_counts = collections.Counter()
    scoped = []
    for m in mappings:
        if m['status'] != 'mapped':
            state, level = m['status'], None
        elif (m['brand'], m['series']) in whitelist:
            state, level = 'in_scope', 'series'
        elif m['brand'] in brands:
            # Do not roll a known out-of-scope model into a brand analysis.
            state, level = ('out_of_scope', None) if m['series'] else ('in_scope', 'brand')
        else:
            state, level = 'out_of_scope', None
        scope_counts[state] += 1
        scoped.append({'post_id': m['post_id'], 'local_product_id': m['local_product_id'],
                       'raw_name': m['raw_name'], 'scope_status': state, 'scope_level': level,
                       'analysis_brand': m['brand'] if state == 'in_scope' else None,
                       'analysis_series': m['series'] if state == 'in_scope' and level == 'series' else None,
                       'source_node_id': m['node_id'], 'original_mapping_unchanged': True})
    write('scope.json', {'rule': 'SU7 + top 8 explicitly compared non-Xiaomi series by unique posts, minimum 10 posts; brands only as ancestors or genuinely brand-only mentions',
                         'whitelist': whitelist, 'counts': dict(scope_counts), 'candidates': competitors})
    with (OUT/'scoped-mentions.jsonl').open('w', encoding='utf-8') as f:
        for row in scoped:
            f.write(json.dumps(row, ensure_ascii=False)+'\n')
    cohorts = {'全部关联SU7': linked, 'SU7主对象且引文通过（无比较）': primary,
               '产品体验或风险': experiences, '明确亲历体验或风险': firsthand,
               '当前拥有且亲历使用': core, '明确未拥有的购车前表达': potential,
               '已订未提表达': ordered}
    profiles = {k: aspect_rows(v) for k, v in cohorts.items()}
    write('profiles.json', profiles)
    write('core-claims.json', core)
    write('potential-claims.json', potential)
    compare = [r for r in linked if r['comparison'] and r['evidence_ok']]
    write('comparison-claims.json', compare)
    owner_groups = []
    for ownership in sorted({p['user_context']['ownership_status'] for p in posts}):
        owner_groups.append({'ownership': ownership, 'posts': sum(p['user_context']['ownership_status'] == ownership for p in posts)})
    summaries = {'source_posts': len(posts), 'source_claims': len(all_rows), 'source_mentions': len(mappings),
                 'cohorts': {k: count(v) for k, v in cohorts.items()}, 'evidence_checks': dict(evidence_counts),
                 'claim_fields': dict(attr_keys), 'core_sentiments': dict(collections.Counter(r['sentiment'] for r in core)),
                 'core_usage_context': sum(bool(r['usage_context']) for r in core),
                 'core_product_review': sum(r['review_product'] for r in core),
                 'date_min': min(r['date'] for r in all_rows), 'date_max': max(r['date'] for r in all_rows),
                 'ownership': owner_groups, 'topic_model_run': False, 'model_api_calls': 0,
                 'attributes': 'actual source has aspect/content/sentiment; no separate normalized attribute field',
                 'identity_limit': 'ownership is model-labeled post-level status; neither real identity nor ownership of SU7 independently verified'}
    write('summary.json', summaries)
    # Deterministic evidence pack: all negative core rows, grouped by aspect.
    pack = []
    for a in profiles['当前拥有且亲历使用']:
        group = [r for r in core if r['aspect'] == a['aspect']]
        picked, seen = [], set()
        for sentiment, limit in [('负面', 10), ('正面', 2), ('中性', 1)]:
            candidates = sorted((r for r in group if r['sentiment'] == sentiment), key=lambda r: (r['review_product'], -len(r['content']), r['key']))
            n = 0
            for r in candidates:
                if r['post_id'] not in seen:
                    picked.append(r); seen.add(r['post_id']); n += 1
                    if n == limit:
                        break
        pack.append({'aspect': a['aspect'], 'counts': a, 'examples': picked})
    write('evidence-pack.json', pack)
    with (OUT/'evidence-reading.txt').open('w', encoding='utf-8') as f:
        for group in pack:
            f.write('\n## '+group['aspect']+' '+json.dumps(group['counts'], ensure_ascii=False)+'\n')
            for r in group['examples']:
                f.write(json.dumps({k:r[k] for k in ['key','sentiment','content','usage_context','evidence','title','review_product']},ensure_ascii=False)+'\n')
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [SOURCE, MAPPING, META, Path(__file__)]}
    # Frozen inputs are themselves hashed as a sorted manifest, not just counted.
    raw_hashes = {pid: hashlib.sha256((INPUTS/(pid+'.json')).read_bytes()).hexdigest() for pid in sorted(raw_inputs)}
    write('input-manifest.json', {'files': hashes, 'frozen_posts': raw_hashes})
    assert len({r['key'] for r in all_rows}) == len(all_rows)
    assert sum(evidence_counts.values()) == len(all_rows)
    assert all(r['su7_primary'] and r['evidence_ok'] and not r['comparison'] for r in core)
    write('checks.json', {'unique_claim_keys': True, 'source_mentions_covered': len(scoped) == len(mappings),
                          'core_evidence_gate': True, 'no_comparison_sentiment_misattribution': True,
                          'semantic_accuracy_measured': False, 'models_run': False})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print('COMPETITORS', json.dumps(competitors[:12], ensure_ascii=False))
    print('CORE', json.dumps(profiles['当前拥有且亲历使用'], ensure_ascii=False))


if __name__ == '__main__':
    main()
