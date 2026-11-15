"""One public field contract shared by historical and live adapters."""
from .contracts import canonical


def project(record):
    d = record.data
    if record.kind == 'posts':
        from .normalize.author import normalize_author_context
        t = d['time']
        return 'posts', {'post_id': record.source_id, 'source_url': d.get('source_url'),
            'title': d.get('title'), 'body_text': d.get('text_content'), 'clean_text': d.get('clean_text'),
            'author_id': d.get('user_id') or None, 'author_nickname': d.get('author_nick'),
            'author_home_url': d.get('author_home'), 'published_at': t['value'],
            'published_raw': t['raw'], 'time_precision': t['precision'], 'time_basis': t['basis'],
            'view_count': d.get('views'), 'reply_count': d.get('replies'),
            'list_time_raw': d.get('list_time_raw'), 'list_image_count': d.get('list_image_count'),
            'tags_json': canonical(d.get('tags')) if d.get('tags') is not None else None,
            'list_author_nickname': d.get('list_author_nickname'),
            'list_author_home_url': d.get('list_author_home_url'),
            'content_segments_json': canonical(d.get('segments', [])),
            'content_order_status': d.get('sequence_status'),
            'author_context_json': canonical(normalize_author_context(d.get('author_context', {}))),
            'field_availability_json': canonical(d.get('field_availability', {}))}
    if record.kind == 'users':
        aliases = {'home_url': 'source_url', 'following_count': 'following',
                   'follower_count': 'followers', 'declared_location': 'csv_location',
                   'profile_status': 'status', 'profile_fetched_at': 'fetched_at'}
        fields = ['home_url','nickname','sex_raw','sex_explicit','sex_inferred','sex_source',
                  'following_count','follower_count','ip_location','declared_location','profile_status',
                  'profile_fetched_at','registered_at','platform_post_count','popular_post_count',
                  'platform_reply_count','declared_vehicle']
        return 'users', dict(user_id=record.source_id, **{k:d.get(aliases.get(k,k)) for k in fields},
              popular_post_urls_json=canonical(d.get('popular_post_urls')) if d.get('popular_post_urls') is not None else None,
              field_availability_json=canonical(d.get('field_availability', {})))
    if record.kind == 'parameters':
        fields = ['series_id','brand_name','series_name','manufacturer_name','spec_name','model_year','sale_status_raw',
                  'is_concept','list_price_raw','dealer_price_raw','model_group','sale_status_code']
        result=dict(spec_id=record.source_id, **{k:d[k] for k in fields if k in d})
        if 'condition_tags' in d: result['condition_tags_json']=canonical(d['condition_tags'])
        return 'product_specs',result
    if record.kind == 'series':
        return None, {}
    raise ValueError('unhandled_record_kind')
