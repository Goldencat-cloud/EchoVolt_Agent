"""Batch completeness checks do not borrow populated fields from earlier batches."""
EXPECTED = {
 'posts': ('title','source_url','text_content','user_id','views','replies','list_time_raw',
           'author_context.platform_post_count','author_context.popular_post_count',
           'author_context.platform_reply_count','author_context.registered_at_raw',
           'author_context.declared_location','author_context.declared_vehicle','author_context.popular_post_urls_raw'),
 'users': ('nickname','source_url','following','followers','ip_location'),
 'parameters': ('series_id','spec_name','model_year','sale_status_raw'),
 'series': ('brand_name','series_name'),
}


def value_at(data,path):
    for key in path.split('.'):
        data=data.get(key) if isinstance(data,dict) else None
    return data


def populated(value):
    return value is not None and value != '' and value != [] and value != {}


class BatchProfile:
    def __init__(self):
        self.kinds={}

    def add(self,record):
        fields=list(EXPECTED.get(record.kind,()))
        if record.kind=='users' and 'platform_post_count' in record.data:
            fields+=['platform_post_count','popular_post_count','platform_reply_count','declared_vehicle','popular_post_urls']
        item=self.kinds.setdefault(record.kind,dict(rows=0,populated={},not_displayed={}))
        item['rows']+=1
        for k in fields:
            item['populated'].setdefault(k,0); item['not_displayed'].setdefault(k,0)
        for k in item['populated']:
            item['populated'][k]+=int(populated(value_at(record.data,k)))
            key='popular_post_urls_raw' if k=='popular_post_urls' else k
            state=record.data.get('field_availability',{}).get(key,{}).get('state')
            if k in {'author_context.declared_vehicle','author_context.popular_post_urls_raw','declared_vehicle','popular_post_urls'} and state=='not_displayed':
                item['not_displayed'][k]+=1

    def report(self):
        empty={kind:[k for k,n in item['populated'].items() if not n and item['not_displayed'].get(k,0)!=item['rows']] for kind,item in self.kinds.items()}
        return dict(passed=bool(self.kinds) and not any(empty.values()),kinds=self.kinds,all_blank_fields=empty)
