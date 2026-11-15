"""AUTO-018 V2 offline taxonomy analysis. Only writes into a new output directory."""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from functools import lru_cache

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent
HELPERS = HERE / 'helpers'
spec = importlib.util.spec_from_file_location('auto018_helpers', HELPERS / 'normalize_entities.py')
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
fold, eid = old.fold, old.eid
RULES = json.loads((HERE / 'aliases.json').read_text(encoding='utf-8'))
SOURCE = old.SOURCE
CATALOG = old.CATALOG
POST_METADATA = PIPELINE / '03_media/source_metadata/004_A4_图片策展_主链路终版.csv'
VERSION = 'taxonomy-2.0'


def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_series(value, brand=None):
    s = old.series_name(value)
    if brand:
        for prefix in [brand]+old.BRAND_GROUPS.get(brand,[]):
            if fold(s).startswith(fold(prefix)) and len(fold(s))>len(fold(prefix)):
                s=re.sub('^'+re.escape(prefix)+r'\s*','',s,flags=re.I)
                break
    if brand=='小米':
        if fold(s) in {fold(a) for a in RULES['series_aliases'][0]['aliases']}:
            return 'SU7'
        if re.fullmatch(r'(?:新|全新|第?[一二三]代)?su7(?:ultra|max|pro|标准版|创始版)?',fold(s)):
            return 'SU7'
        if re.fullmatch(r'\d{1,2}(?:\s*(?:pro|max|ultra))*|v8s|su|增程suv|增程车',fold(s)):
            return ''
    if brand=='特斯拉':
        for canonical,forms in {'Model 3':['3','MODEL三','焕新3','m3'], 'Model Y':['Y','焕新Y'], 'Model S':['S'], 'Model X':['X']}.items():
            if fold(s) in {fold(x) for x in forms}:
                return canonical
    if fold(s).startswith('su7') and fold(s) not in {'su7l', 'su7l猜想图'}:
        return 'SU7'
    if re.search('[A-Za-z]', s) and re.search('[\u4e00-\u9fff]', s):
        s = re.sub(r'[a-zA-Z]+', lambda m: m[0].upper(), s)
    return s


@lru_cache(maxsize=4096)
def alias_pattern(alias):
    token=fold(alias)
    if not token:
        return re.compile(r'(?!)')
    if token[-1].isascii() and token[-1].isalnum():
        end = r'(?=$|[^a-z0-9]|(?:ultra|max|pro|gt|fr|plaid|turbo|performance|prototype)(?![a-z])|20\d{2}(?:年)?款)'
    else:
        end = ''
    return re.compile(re.escape(token)+end)


@lru_cache(maxsize=200000)
def match(alias, text):
    return alias_pattern(alias).search(fold(text)) is not None


class Resolver:
    def __init__(self, anchors, catalog):
        self.catalog = catalog
        self.pairs = set()
        for a in anchors:
            b=old.brand(a['brand'])
            s=clean_series(a['series'],b)
            if s and fold(s) not in old.GENERIC_SERIES and fold(s) not in old.brand_forms(b) and not old.NICKNAME.search(s) and b not in old.NON_CAR_BRANDS:
                self.pairs.add((b, s))
        self.pairs |= {('小米','SU7'), ('小米','YU7')}
        self.pairs |= {(r['brand'], r['series']) for r in RULES['series_aliases']}
        self.brands = {b for b, s in self.pairs} | set(old.BRAND_GROUPS)
        self.forms = {b: list(dict.fromkeys([b] + old.BRAND_GROUPS.get(b, []))) for b in self.brands}
        self.names = collections.defaultdict(set)
        for b, s in self.pairs:
            self.names[fold(s)].add((b, s))

    @lru_cache(maxsize=40000)
    def brand_hits(self, text):
        hits = [(b, f) for b, forms in self.forms.items() for f in forms if match(f, text)]
        # 吉利银河 should not be simultaneously counted as generic 吉利 when the longer brand is explicit.
        return {b for b, f in hits if not any(fold(f) != fold(g) and fold(f) in fold(g) for cb, g in hits)}

    @lru_cache(maxsize=40000)
    def explicit_pairs(self, text):
        result = set()
        for b, s in self.pairs:
            if match(s, text) and any(match(f, text) for f in self.forms[b]):
                result.add((b, s))
        return {p for p in result if not any(p[0] == q[0] and fold(p[1]) != fold(q[1]) and fold(p[1]) in fold(q[1]) for q in result)}

    def own_candidates(self, text):
        explicit = self.explicit_pairs(text)
        if explicit:
            return explicit, 'own_explicit_name'
        for a in RULES['series_aliases']:
            if any(match(x, text) for x in a['aliases']):
                return {(a['brand'], a['series'])}, 'forum_alias' if a['requires_forum_for_bare'] else 'colloquial_alias'
        matches = {next(iter(ps)) for token, ps in self.names.items() if len(ps) == 1 and not token.isdigit() and len(token) >= 3 and match(token, text)}
        return matches, 'corpus_model_alias'

    def resolve(self, pid, e, original, previous=None):
        name = e['name']
        quotes = [x['quote'] for x in e['evidence']]
        own = ' '.join(quotes)
        title = original.get('title', '')
        post_text = '\n'.join(b.get('text', '') for b in original['blocks'] if b['type'] == 'text')
        checks = old.evidence_check(e, original)
        reasons = []
        if any(c not in {'exact','format_normalized'} for c in checks):
            reasons.append('原产品引文定位需复核')
        result = {'post_id': pid, 'local_product_id': e['id'], 'raw_name': name, 'rule_version': VERSION,
                  'node_id': None, 'node_path': [], 'ancestor_ids': [], 'resolution_level': 'unresolved',
                  'brand': None, 'series': None, 'specid': None, 'attributes': {'model_year':None,'version':None,'generation':None},
                  'attribute_evidence': {}, 'status': 'unresolved', 'method': None, 'resolution_basis': [],
                  'review_reasons': reasons, 'review_required':True, 'evidence_check': checks, 'original': e,
                  'forum_context': RULES['forum_context'], 'catalog_candidates': [], 'catalog_status':'not_applicable'}
        # Product-related components remain separately recorded, without becoming whole vehicles.
        phone_name=(re.fullmatch(r'(?:小米|xiaomi)\s*\d{1,2}(?:\s*(?:pro|max|ultra))*',name,re.I)
                    or re.match(r'^(?:红米|redmi)(?:\s*note)?\s*\d|^(?:苹果)?(?:iphone|ipad)',name,re.I))
        if old.NON_VEHICLE.search(name) or phone_name or (e.get('brand') in old.NON_CAR_BRANDS and not e.get('series')):
            result.update(status='excluded', method='non_vehicle_or_group')
            reasons.append('非整车对象或组织集合')
            return result
        b, s, method = None, None, None
        own_brands = self.brand_hits(own)
        name_brands = self.brand_hits(name)
        pairs, pm = self.own_candidates(own)
        name_pairs, _ = self.own_candidates(name)
        # In comparisons, a named target remains itself even when another car is fully named in the quote.
        # Example: target 小米SU7, quote SU7比特斯拉Model 3更舒服.
        if len(name_pairs)==1:
            named=next(iter(name_pairs))
            aliases=[a for r in RULES['series_aliases'] if (r['brand'],r['series'])==named for a in r['aliases']] or [named[1]]
            supported=any(match(a,own) for a in aliases)
            same_code_conflict=any(p[1]==named[1] and p[0]!=named[0] for p in self.explicit_pairs(own))
            if supported and not same_code_conflict and (not name_brands or named[0] in name_brands):
                pairs={named}
                pm='own_named_target_with_alias_support'
        literal_brand = next((cb for cb,forms in self.forms.items() if any(fold(name)==fold(f) for f in forms)),None)
        if literal_brand and literal_brand in own_brands and len(pairs)!=1:
            b,method=literal_brand,'brand_name_only'
            pairs=set()
        # More than one name in a quotation: use the product's supported name, not every co-mentioned car.
        if len(pairs) > 1:
            narrowed = pairs & name_pairs
            if len(narrowed) == 1:
                pairs = narrowed
            else:
                eb=old.brand(e.get('brand')); es=clean_series(e.get('series'),eb)
                supported = {(eb,es)} & pairs
                if supported:
                    pairs = supported
        if not b and len(pairs) == 1:
            chosen = next(iter(pairs))
            # A name such as 尚界酥妻 explicitly defeats the SU7 forum prior.
            explicit_name_conflict = name_brands and chosen[0] not in name_brands
            # A differently named comparison object does not change the target's brand.
            direct_own_conflict = own_brands and chosen[0] not in own_brands and pm!='own_named_target_with_alias_support'
            if explicit_name_conflict or direct_own_conflict:
                conflict_brands = name_brands or own_brands
                if len(conflict_brands) == 1:
                    b = next(iter(conflict_brands))
                    method = 'explicit_brand_override'
                reasons.append('明确品牌覆盖别名默认车系')
            else:
                b, s = chosen
                method = pm
        elif not b and len(pairs) > 1:
            reasons.append('本条证据有多个车型且无法唯一指代')
        # Recover an already supported explicit model from V1; only its parent level is used.
        if not b and previous and previous.get('status') == 'resolved' and previous.get('normalized'):
            n = previous['normalized']
            pb=n['brand'];ps=clean_series(n['series'],pb)
            if ps and match(ps, own) and (not name_brands or pb in name_brands):
                b, s, method = pb, ps, 'existing_supported_series'
        if not b and len(own_brands) == 1:
            b, method = next(iter(own_brands)), 'own_explicit_brand'
            # A bare numeric model can be resolved only with explicit brand plus supporting model evidence.
            es = clean_series(e.get('series'),b)
            if (b,es) in self.pairs and match(es, own):
                s = es
        if not b:
            for a in RULES['brand_aliases']:
                if match(a['aliases'][0], name) and match(a['aliases'][0], own):
                    b, method = a['brand'], 'colloquial_brand_only'
                    break
        # Version-only/coreference mentions: inspect title and whole post before applying the forum prior.
        if not b or (b=='小米' and not s and not literal_brand):
            generic = bool(re.fullmatch(r'(?:小米)?(?:汽车|SUV|轿车|车)', name, re.I))
            su7_cue = any(match(a, own) or match(a, name) for a in RULES['series_aliases'][0]['aliases'])
            implicit = any(match(a, name) or match(a, own) for a in RULES['implicit_target_forms']) or bool(re.search(r'小米.*(?:标准|MAX|PRO|Ultra)', name, re.I))
            if generic and ('小米' in name or '小米' in own):
                b, method = '小米', 'brand_only_generic_vehicle'
            elif su7_cue or implicit:
                title_pairs = self.explicit_pairs(title)
                post_pairs = self.explicit_pairs(post_text)
                if b:
                    title_pairs={p for p in title_pairs if p[0]==b}
                    post_pairs={p for p in post_pairs if p[0]==b}
                if su7_cue:
                    # SU7 tokens and user-approved aliases default to Xiaomi unless this mention names another brand.
                    explicit_brands = name_brands | own_brands
                    if explicit_brands and '小米' not in explicit_brands:
                        if len(explicit_brands) == 1:
                            b, method = next(iter(explicit_brands)), 'explicit_brand_override'
                        reasons.append('SU7别名与明确品牌冲突')
                    else:
                        b, s, method = '小米', 'SU7', 'forum_context_alias'
                elif len(title_pairs) == 1 and len(post_pairs | title_pairs) == 1:
                    b, s = next(iter(title_pairs))
                    method = 'title_and_post_coreference'
                elif len(post_pairs) == 1:
                    b, s = next(iter(post_pairs))
                    method = 'post_coreference'
                elif not post_pairs and not self.brand_hits(title) - {'小米'} and not self.brand_hits(own) - {'小米'}:
                    b, s, method = '小米','SU7','forum_implicit_target'
                else:
                    reasons.append('版本或指代存在多个可能车型')
        if b and s and own_brands and b not in own_brands and method!='own_named_target_with_alias_support':
            s = None
            reasons.append('车型与明确品牌冲突降至品牌')
        if b:
            result.update(brand=b, series=s, method=method, status='mapped', resolution_level='series' if s else 'brand')
            result['resolution_basis'] = [{'scope': 'own_evidence', 'evidence': e['evidence']}]
            matched_aliases=[a for r in RULES['series_aliases'] if (r['brand'],r['series'])==(b,s) for a in r['aliases'] if match(a,own)]
            if matched_aliases:
                result['resolution_basis'].append({'scope':'alias_dictionary','version':RULES['version'],'matched_aliases':matched_aliases})
            uses_forum=('forum' in method) or ((b,s)==('小米','SU7') and not any(match(f,own) for f in self.forms['小米']))
            if uses_forum:
                result['resolution_basis'].append({'scope':'forum_context','platform':'汽车之家','forum_series':'小米SU7','used_as_default':True})
            if method in {'title_and_post_coreference','post_coreference'}:
                result['resolution_basis'].append({'scope':'title_and_post','title':title})
            # Attribute extraction never turns missing fields into additional taxonomy nodes.
            year = e.get('model_year')
            years = set(re.findall(r'(20\d{2})(?:年)?款', own))
            if len(years) == 1 and (not year or str(year) in years):
                year = next(iter(years))
                result['attributes']['model_year'] = year
                result['attribute_evidence']['model_year'] = 'own_evidence'
            elif year:
                reasons.append('原年款字段无明确本条证据或冲突，保留在original')
            v, conflict = old.trim_value(e.get('version'))
            lexical, _ = old.trim_value(name)
            known_markers = ['Ultra','Max','Pro','标准版','创始版','原型车','GT','FR','Plaid','Performance','限量版','挖孔版']
            if lexical and any(k in lexical for k in known_markers) and lexical != name:
                v = lexical
            if v and not conflict:
                # Known version labels may be colloquial; each component still needs supporting text.
                markers = [k for k in known_markers if k in v]
                supported = all(any(match(a, own) for a in {'标准版':['标准'], '创始版':['创始'], '原型车':['原型','prototype']}.get(k,[k])) for k in markers)
                if (markers and supported) or (not markers and fold(v) in fold(own)):
                    result['attributes']['version'] = v
                    result['attribute_evidence']['version'] = 'own_evidence'
                else:
                    reasons.append('版本字段未被本条证据充分支持，保留在original')
            gen = old.generation(own)
            if gen:
                result['attributes']['generation'] = gen
                result['attribute_evidence']['generation'] = 'own_evidence'
            if b == '小米' and s == 'SU7':
                year = result['attributes']['model_year']
                candidates = [c for c in self.catalog if c['eligible'] and (not year or c['model_year'] == year)]
                exact = [c for c in candidates if year and fold(c['catalog_trim']) in fold(own)]
                if len(exact) == 1 and not any(k in fold(own) for k in ['prototype','原型','猜想']):
                    result.update(specid=exact[0]['specid'], resolution_level='configuration', catalog_status='exact_year_and_descriptor')
                    result['attributes']['version'] = exact[0]['catalog_trim']
                else:
                    version = result['attributes']['version'] or ''
                    if 'Ultra' in version or '原型车' in version:
                        candidates = []
                    elif 'Max' in version:
                        candidates = [c for c in candidates if 'max' in fold(c['catalog_trim'])]
                    elif 'Pro' in version:
                        candidates = [c for c in candidates if 'pro' in fold(c['catalog_trim'])]
                    elif '标准' in version:
                        candidates = [c for c in candidates if not re.search(r'max|pro',fold(c['catalog_trim']))]
                    if '创始' in version:
                        candidates = [c for c in candidates if '创始' in c['catalog_trim']]
                    result['catalog_candidates'] = [c['specid'] for c in candidates]
                    result['catalog_status'] = 'insufficient_identification' if candidates else 'not_covered'
        else:
            reasons.append('无法确认品牌或车系，保留待复核')
        result['review_required'] = bool(reasons)
        return result


def node_path(m):
    if not m['brand']:
        return []
    nodes = [{'id':'root:vehicles','label':'汽车产品','level':'root','parent_id':None}]
    bid = eid('brand',[fold(m['brand'])])
    nodes.append({'id':bid,'label':m['brand'],'level':'brand','parent_id':'root:vehicles'})
    if m['series']:
        sid = eid('series',[fold(m['brand']),fold(m['series'])])
        nodes.append({'id':sid,'label':m['series'],'level':'series','parent_id':bid})
        if m['specid']:
            nodes.append({'id':'autohome:spec:'+m['specid'],'label':m['specid'],'level':'configuration','parent_id':sid})
    return nodes


def write_outputs(output, posts, mappings, catalog, source_hashes, old_maps):
    output.mkdir(parents=True)
    def js(name, obj):
        (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def jl(name, rows):
        (output/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    def csvout(name, rows):
        if not rows:
            return
        with (output/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
            for r in rows:
                w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})
    nodes = {'root:vehicles':{'id':'root:vehicles','label':'汽车产品','level':'root','parent_id':None}}
    direct=collections.Counter();rollup=collections.Counter();nodeposts=collections.defaultdict(set)
    for m in mappings:
        ns=node_path(m)
        for n in ns:
            nodes[n['id']]=n
        m['node_path']=[n['label'] for n in ns if n['level']!='root']
        m['ancestor_ids']=[n['id'] for n in ns[:-1]]
        m['node_id']=ns[-1]['id'] if ns else None
        if m['node_id']:
            direct[m['node_id']]+=1
            for n in ns:
                rollup[n['id']]+=1;nodeposts[n['id']].add(m['post_id'])
    lookup={(m['post_id'],m['local_product_id']):m for m in mappings}
    refs={c['specid']:c for c in catalog}
    for n in nodes.values():
        if n['level']=='configuration':
            ref=refs[n['id'].rsplit(':',1)[-1]]
            n['label']=ref['name'];n['specid']=ref['specid']
        n.update(direct_mentions=direct[n['id']],rollup_mentions=rollup[n['id']],rollup_posts=len(nodeposts[n['id']]))
    for m in mappings:
        if m['specid']:
            m['node_path'][-1]=refs[m['specid']]['name']
    # Tree paths contain each mention at most once, and siblings cannot add unknown records to leaf nodes.
    checks={
      'source_hashes_unchanged':all(sha(Path(p))==v for p,v in source_hashes.items()),
      'all_mentions_once':len(lookup)==len(mappings)==sum(len(p['products']) for p in posts),
      'all_nodes_have_valid_parent':all(n['parent_id'] is None or n['parent_id'] in nodes for n in nodes.values()),
      'taxonomy_node_uniqueness':len(nodes)==len({n['id'] for n in nodes.values()}),
      'mention_node_fk':all(m['node_id'] is None or m['node_id'] in nodes for m in mappings),
      'one_deepest_node_per_mention':sum(direct.values())==sum(m['status']=='mapped' for m in mappings),
      'each_ancestor_once':all(len(m['ancestor_ids'])==len(set(m['ancestor_ids'])) for m in mappings),
      'tree_rollup_consistent':all(n['rollup_mentions']==n['direct_mentions']+sum(c['rollup_mentions'] for c in nodes.values() if c['parent_id']==n['id']) for n in nodes.values()),
      'no_null_tuple_entities':all(n['level'] in {'root','brand','series','configuration'} and (n['level']!='configuration' or 'specid' in n) for n in nodes.values()),
      'no_hypothetical_configs':all(m['specid']!='74430' for m in mappings),
      'config_needs_year':all(m['attributes']['model_year'] for m in mappings if m['specid']),
      'human_semantic_acceptance':'not_measured'}
    assert all(v is True for k,v in checks.items() if k!='human_semantic_acceptance'),checks
    links=[]
    for p in posts:
        for c in p['claims']:
            for t in c['target_products']:
                m=lookup[p['post_id'],t['product_id']]
                links.append({'post_id':p['post_id'],'claim_id':c['id'],'local_product_id':t['product_id'],'role':t['role'],
                              'node_id':m['node_id'],'ancestor_ids':m['ancestor_ids'],'resolution_level':m['resolution_level'],'attributes':m['attributes']})
    aliases=collections.defaultdict(lambda:{'count':0,'posts':set()})
    for m in mappings:
        key=(m['raw_name'],m['node_id'],m['resolution_level'],m['method'],m['review_required'])
        aliases[key]['count']+=1;aliases[key]['posts'].add(m['post_id'])
    aliasrows=sorted([{'raw_name':k[0],'node_id':k[1],'resolution_level':k[2],'method':k[3],'review_required':k[4],
                       'mentions':v['count'],'posts':len(v['posts']),'example_post_id':min(v['posts'])} for k,v in aliases.items()],key=lambda r:-r['mentions'])
    transitions=collections.Counter((old_maps[m['post_id'],m['local_product_id']]['status'],m['status'],m['resolution_level']) for m in mappings)
    stats={'posts':len(posts),'mentions':len(mappings),'taxonomy_nodes_excluding_root':len(nodes)-1,
           'node_counts_by_level':dict(collections.Counter(n['level'] for n in nodes.values())),
           'mention_counts_by_level':dict(collections.Counter(m['resolution_level'] for m in mappings)),
           'status_counts':dict(collections.Counter(m['status'] for m in mappings)),
           'methods':dict(collections.Counter(m['method'] for m in mappings)),
           'needs_review_mentions':sum(m['review_required'] for m in mappings),'claim_product_links':len(links),
           'newly_mapped_from_v1':sum(old_maps[m['post_id'],m['local_product_id']]['status']!='resolved' and m['status']=='mapped' for m in mappings),
           'catalog_linked_mentions':sum(bool(m['specid']) for m in mappings)}
    claims=[c for p in posts for c in p['claims']]
    with POST_METADATA.open(encoding='utf-8-sig',newline='') as f:
        metadata={r['post_id']:r for r in csv.DictReader(f)}
    for m in mappings:
        meta=metadata.get(m['post_id'],{})
        m['source_url']=meta.get('source_url')
        m['post_title']=meta.get('title')
    dates=[metadata[p['post_id']]['created_at'] for p in posts if metadata.get(p['post_id'],{}).get('created_at')]
    from urllib.parse import urlsplit
    authors=[]
    for p in posts:
        home=metadata.get(p['post_id'],{}).get('author_home','').strip()
        if home:
            u=urlsplit(home);authors.append(u.netloc.lower()+u.path.rstrip('/'))
    su7claims=[]
    for p in posts:
        for c in p['claims']:
            if any(lookup[p['post_id'],t['product_id']]['brand']=='小米' and lookup[p['post_id'],t['product_id']]['series']=='SU7' for t in c['target_products']):
                su7claims.append((p['post_id'],c['id']))
    readiness={'posts':len(posts),'claims':len(claims),'su7_linked_unique_claims':len(set(su7claims)),
        'claim_type':dict(collections.Counter(c['claim_type'] for c in claims)),
        'aspect':dict(collections.Counter(c['aspect'] for c in claims)),
        'experience_basis':dict(collections.Counter(c['experience_basis'] for c in claims)),
        'journey_stage':dict(collections.Counter(c['journey_stage'] for c in claims)),
        'statement_type':dict(collections.Counter(c['statement_type'] for c in claims)),
        'ownership_status':dict(collections.Counter(p['user_context']['ownership_status'] for p in posts)),
        'claims_with_usage_context':sum(c.get('usage_context') is not None for c in claims),
        'claims_with_comparison':sum(c.get('comparison') is not None for c in claims),
        'claims_without_target_products':sum(not c['target_products'] for c in claims),
        'metadata_matched_posts':sum(p['post_id'] in metadata for p in posts),
        'posts_with_timestamp':len(dates),'timestamp_min':min(dates) if dates else None,'timestamp_max':max(dates) if dates else None,
        'posts_with_author_home':len(authors),'distinct_platform_author_home':len(set(authors)),
        'semantic_acceptance':'not_measured','scope':'field availability profile; not customer needs findings'}
    jl('mention-mapping.jsonl',mappings);jl('claim-product-links.jsonl',links)
    ordered=sorted(nodes.values(),key=lambda n:(n['level'],-n['rollup_mentions'],n['label']))
    js('taxonomy.json',ordered);csvout('taxonomy.csv',[{'id':n['id'],'label':n['label'],'level':n['level'],'parent_id':n['parent_id'],
          'direct_mentions':n['direct_mentions'],'rollup_mentions':n['rollup_mentions'],'rollup_posts':n['rollup_posts']} for n in ordered])
    csvout('mention-mapping.csv',[{k:m[k] for k in ['post_id','local_product_id','raw_name','node_id','node_path','resolution_level','attributes','method','status','review_required','review_reasons']} for m in mappings])
    csvout('alias-mapping.csv',aliasrows)
    csvout('review-queue.csv',[r for r in aliasrows if r['review_required'] or r['resolution_level']=='unresolved'])
    js('v1-comparison.json',{'previous_entity_count':966,'taxonomy_nodes_excluding_root':len(nodes)-1,
       'important':'V1实体组合数与V2层级节点数不是同一个统计量；核心是取消空值组合实体。',
       'transitions':[{'v1_status':a,'v2_status':b,'level':c,'mentions':n} for (a,b,c),n in transitions.items()]})
    js('summary.json',stats);js('checks.json',checks);js('alias-dictionary.json',RULES);js('catalog-reference.json',catalog)
    js('analysis-readiness.json',readiness)
    # Reuse the V1 UI as a presentation base, with V2 mappings and distinct annotation namespace.
    oldhtml=(V1/'final/review.html').read_text(encoding='utf-8')
    shell=re.sub(r'const data=.*?;let page=0,view=\[\];', 'const data=__DATA__;let page=0,view=[];', oldhtml, count=1,flags=re.S)
    shell=shell.replace('auto018-v1-','auto018-taxonomy-v2-').replace('产品实体归一 · 第一轮','产品 taxonomy · V2')
    shell=shell.replace('SU7 产品实体归一复核','SU7 产品 taxonomy 复核')
    shell=shell.replace('<option>resolved</option>','<option>mapped</option>')
    shell=shell.replace('语料映射，不代表官方车型库或人工语义验收。specid 仅按用户配置表快照关联；缺失信息保持未知。','品牌 → 车系 → 明确配置。每条提及落到最深可确认节点；论坛口语可归类，未知年款/版本留空。下方可按 taxonomy 节点和层级筛选。')
    panel='<details open><summary>Taxonomy 层级目录（直接落点 / 含后代提及；帖子数独立去重）</summary><div style="max-height:300px;overflow:auto">'
    import html
    def tree(parent):
        children=sorted([n for n in nodes.values() if n['parent_id']==parent],key=lambda n:-n['rollup_mentions'])
        return '<ul>'+''.join('<li>'+html.escape(n['label'])+' <small>'+str(n['direct_mentions'])+' / '+str(n['rollup_mentions'])+' · '+str(n['rollup_posts'])+'帖</small>'+tree(n['id'])+'</li>' for n in children)+'</ul>' if children else ''
    panel+=tree('root:vehicles')+'</div></details><label>层级 <select id="level"><option value="">全部</option><option value="brand">品牌</option><option value="series">车系</option><option value="configuration">配置</option><option value="unresolved">未识别</option></select></label><label>节点 <select id="node"><option value="">全部节点（含后代）</option>'+''.join('<option value="'+n['id']+'">'+html.escape(n['label'])+'</option>' for n in ordered if n['level']!='root')+'</select></label>'
    shell=shell.replace('<main id="list">',panel+'<main id="list">')
    # Include the brand in selectors: 小米/SU7 and 金彭/SU7 must be distinguishable.
    for n in ordered:
        if n['level']=='root':
            continue
        labels=[n['label']];parent=n['parent_id']
        while parent and parent!='root:vehicles':
            labels.insert(0,nodes[parent]['label']);parent=nodes[parent]['parent_id']
        old_option='<option value="'+n['id']+'">'+html.escape(n['label'])+'</option>'
        new_option='<option value="'+n['id']+'">'+html.escape(' / '.join(labels))+'</option>'
        shell=shell.replace(old_option,new_option)
    shell=shell.replace("view=data.filter(r=>", "view=data.filter(r=>(!$('level').value||r.resolution_level===$('level').value)&&(!$('node').value||r.node_id===$('node').value||r.ancestor_ids.includes($('node').value))&&")
    shell=shell.replace("$('q').oninput=$('status').onchange=", "$('level').onchange=$('node').onchange=$('q').oninput=$('status').onchange=")
    shell=shell.replace('normalized:r.normalized,method:r.method', 'path:r.node_path,level:r.resolution_level,attributes:r.attributes,method:r.method')
    shell=shell.replace('candidates:r.catalog_candidates,reasons:r.review_reasons','candidates:r.catalog_candidates,basis:r.resolution_basis,reasons:r.review_reasons')
    shell=shell.replace('<small>${esc(r.post_id)} / ${esc(r.local_product_id)}</small>', '<p>${esc(r.post_title||\'\')}</p><small>${esc(r.post_id)} / ${esc(r.local_product_id)}</small> ${r.source_url&&/^https:\/\/club.autohome.com.cn\//.test(r.source_url)?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">打开汽车之家原帖</a>`:\'\'}')
    review=[{**m,'normalized':None,'catalog_specid':m['specid'],'evidence':m['original']['evidence'],
             'source_type_note':'语境映射依据：'+(m['method'] or 'unresolved')+'；图片说明保持原来源。'} for m in mappings]
    data=json.dumps(review,ensure_ascii=False).replace('<','\\u003c')
    (output/'review.html').write_text(shell.replace('__DATA__',data),encoding='utf-8')
    js('manifest.json',{'version':VERSION,'source_hashes':source_hashes,'stats':stats,'scope':'offline_taxonomy_preparation',
        'no_model_calls':True,'human_semantic_acceptance':'pending','files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(output.iterdir()) if p.is_file()]})
    return stats,checks


def main(output):
    if output.exists():
        raise ValueError('Output already exists; choose a fresh directory.')
    sources=[SOURCE,CATALOG,POST_METADATA,V1/'final/mention-mapping.jsonl',V1/'final/corpus-name-anchors.json',V1/'normalize_entities.py',HERE/'aliases.json',Path(__file__),HERE/'test_taxonomy.py']
    hashes={str(p):sha(p) for p in sources}
    posts=read_jsonl(SOURCE)
    previous={(m['post_id'],m['local_product_id']):m for m in read_jsonl(V1/'final/mention-mapping.jsonl')}
    with CATALOG.open(encoding='utf-8-sig',newline='') as f:
        catalog=old.make_catalog(list(csv.DictReader(f)))
    r=Resolver(json.loads((V1/'final/corpus-name-anchors.json').read_text(encoding='utf-8')),catalog)
    mappings=[]
    for post in posts:
        original=json.loads((old.INPUTS/(post['post_id']+'.json')).read_text(encoding='utf-8'))
        for e in post['products']:
            mappings.append(r.resolve(post['post_id'],e,original,previous[(post['post_id'],e['id'])]))
    stats,checks=write_outputs(output,posts,mappings,catalog,hashes,previous)
    print(json.dumps({'output':str(output),'summary':stats,'checks':checks},ensure_ascii=False,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=HERE/'delivery')
    main(ap.parse_args().output)
