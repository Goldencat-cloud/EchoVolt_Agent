"""AUTO-018 一次性语料整理分析；不修改源数据，不调用模型或网络。

Run: python collaboration/result/auto018-product-entity-normalization/v1/normalize_entities.py
Outputs are reproducible and written to a fresh --output directory only.
"""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata
from functools import lru_cache

# 迁移后本文件位于 05_normalization/helpers/，仓库根的上溯层数随之变为 2。
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'collaboration/result/auto016-modular-post-extraction/single-v23-full-repair1/contract-passed.jsonl'
INPUTS = ROOT / 'collaboration/result/auto016-modular-post-extraction/single-v23-full/inputs'
CATALOG = ROOT / 'data/reference/su7_parameters.csv'
RULE_VERSION = 'product-normalization-1.2'


@lru_cache(maxsize=100000)
def fold(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).casefold()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def eid(kind, values):
    return kind + ':' + digest(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode())[:20]


BRAND_GROUPS = {
    '小米': ['小米', '小米汽车', 'Xiaomi'], '特斯拉': ['特斯拉', 'Tesla'],
    '小鹏': ['小鹏', '小鹏汽车', 'XPENG'], '极氪': ['极氪', 'ZEEKR'],
    '宝马': ['宝马', 'BMW'], '比亚迪': ['比亚迪', 'BYD'],
    '理想': ['理想', '理想汽车'], '零跑': ['零跑', '零跑汽车'],
    '蔚来': ['蔚来', '蔚来汽车'], '极越': ['极越', '极越汽车'],
    '阿维塔': ['阿维塔'], '保时捷': ['保时捷'], '问界': ['问界', 'AITO'],
    '智界': ['智界', 'LUXEED'], '吉利': ['吉利', '吉利汽车'],
}
BRANDS = {fold(a): b for b, aliases in BRAND_GROUPS.items() for a in aliases}
NON_VEHICLE = re.compile(r'手机|平板|手表|耳机|充电宝|洗衣机|空调|冰箱|电视|扫地|电饭|路由器|车衣|贴膜|轮胎|刹车片|手机支架|电动牙刷|净水器|小爱音箱|充电枪|充放电枪|充电机械臂|汽车工厂|有限公司|汽车电池|电池包|电机', re.I)
NON_CAR_BRANDS = {'华为', '苹果', 'Apple', '宁德时代', '小米生态链', 'OPPO', '国家电网', '倍耐力', '米其林', '鸿蒙智行', 'BBA', 'bba', '亿纬锂能'}
GENERIC_SERIES = {'汽车', '轿车', 'suv', '纯电', '电车', '新车', '车型', 'l系列', '未知', '未明确', '无法判断', '轿跑', '新能源', '第二款车', '标准版', '创始版', 'ultra', 'max', 'pro', '新一代', '第一代', '增程'}
NICKNAME = re.compile(r'毛豆|米时捷|苏7|速7|速七|米车', re.I)


def brand(value):
    return BRANDS.get(fold(value), unicodedata.normalize('NFKC', value).strip() if value else None)


def brand_forms(value):
    return [fold(x) for x in BRAND_GROUPS.get(value, [value])]


def series_name(value):
    value = unicodedata.normalize('NFKC', value or '').strip()
    if re.fullmatch(r'su7\s*(?:ultra|max|pro|标准版|创始版)', value, re.I):
        return 'SU7'
    if re.fullmatch(r'(su7|yu7|model\s*[3ysx])', value, re.I):
        return 'Model ' + re.sub(r'^model\s*', '', value, flags=re.I).upper() if value.lower().startswith('model') else value.upper()
    return value.upper() if re.fullmatch(r'[a-z]+\d+[a-z+]*|\d+[a-z]+', value, re.I) else value


@lru_cache(maxsize=4096)
def token_pattern(token):
    t = fold(token)
    suffix = r'(?:(?![a-z0-9+])|(?=20\d{2}(?:年)?款)|(?=(?:ultra(?:prototype)?|max|pro|gt|fr|plaid|performance)(?![a-z])))'
    return re.compile(re.escape(t) + (suffix if t[-1:].isascii() and t[-1:].isalnum() else ''))


@lru_cache(maxsize=100000)
def in_text(token, text):
    t = fold(token)
    if not t:
        return False
    # Avoid SU7 matching SU7L / SU7 Ultra matching SU7 UltraX.
    return token_pattern(token).search(fold(text)) is not None


def make_catalog(rows):
    grouped = collections.defaultdict(list)
    for r in rows:
        grouped[r['specid']].append(r)
    out = []
    for sid, rs in sorted(grouped.items()):
        for field in ['车型名称', '年款', '状态']:
            assert len({r[field] for r in rs}) == 1, (sid, field)
        assert len({(r['配置分组'], r['配置分类'], r['配置项']) for r in rs}) == len(rs)
        full = [r['配置值'] for r in rs if r['配置项'] == '车型名称']
        assert len(full) == 1
        short = rs[0]['车型名称']
        trim = re.sub(r'^\d{4}款\s*', '', short)
        out.append({'specid': sid, 'name': full[0], 'model_year': rs[0]['年款'], 'catalog_trim': trim,
                    'source_status': rs[0]['状态'], 'eligible': '猜想' not in short,
                    'exclusion_reason': 'hypothetical_render' if '猜想' in short else None,
                    'parameter_rows': len(rs), 'source': str(CATALOG), 'source_scope': 'user_supplied_snapshot'})
    return out


def evidence_check(product, original):
    blocks = {b['block_id']: b for b in original['blocks']}
    checked = []
    for ev in product['evidence']:
        block = blocks.get(ev['block_id'])
        if not block:
            checked.append('missing_block')
            continue
        expected = 'text' if block['type'] == 'text' else 'image_summary'
        text = block.get('text', '') if expected == 'text' else block.get('summary', '')
        quote = ev['quote']
        if ev['source_type'] != expected:
            checked.append('source_type_mismatch')
        elif quote in text:
            checked.append('exact')
        elif fold(quote) in fold(text):
            checked.append('format_normalized')
        else:
            # Keep previously accepted punctuation/ellipsis cases in review; never weaken this pass.
            checked.append('needs_review')
    return checked


def trim_value(value):
    v = fold(value)
    parts = []
    for token, label in [('ultra', 'Ultra'), ('max', 'Max'), ('pro', 'Pro'), ('gt', 'GT'), ('fr', 'FR'), ('plaid', 'Plaid'), ('performance', 'Performance')]:
        if re.search(r'(?<![a-z])' + token + r'(?![a-z])', v):
            parts.append(label)
    if '标准' in v:
        parts.append('标准版')
    if '创始' in v:
        parts.append('创始版')
    if 'prototype' in v or '原型' in v:
        parts.append('原型车')
    for qualifier in ['纽北限量版', '限量版', '挖孔版', '纪念版', '赛道版', '改装版']:
        if qualifier in v and not any(qualifier in p for p in parts):
            parts.append(qualifier)
    if len([x for x in parts if x in ['Ultra', 'Max', 'Pro', '标准版']]) > 1:
        return None, True
    if parts:
        return ' '.join(parts), False
    return (unicodedata.normalize('NFKC', value).strip() if value else None), False


def generation(value):
    for text, label in [('新一代', '新一代'), ('第一代', '第一代'), ('初代', '第一代'), ('二代', '第二代'), ('新款', '新款'), ('老款', '老款'), ('旧款', '老款'), ('小米新SU7','原文新SU7'), ('小米新su7','原文新SU7'), ('新小米SU7','原文新SU7')]:
        if text in value:
            return label
    return None


def run(output):
    assert not output.exists(), 'Choose a new --output directory; existing data is not overwritten.'
    source_bytes, catalog_bytes = SOURCE.read_bytes(), CATALOG.read_bytes()
    posts = [json.loads(line) for line in source_bytes.decode('utf-8').splitlines() if line.strip()]
    assert len({p['post_id'] for p in posts}) == len(posts) == 9529
    catalog_rows = list(csv.DictReader(catalog_bytes.decode('utf-8-sig').splitlines()))
    catalog = make_catalog(catalog_rows)
    products = [(p['post_id'], e) for p in posts for e in p['products']]
    assert len({(pid, e['id']) for pid, e in products}) == len(products)
    # Candidate names are learned from explicit branded names and their own quoted evidence.
    anchors = collections.defaultdict(list)
    for pid, e in products:
        b, s = brand(e.get('brand')), series_name(e.get('series'))
        if not b or not s or fold(s) in GENERIC_SERIES or fold(s) in brand_forms(b) or b in NON_CAR_BRANDS or NON_VEHICLE.search(e['name']) or NICKNAME.search(e['name']):
            continue
        if not any(bf in fold(e['name']) for bf in brand_forms(b)) or not in_text(s, e['name']):
            continue
        evs = [v for v in e['evidence'] if any(bf in fold(v['quote']) for bf in brand_forms(b)) and in_text(s, v['quote'])]
        if evs:
            anchors[(b, s)].append({'post_id': pid, 'local_product_id': e['id'], 'evidence': evs[:1]})
    # User reference is an explicit naming source for SU7 even if a corpus anchor were missing.
    anchors[('小米', 'SU7')].append({'source': str(CATALOG), 'specids': [c['specid'] for c in catalog if c['eligible']]})
    lookup = collections.defaultdict(set)
    for b, s in anchors:
        lookup[fold(s)].add((b, s))
    mappings, entities = [], {}
    post_map = {p['post_id']: p for p in posts}
    for pid in post_map:
        original = json.loads((INPUTS / (pid + '.json')).read_text(encoding='utf-8'))
        for e in post_map[pid]['products']:
            m = {'rule_version': RULE_VERSION, 'post_id': pid, 'local_product_id': e['id'], 'raw_name': e['name'],
                 'original': e, 'status': 'unresolved', 'canonical_id': None, 'brand_id': None, 'series_id': None,
                 'normalized': None, 'catalog_specid': None, 'catalog_candidates': [], 'catalog_status': 'not_applicable',
                 'method': None, 'review_reasons': [], 'evidence_check': evidence_check(e, original)}
            reasons = m['review_reasons']
            evtexts = [v['quote'] for v in e['evidence']]
            ev = ' '.join(evtexts)
            name = e['name']
            b, s = brand(e.get('brand')), series_name(e.get('series'))
            if NON_VEHICLE.search(name) or (b in NON_CAR_BRANDS and not s):
                m['status'] = 'excluded'
                reasons.append('non_vehicle_or_group_organization')
            elif not evtexts or any(c not in ('exact', 'format_normalized') for c in m['evidence_check']):
                reasons.append('evidence_block_check_needs_review')
            elif NICKNAME.search(name):
                reasons.append('nickname_needs_explicit_coreference_review')
            else:
                if b and fold(s) in brand_forms(b):
                    s = None
                if fold(s) in GENERIC_SERIES:
                    reasons.append('generic_series_not_vehicle_model')
                    s = None
                pair = None
                if s and b and (b, s) in anchors and in_text(s, name) and any(in_text(s, q) for q in evtexts):
                    if any(any(bf in fold(q) for bf in brand_forms(b)) for q in evtexts):
                        pair = (b, s)
                        m['method'] = 'explicit_brand_series'
                    elif len(lookup[fold(s)]) == 1 and not re.fullmatch(r'\d+', s):
                        pair = (b, s)
                        m['method'] = 'unique_corpus_series_alias'
                if not pair:
                    matches = []
                    for token, pairs in lookup.items():
                        for cb, cs in pairs:
                            if not in_text(cs, name) or not any(in_text(cs, q) for q in evtexts):
                                continue
                            explicit = any(bf in fold(name) for bf in brand_forms(cb)) and any(any(bf in fold(q) for bf in brand_forms(cb)) for q in evtexts)
                            # Bare numeric names, nicknames and short ambiguous model codes require explicit brand.
                            unique_alias = len(pairs) == 1 and not re.fullmatch(r'\d+', cs) and len(token) >= 3
                            if explicit or unique_alias:
                                matches.append((cb, cs))
                    if matches:
                        longest = max(len(fold(cs)) for cb, cs in matches)
                        matches = sorted(set((cb, cs) for cb, cs in matches if len(fold(cs)) == longest))
                        if b:
                            preferred = [p for p in matches if p[0] == b]
                            if preferred:
                                matches = preferred
                        if len(matches) == 1:
                            pair = matches[0]
                            m['method'] = 'unique_corpus_name_alias'
                        else:
                            m['status'] = 'ambiguous'
                            reasons.append('multiple_series_candidates')
                is_brand_only = (not s and e.get('version') is None and
                                 any(fold(name) == bf for bf in brand_forms(b)) if b else False)
                if not pair and is_brand_only and any(any(bf in fold(q) for bf in brand_forms(b)) for q in evtexts):
                    m['method'] = 'brand_name_only'
                elif not pair:
                    reasons.append('no_unique_supported_series')
                if pair or m['method'] == 'brand_name_only':
                    nb, ns = pair if pair else (b, None)
                    if b and nb != b:
                        reasons.append('brand_field_conflict')
                    if re.search(r'su7', fold(name)) and re.search(r'model[3ysx]|极氪\d', fold(name)):
                        reasons.append('composite_vehicle_name')
                    if s and pair and fold(s) != fold(ns):
                        reasons.append('series_field_conflict')
                    year = e.get('model_year')
                    if year and not any(re.search(re.escape(str(year)) + r'(年)?款', fold(q)) for q in evtexts):
                        reasons.append('model_year_not_supported_by_own_evidence')
                    version, conflict = trim_value(e.get('version'))
                    # Recover only explicit discriminators in the extracted name, never infer a trim from price/range.
                    lexical_version, lexical_conflict = trim_value(name)
                    if lexical_version == name:
                        lexical_version = None
                    if lexical_version and any(t in lexical_version for t in ['Ultra', 'Max', 'Pro', 'GT', 'FR', 'Plaid', 'Performance', '标准版', '创始版', '原型车', '限量版', '挖孔版']):
                        if version and version != lexical_version:
                            vf, nf = set(version.split()), set(lexical_version.split())
                            if vf <= nf or any(in_text(t, version) for t in ['Max', 'Pro', 'Ultra']):
                                version = lexical_version
                            elif not (nb == '小米' and ns == 'SU7'):
                                reasons.append('trim_field_conflict')
                        elif not version:
                            version = lexical_version
                    if conflict or lexical_conflict:
                        reasons.append('multiple_trim_markers')
                    if version:
                        for marker in ['Ultra', 'Max', 'Pro', 'GT', 'FR', 'Plaid', 'Performance', '标准版', '创始版', '原型车', '限量版', '挖孔版']:
                            if marker in version:
                                variants = {'标准版': ['标准'], '创始版': ['创始'], '原型车': ['prototype', '原型']}.get(marker, [marker])
                                if not any(any(in_text(v, q) for q in evtexts) for v in variants):
                                    reasons.append('trim_marker_not_supported:' + marker)
                        if not any(t in version for t in ['Ultra', 'Max', 'Pro', 'GT', 'FR', 'Plaid', 'Performance', '标准版', '创始版', '原型车']) and not any(fold(version) in fold(q) for q in evtexts):
                            reasons.append('trim_not_supported_by_own_evidence')
                    gen = generation(name + ' ' + (e.get('version') or ''))
                    if gen and not any(generation(q) == gen for q in evtexts):
                        reasons.append('generation_not_supported_by_own_evidence')
                    # Generation descriptors belong to generation, not trim.
                    if version and fold(version) in {'新一代', '第一代', '初代', '新款', '老款', '旧款'}:
                        version = None
                    normalized = {'brand': nb, 'series': ns, 'model_year': year, 'version': version, 'generation': gen}
                    m['normalized'] = normalized
                    m['brand_id'] = eid('brand', [nb])
                    m['series_id'] = eid('series', [nb, ns]) if ns else None
                    if not reasons:
                        m['status'] = 'resolved'
                        key = [nb, ns, year, version, gen]
                        m['canonical_id'] = eid('entity', key)
                        if m['canonical_id'] not in entities:
                            display = ' '.join(str(t) for t in [nb, ns, (str(year) + '款') if year else None, version, gen] if t)
                            entities[m['canonical_id']] = {'canonical_id': m['canonical_id'], 'display_name': display, **normalized,
                                                          'brand_id': m['brand_id'], 'series_id': m['series_id'],
                                                          'entity_level': '品牌' if not ns else '具体配置' if year or version or gen else '车系',
                                                          'reference_status': 'corpus_mentioned_not_officially_verified',
                                                          'mention_count': 0, 'post_ids': set(), 'raw_names': set(), 'catalog_specids': set()}
                        ent = entities[m['canonical_id']]
                        ent['mention_count'] += 1
                        ent['post_ids'].add(pid)
                        ent['raw_names'].add(name)
                    if nb == '小米' and ns == 'SU7':
                        eligible = [c for c in catalog if c['eligible']]
                        specific = []
                        if year:
                            for c in eligible:
                                if c['model_year'] != str(year):
                                    continue
                                # Full named configuration required. Range prefixes may be omitted, but no numeric-only lookup.
                                desc = c['catalog_trim']
                                if fold(desc) in fold(name) and any(fold(desc) in fold(q) for q in evtexts):
                                    specific.append(c)
                        if len(specific) == 1 and m['status'] == 'resolved':
                            m['catalog_specid'] = specific[0]['specid']
                            m['catalog_status'] = 'exact_year_and_descriptor'
                            entities[m['canonical_id']]['catalog_specids'].add(m['catalog_specid'])
                        else:
                            candidates = [c for c in eligible if not year or c['model_year'] == str(year)]
                            if version:
                                if 'Ultra' in version or '原型车' in version:
                                    candidates = []
                                elif 'Max' in version:
                                    candidates = [c for c in candidates if 'max' in fold(c['catalog_trim'])]
                                elif 'Pro' in version:
                                    candidates = [c for c in candidates if 'pro' in fold(c['catalog_trim'])]
                                elif '标准' in version:
                                    candidates = [c for c in candidates if not re.search('max|pro', fold(c['catalog_trim']))]
                                if '创始版' in version:
                                    candidates = [c for c in candidates if '创始' in c['catalog_trim']]
                            m['catalog_candidates'] = [c['specid'] for c in candidates]
                            m['catalog_status'] = 'insufficient_identification' if candidates else 'not_covered_by_snapshot'
            mappings.append(m)

    # Exact reference products share specid identity; partial mentions keep their own null-bearing tuple.
    catalog_lookup = {c['specid']: c for c in catalog}
    entities = {}
    for m in mappings:
        if m['status'] != 'resolved':
            continue
        m['identity_basis'] = 'catalog_specid' if m['catalog_specid'] else 'corpus_partial_tuple'
        if m['catalog_specid']:
            ref = catalog_lookup[m['catalog_specid']]
            m['canonical_id'] = 'autohome:spec:' + ref['specid']
            m['mention_generation'] = m['normalized']['generation']
            m['normalized'] = {**m['normalized'], 'version': ref['catalog_trim'], 'generation': None}
        n, cid = m['normalized'], m['canonical_id']
        if cid not in entities:
            display = catalog_lookup[m['catalog_specid']]['name'] if m['catalog_specid'] else ' '.join(str(t) for t in [n['brand'], n['series'], (str(n['model_year']) + '款') if n['model_year'] else None, n['version'], n['generation']] if t)
            entities[cid] = {'canonical_id': cid, 'display_name': display, **n, 'brand_id': m['brand_id'], 'series_id': m['series_id'],
                             'entity_level': '品牌' if not n['series'] else '具体配置' if n['model_year'] or n['version'] or n['generation'] else '车系',
                             'identity_basis': m['identity_basis'], 'reference_status': 'user_catalog_snapshot' if m['catalog_specid'] else 'corpus_mentioned_not_officially_verified',
                             'mention_count': 0, 'post_ids': set(), 'raw_names': set(), 'catalog_specids': set()}
        ent = entities[cid]
        ent['mention_count'] += 1
        ent['post_ids'].add(m['post_id'])
        ent['raw_names'].add(m['raw_name'])
        if m['catalog_specid']:
            ent['catalog_specids'].add(m['catalog_specid'])

    # Relational view preserves original claim direction and local IDs; unresolved targets remain visible.
    mapping_lookup = {(m['post_id'], m['local_product_id']): m for m in mappings}
    claim_links = []
    for post in posts:
        for c in post['claims']:
            for target in c['target_products']:
                m = mapping_lookup[(post['post_id'], target['product_id'])]
                claim_links.append({'post_id': post['post_id'], 'claim_id': c['id'], 'local_product_id': target['product_id'],
                                    'role': target['role'], 'canonical_id': m['canonical_id'], 'status': m['status'],
                                    'series_id': m['series_id'] if m['status'] == 'resolved' else None,
                                    'catalog_specid': m['catalog_specid']})
    for ent in entities.values():
        ent['post_count'] = len(ent.pop('post_ids'))
        ent['raw_names'] = sorted(ent['raw_names'])
        ent['catalog_specids'] = sorted(ent['catalog_specids'])
    # An exact canonical tuple must never identify two catalog specs; avoid propagating such collisions.
    catalog_conflicts = {cid for cid, e in entities.items() if len(e['catalog_specids']) > 1}
    for m in mappings:
        if m['canonical_id'] in catalog_conflicts:
            # Parent entity is still useful; exact catalog link lives on each mention only.
            m['review_reasons'].append('canonical_tuple_has_multiple_catalog_specs')
    aliases = collections.defaultdict(lambda: {'count': 0, 'posts': set()})
    for m in mappings:
        key = (m['raw_name'], m['status'], m['canonical_id'], m['catalog_specid'], '|'.join(m['review_reasons']))
        aliases[key]['count'] += 1
        aliases[key]['posts'].add(m['post_id'])
    alias_rows = [{'raw_name': k[0], 'status': k[1], 'canonical_id': k[2], 'catalog_specid': k[3], 'review_reasons': k[4],
                   'mention_count': v['count'], 'post_count': len(v['posts']), 'example_post_id': min(v['posts'])}
                  for k, v in aliases.items()]
    alias_rows.sort(key=lambda x: (-x['mention_count'], x['raw_name']))
    stats = {'posts': len(posts), 'product_mentions': len(products), 'unique_raw_names': len({e['name'] for _, e in products}),
             'canonical_entities': len(entities), 'status_counts': dict(collections.Counter(m['status'] for m in mappings)),
             'catalog_rows': len(catalog_rows), 'catalog_specs': len(catalog), 'catalog_eligible_specs': sum(c['eligible'] for c in catalog),
             'catalog_linked_mentions': sum(m['catalog_specid'] is not None for m in mappings),
             'catalog_linked_specs': sorted({m['catalog_specid'] for m in mappings if m['catalog_specid']}),
             'catalog_conflicting_canonical_tuples': len(catalog_conflicts),
             'claim_product_links': len(claim_links),
             'review_reasons': dict(collections.Counter(r for m in mappings for r in m['review_reasons'])),
             'evidence_checks': dict(collections.Counter(c for m in mappings for c in m['evidence_check']))}
    checks = {'source_hash_unchanged': digest(SOURCE.read_bytes()) == digest(source_bytes),
              'catalog_hash_unchanged': digest(CATALOG.read_bytes()) == digest(catalog_bytes),
              'all_mentions_covered_once': len(mappings) == len(products) == len(mapping_lookup),
              'canonical_fk_integrity': all(m['canonical_id'] in entities if m['status'] == 'resolved' else m['canonical_id'] is None for m in mappings),
              'brand_and_series_parents_consistent': all(m['brand_id'] == entities[m['canonical_id']]['brand_id'] and m['series_id'] == entities[m['canonical_id']]['series_id'] for m in mappings if m['status'] == 'resolved'),
              'no_hypothetical_spec_links': all(m['catalog_specid'] != '74430' for m in mappings),
              'exact_spec_link_has_year': all(m['normalized']['model_year'] is not None for m in mappings if m['catalog_specid']),
              'no_unresolved_spec_links': all(m['status'] == 'resolved' for m in mappings if m['catalog_specid']),
              'one_catalog_spec_one_entity': all(len({m['canonical_id'] for m in mappings if m['catalog_specid'] == sid}) == 1 for sid in {m['catalog_specid'] for m in mappings if m['catalog_specid']}),
              'canonical_tuple_consistency': all(all(m['normalized'][k] == entities[m['canonical_id']][k] for k in ['brand','series','model_year','version','generation']) for m in mappings if m['status'] == 'resolved'),
              'no_nickname_auto_resolution': all(m['status'] != 'resolved' for m in mappings if NICKNAME.search(m['raw_name'])),
              'no_generic_series_entities': all(fold(e['series']) not in GENERIC_SERIES and fold(e['series']) not in brand_forms(e['brand']) for e in entities.values() if e['series']),
              'trim_and_year_are_separate': eid('entity', ['小米','SU7',None,'Max',None]) != eid('entity', ['小米','SU7','2024','Max',None]),
              'prototype_not_same_as_production': trim_value('Ultra Prototype')[0] != trim_value('Ultra')[0],
              'human_semantic_acceptance': 'not_measured'}
    assert all(v is True for k, v in checks.items() if k != 'human_semantic_acceptance'), checks
    output.mkdir(parents=True)
    def write_json(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def write_jsonl(name, rows):
        (output / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    def write_csv(name, rows):
        if not rows:
            return
        with (output / name).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    entity_rows = sorted(entities.values(), key=lambda e: (-e['mention_count'], e['display_name']))
    write_json('summary.json', stats)
    write_json('checks.json', checks)
    write_json('catalog.json', catalog)
    write_json('normalization-rules.json', {'version': RULE_VERSION, 'brand_alias_groups': BRAND_GROUPS,
                                          'generic_series': sorted(GENERIC_SERIES), 'non_car_brands_or_groups': sorted(NON_CAR_BRANDS),
                                          'entity_identity_fields': ['brand','series','model_year','version','generation'],
                                          'specid_link_rule': 'explicit year and full catalog descriptor in name and own evidence; unique eligible record',
                                          'incomplete_catalog_not_negative_evidence': True})
    write_jsonl('mention-mapping.jsonl', mappings)
    write_jsonl('canonical-entities.jsonl', entity_rows)
    write_jsonl('claim-product-links.jsonl', claim_links)
    write_json('corpus-name-anchors.json', [{'brand': b, 'series': s, 'support_count': len(v), 'examples': v[:3]} for (b, s), v in sorted(anchors.items())])
    write_csv('canonical-entities.csv', entity_rows)
    write_csv('alias-mapping.csv', alias_rows)
    write_csv('review-queue.csv', [r for r in alias_rows if r['status'] != 'resolved' or r['review_reasons']])
    write_csv('catalog.csv', catalog)
    write_csv('mention-mapping.csv', [{k: m[k] for k in ['post_id','local_product_id','raw_name','status','canonical_id','brand_id','series_id','normalized','catalog_specid','catalog_status','catalog_candidates','method','review_reasons']} for m in mappings])
    # Keep the supplied snapshot exactly, including hypothetical items and unavailable '-' values.
    (output / 'source-su7-config.csv').write_bytes(catalog_bytes)
    review_data = []
    for m in mappings:
        review_data.append({**{k: m[k] for k in ['post_id','local_product_id','raw_name','status','normalized','catalog_specid','catalog_status','catalog_candidates','review_reasons','method']},
                            'evidence': m['original']['evidence'], 'source_type_note': 'image_summary 为已有模型图片说明，不等于独立图像核验'})
    data = json.dumps(review_data, ensure_ascii=False).replace('<', '\\u003c')
    template = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SU7 产品实体归一复核</title>
<style>body{font:15px system-ui,"Microsoft YaHei";max-width:1250px;margin:24px auto;background:#f5f7fa;color:#173339}header{position:sticky;top:0;background:#f5f7fa;padding:12px 0}input,select,button{font:inherit;padding:8px;margin:4px}article{background:white;margin:14px 0;padding:18px;border:1px solid #dce3e5;border-radius:9px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#647577}.row{display:grid;grid-template-columns:1fr 1fr;gap:20px}blockquote{border-left:3px solid #1e777c;margin:12px 0;padding:8px}</style>
<header><h1>产品实体归一 · 第一轮</h1><p>语料映射，不代表官方车型库或人工语义验收。specid 仅按用户配置表快照关联；缺失信息保持未知。</p>
<input id="q" placeholder="搜索名称、版本、年款、post_id" size="45"><select id="status"><option value="">全部状态</option><option>resolved</option><option>ambiguous</option><option>unresolved</option><option>excluded</option></select><button id="prev">上一页</button><button id="next">下一页</button><button id="export">导出人工标注</button><div id="count"></div></header><main id="list"></main>
<script>const data=__DATA__;let page=0,view=[];const $=x=>document.getElementById(x),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=r=>'auto018-v1-'+r.post_id+'-'+r.local_product_id;function draw(){view=data.filter(r=>(!$('status').value||r.status===$('status').value)&&JSON.stringify(r).toLowerCase().includes($('q').value.toLowerCase()));page=Math.min(page,Math.max(0,Math.ceil(view.length/40)-1));$('count').textContent=`${view.length} 个提及 · 第 ${page+1} 页 / ${Math.max(1,Math.ceil(view.length/40))} 页`;$('list').innerHTML=view.slice(page*40,page*40+40).map((r,i)=>{let saved;try{saved=JSON.parse(localStorage.getItem(key(r))||'{}')}catch(e){saved={}}return `<article><h3>${esc(r.raw_name)} <small>${esc(r.status)}</small></h3><small>${esc(r.post_id)} / ${esc(r.local_product_id)}</small><div class="row"><pre>${esc(JSON.stringify({normalized:r.normalized,method:r.method,specid:r.catalog_specid,catalog_status:r.catalog_status,candidates:r.catalog_candidates,reasons:r.review_reasons},null,2))}</pre><div>${r.evidence.map(e=>`<blockquote><small>${esc(e.block_id)} · ${esc(e.source_type)}</small><p>${esc(e.quote)}</p></blockquote>`).join('')}</div></div><small>${esc(r.source_type_note)}</small><p>人工复核 <select data-i="${i}" class="mark">${['未复核','通过','存疑','错误'].map(m=>`<option ${saved.mark===m?'selected':''}>${m}</option>`).join('')}</select><input class="note" data-i="${i}" value="${esc(saved.note||'')}" placeholder="备注、建议标准名" size="65"></p></article>`}).join('');document.querySelectorAll('.mark,.note').forEach(el=>el.onchange=()=>{let i=Number(el.dataset.i),r=view[page*40+i],mark=document.querySelector(`.mark[data-i="${i}"]`).value,note=document.querySelector(`.note[data-i="${i}"]`).value;localStorage.setItem(key(r),JSON.stringify({post_id:r.post_id,local_product_id:r.local_product_id,mark,note}));});}
$('q').oninput=$('status').onchange=()=>{page=0;draw()};$('prev').onclick=()=>{page=Math.max(0,page-1);draw()};$('next').onclick=()=>{page++;draw()};$('export').onclick=()=>{const a=document.createElement('a'),rows=data.flatMap(r=>{try{let v=JSON.parse(localStorage.getItem(key(r))||'null');return v?[v]:[]}catch(e){return []}});a.href=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));a.download='auto018-human-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};draw();</script></html>'''
    (output / 'review.html').write_text(template.replace('__DATA__', data), encoding='utf-8')
    write_json('manifest.json', {'rule_version': RULE_VERSION, 'source': str(SOURCE), 'source_sha256': digest(source_bytes),
                                 'catalog_source': str(CATALOG), 'catalog_sha256': digest(catalog_bytes),
                                 'original_inputs': str(INPUTS), 'scope': 'offline_data_preparation',
                                 'ai_generated_rules_need_human_review': True, 'human_acceptance': 'pending',
                                 'no_network_or_model_calls': True, 'stats': stats,
                                 'files': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())} for p in sorted(output.iterdir()) if p.is_file()]})
    print(json.dumps({'output': str(output), 'stats': stats, 'checks': checks}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'final')
    run(parser.parse_args().output)
