"""Author-card adapter and the shared five-field conversion. No IO."""
from urllib.parse import urljoin

from ..contracts import IngestionError,Record
from ..quality import evaluate
from .basic import number,user_id,clean_text,parse_time
from .pages import Tree,check_page

COUNT_FIELDS=('platform_post_count','popular_post_count','platform_reply_count')
AUTHOR_FIELDS=COUNT_FIELDS+('declared_vehicle','popular_post_urls_raw')


def normalize_author_context(context):
    result=dict(context)
    for key in COUNT_FIELDS:
        if key in result:
            value=result[key]
            result[key]=number(value) if value not in (None,'') else None
    for key in ['declared_vehicle','popular_post_urls_raw']:
        if key in result: result[key]=clean_text(result[key]) or None
    return result


def author_card(text,uid,retrieved_at,flag=0):
    check_page(text)
    root=Tree(text).root
    names=[n for n in root.walk() if n.tag=='a' and n.has_class('name')]
    if len(names)!=1 or user_id(urljoin('https://i.autohome.com.cn',names[0].attrs.get('href','')))!=uid:
        raise IngestionError('author_card_identity_unverified')
    context={k:None for k in AUTHOR_FIELDS}
    availability={}; locators={}; popular_urls=[]
    for link in root.walk():
        if link.tag!='a' or not link.has_class('count-item'): continue
        strong=[n for n in link.walk() if n.tag=='strong']
        label=link.text()
        key='popular_post_count' if '热门' in label else ('platform_reply_count' if '回复' in label else ('platform_post_count' if '帖子' in label else None))
        if not key: continue
        if key in locators: raise IngestionError('author_card_counter_ambiguous')
        value=number(strong[0].text()) if len(strong)==1 else None
        if not isinstance(value,int) or value<0: raise IngestionError('author_card_counter_invalid')
        context[key]=value; locators[key]=link.locator
        availability[key]=dict(state='available',locator=link.locator)
        if key=='popular_post_count' and link.attrs.get('href'):
            url=urljoin('https://club.autohome.com.cn/',link.attrs['href'])
            if not url.startswith('https://'): raise IngestionError('author_card_url_invalid')
            popular_urls.append(url)
    missing_counters=[k for k in COUNT_FIELDS if context[k] is None]
    if missing_counters and flag==1:
        for k in missing_counters:
            availability[k]=dict(state='not_provided_by_card',locator='html:author-card')
    elif missing_counters:
        raise IngestionError('author_card_counters_missing')
    cars=list(dict.fromkeys(clean_text(n.text()) for n in root.walk() if n.tag=='a' and n.has_class('profile-cars-item') and clean_text(n.text())))
    context['declared_vehicle']=' | '.join(cars) if cars else None
    context['popular_post_urls_raw']=' | '.join(popular_urls) if popular_urls else None
    for key in ['declared_vehicle','popular_post_urls_raw']:
        availability[key]=dict(state='available' if context[key] is not None else 'not_displayed',locator='html:author-card')
    for key in ['follower_count','following_count','ip_location','sex_explicit']:
        availability[key]=dict(state='not_provided_by_card',locator='html:author-card')
    for node in root.walk():
        if node.tag!='div' or not node.has_class('user-profile'): continue
        values=[n for n in node.walk() if n.has_class('profile-text')]
        if len(values)!=1: continue
        if '来自' in node.text(): context['declared_location']=clean_text(values[0].text())
        elif '注册' in node.text(): context['registered_at_raw']=clean_text(values[0].text())
    context=normalize_author_context(context)
    data=dict(source_url=urljoin('https://i.autohome.com.cn',names[0].attrs['href']),
              nickname=clean_text(names[0].attrs.get('title') or names[0].text()),
              fetched_at=retrieved_at,status='ok',field_availability=availability,
              **{k:context[k] for k in COUNT_FIELDS},declared_vehicle=context['declared_vehicle'],
              popular_post_urls=popular_urls,registered_at=parse_time(context.get('registered_at_raw'))['value'],
              csv_location=context.get('declared_location'),author_context=context)
    return evaluate(Record('users',uid,data,'html:author-card',parser_version='autohome-author-card-1'))


def attach_card_to_post(post,card,snapshot_id):
    if post.data.get('user_id')!=card.source_id: raise IngestionError('post_author_card_mismatch')
    post.data['author_context']=dict(card.data['author_context'],source_snapshot_id=snapshot_id,retrieved_at=card.data['fetched_at'])
    post.data.setdefault('field_availability',{}).update({
        'author_context.'+k:dict(v,source_snapshot_id=snapshot_id) for k,v in card.data['field_availability'].items() if k in AUTHOR_FIELDS})
    post.audit['author_card_snapshot_id']=snapshot_id
    post.parser_version='autohome-page-2'


def merge_card_into_home(home,card,snapshot_id):
    if home.source_id!=card.source_id: raise IngestionError('home_author_card_mismatch')
    for key in COUNT_FIELDS+('declared_vehicle','popular_post_urls','registered_at'):
        home.data[key]=card.data.get(key)
    home.data['csv_location']=card.data.get('csv_location')
    home.data.setdefault('field_availability',{}).update({k:dict(v,source_snapshot_id=snapshot_id) for k,v in card.data['field_availability'].items() if k in AUTHOR_FIELDS})
    home.audit['author_card_snapshot_id']=snapshot_id
    home.parser_version='autohome-home-with-card-1'
