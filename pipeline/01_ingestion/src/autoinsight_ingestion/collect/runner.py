from __future__ import annotations

import json
from datetime import datetime,timedelta
import re

from ..contracts import IngestionError,date_boundary,now,canonical
from ..normalize.legacy import product_json, product_list
from ..normalize.pages import forum_list,post_page,user_page
from ..normalize.author import author_card,attach_card_to_post,merge_card_into_home,AUTHOR_FIELDS
from ..quality.batch import BatchProfile
from .http import Transport


def run_collection(store,config,*,user_ids=(),cancelled=lambda:False,transport_factory=Transport,run_id=None,credential_path=None):
    run_config=config.public()
    run_config["credentials"]="provided" if credential_path else "absent"
    run_id=store.begin_run(run_config,run_id)
    transport=transport_factory(store,run_id,config,cancelled)
    if credential_path and hasattr(transport,"attach_credentials"):
        transport.attach_credentials(credential_path)
    counts=dict(pages=0,records=0,requests=0,issues=0,coverage_status='partial',checkpoint_advanced=False)
    authors=set(user_ids); profile=BatchProfile(); target='run'; page=None
    cards={}; latest_cards={}

    def commit(raw,records):
        for record in records: profile.add(record)
        result=store.ingest(run_id,raw['task_id'],raw['response_id'],records)
        counts['records']+=result['rows']
        counts['issues']+=sum(len(r.issues) for r in records)+result['conflict']+result['incomplete_skipped']
        return result

    def fetch_card(uid,flag=0):
        key=(uid,flag)
        if key in cards: return cards[key]
        url=f'https://club.autohome.com.cn/frontnc/user/getdetailusertpl/{uid}-{flag}'
        try:
            raw=transport.get(url,validator=lambda text:author_card(text,uid,'',flag))
            card=author_card(raw['text'],uid,raw['retrieved_at'])
            commit(raw,[card])
            cards[key]=(card,raw['response_id'])
            latest_cards[uid]=cards[key]
            store.resolved(run_id,url)
            return cards[key]
        except IngestionError as error:
            store.failure(run_id,url,error.code)
            counts['issues']+=1; cards[key]=None
            if error.code in {'cancelled','blocked','blocked_or_rate_limited','request_budget_exhausted'}: raise
            return None

    try:
        if config.kind=='posts':
            scope='autohome:forum:'+(config.series_id or '6962')+':published-desc'
            with store.mutex:
                cp=store.db.execute('SELECT * FROM collection_checkpoints WHERE scope_key=?',(scope,)).fetchone()
            upper=date_boundary(now())
            if config.end: upper=min(upper,date_boundary(config.end,end=True))
            lower=date_boundary(cp['checked_until'])-timedelta(days=config.overlap_days) if cp else date_boundary(config.start)
            if lower is None: raise IngestionError('initial_start_required')
            if config.start: lower=min(lower,date_boundary(config.start))
            if lower>=upper: raise IngestionError('invalid_scan_window')
            if cp and upper<date_boundary(cp['checked_until']): raise IngestionError('backfill_requires_separate_scope')
            counts.update(window_start=lower.isoformat(),window_end=upper.isoformat())
            last=None; seen=set(); unresolved=False; reached=False
            for page in range(1,config.max_pages+1):
                if cancelled(): raise IngestionError('cancelled')
                target=f"https://club.m.autohome.com.cn/Adaptive/Forum/GetTopicListPartial2021?bbs=c&bbsid={config.series_id or '6962'}&pageindex={page}&sort=Lastest&qaType=-1"
                raw=transport.get(target,validator=forum_list)
                items=raw.get('parsed') or forum_list(raw['text']); counts['pages']+=1
                dated=[]; below=False
                # Validate the entire page before allowing a lower-bound stop.
                for item in items:
                    if not item['published_raw']: raise IngestionError('list_publication_time_missing')
                    t=date_boundary(item['published_raw'].replace('/','-'))
                    end=t+timedelta(days=1) if len(item['published_raw'])==10 else t
                    if not item.get('is_pinned') and item['post_id'] not in seen:
                        if last and t>last: raise IngestionError('publication_order_violation')
                        last=t
                        if end<lower: below=True
                    dated.append((item,t,end))
                store.mark_parsed(raw['response_id'],summary={'items':len(items)})
                selected=[]
                for item,t,end in dated:
                    if item['post_id'] in seen: continue
                    seen.add(item['post_id'])
                    if end<lower or t>=upper: continue
                    selected.append(item)
                stats={}
                if selected:
                    target='https://club.autohome.com.cn/frontapi/getclicksandreplys?topicids='+','.join(x['post_id'] for x in selected)
                    sr=transport.get(target)
                    payload=json.loads(sr['text'])
                    if not isinstance(payload.get('result'),list): raise IngestionError('interaction_response_invalid')
                    stats={str(x.get('topicid')):x for x in payload['result']}
                    store.mark_parsed(sr['response_id'])
                for item in selected:
                    target=item['url']
                    try:
                        detail=transport.get(target)
                        record=post_page(detail['text'],item['post_id'],target,detail['retrieved_at'],{**item,'response_id':raw['response_id']})
                        stat=stats.get(item['post_id'],{})
                        record.data.update(views=stat.get('views'),replies=stat.get('allreplys',stat.get('replys')))
                        if record.data['views'] is None or record.data['replies'] is None:
                            raise IngestionError('interaction_values_missing')
                        uid=record.data.get('user_id')
                        if uid:
                            match=re.search(r"topicType\s*:\s*['\"]([^'\"]*)['\"]",detail['text'])
                            card=fetch_card(uid,1 if match and match[1]=='问' else 0)
                            if card: attach_card_to_post(record,*card)
                            else:
                                record.data['field_availability']={
                                    'author_context.'+k:dict(state='request_or_parse_failed') for k in AUTHOR_FIELDS}
                        result=commit(detail,[record]); store.resolved(run_id,target)
                        if result['rejected'] or result['conflict'] or result['incomplete_skipped'] or record.data['time']['value'] is None:
                            unresolved=True
                        if record.data.get('user_id'): authors.add(record.data['user_id'])
                    except IngestionError as error:
                        store.failure(run_id,target,error.code,page=page)
                        unresolved=True; counts['issues']+=1
                        if error.code in {'cancelled','blocked','blocked_or_rate_limited','request_budget_exhausted'}: raise
                if below:
                    reached=True
                    if not unresolved and not cancelled():
                        with store.transaction() as db:
                            db.execute('INSERT INTO collection_checkpoints VALUES(?,?,?,?,?) ON CONFLICT(scope_key) DO UPDATE SET covered_from=excluded.covered_from,checked_until=excluded.checked_until,run_id=excluded.run_id,updated_at=excluded.updated_at',
                                       (scope,min(lower,date_boundary(cp['covered_from'])).isoformat() if cp else lower.isoformat(),upper.isoformat(),run_id,now()))
                        counts.update(coverage_status='time_window_completed',checkpoint_advanced=True)
                    break
            if not reached: counts['stop_reason']='page_limit_before_lower_bound'
        elif config.kind=='users':
            if not authors: raise IngestionError('user_ids_required')
        elif config.kind in {'parameters','product_json'}:
            sid=config.series_id
            target=f'https://car-web-api.autohome.com.cn/car/spec/listSpec?type=0x001f&seriesid={sid}'
            raw=transport.get(target); payload=json.loads(raw['text'])
            if payload.get('returncode')!=0: raise IngestionError('product_source_error')
            store.mark_parsed(raw['response_id'])
            spec_meta=product_list(raw['body'])
            anchors=[str(s['id']) for g in (payload.get('result') or {}).get('otherlist',[]) for s in g.get('speclist',[]) if s.get('id')]
            urls=[f'https://car-web-api.autohome.com.cn/car/param/getParamConf?mode=1&site=1&seriesid={sid}']
            if anchors: urls.append(f'https://car-web-api.autohome.com.cn/car/param/getParamConf?mode=1&site=2&seriesid={sid}&specid={anchors[0]}')
            for target in urls:
                raw=transport.get(target); commit(raw,list(product_json(raw['body'],sid,spec_meta)))
            counts['coverage_status']='configured_product_groups_completed'
        else: raise IngestionError('online_kind_not_supported')

        for uid in sorted(authors):
            if uid not in latest_cards:
                fetch_card(uid)
            target=f'https://i.autohome.com.cn/{uid}/home.html'
            with store.mutex:
                last=store.db.execute("SELECT profile_fetched_at,follower_count,following_count FROM users WHERE user_id=? AND profile_status='ok'",(uid,)).fetchone()
                failed=store.db.execute("SELECT 1 FROM collection_failures WHERE target=? AND state='pending'",(target,)).fetchone()
            if last and last[1] is not None and last[2] is not None and store._time(last[0]) is not None and not failed:
                if datetime.fromisoformat(now()).timestamp()-store._time(last[0])<config.profile_refresh_after_hours*3600: continue
            try:
                raw=transport.get(target); record=user_page(raw['text'],uid,raw['retrieved_at'])
                if uid in latest_cards: merge_card_into_home(record,*latest_cards[uid])
                commit(raw,[record]); store.resolved(run_id,target)
            except IngestionError as error:
                store.failure(run_id,target,error.code); counts['issues']+=1
                if error.code in {'cancelled','blocked','blocked_or_rate_limited','request_budget_exhausted'}: raise
        if config.kind=='users': counts['coverage_status']='configured_users_completed'
        if cancelled(): raise IngestionError('cancelled')
        counts.update(requests=transport.used,batch_quality=profile.report())
        status='succeeded' if counts['coverage_status']!='partial' and not counts['issues'] and counts['batch_quality']['passed'] else 'partial'
        store.finish_run(run_id,status,counts)
        return dict(run_id=run_id,status=status,counts=counts,publishable=status=='succeeded')
    except BaseException as error:
        code=error.code if isinstance(error,IngestionError) else 'collection_failed'
        store.failure(run_id,target,code,page=page)
        counts.update(requests=transport.used,stop_reason=code,batch_quality=profile.report())
        status='interrupted' if code=='cancelled' or isinstance(error,KeyboardInterrupt) else 'partial'
        store.finish_run(run_id,status,counts)
        if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
        return dict(run_id=run_id,status=status,counts=counts,error_code=code,publishable=False)
