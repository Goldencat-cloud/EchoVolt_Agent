"""Source aliases are input compatibility only, never the public database schema."""
POST_FIELDS = {
 '帖子标题':'posts.title','帖子链接':'posts.source_url','帖子相对时间':'posts.list_time_raw',
 '浏览数':'posts.view_count','回帖数':'posts.reply_count','列表图片数':'posts.list_image_count',
 '帖子标签':'posts.tags_json','作者昵称_列表页':'posts.list_author_nickname',
 '作者主页_列表页':'posts.list_author_home_url','正文':'posts.body_text',
 '作者信息':'source_snapshots原文件（原文取证，不进业务表）','是否匹配正文':'source_snapshots.issues_json.legacy_body_match_status',
 '图片链接':'posts.content_segments_json[image]','全文':'posts.content_segments_json / posts.body_text',
 '视频ID':'posts.content_segments_json[video]','发布时间':'posts.published_raw / posts.published_at',
 '作者昵称':'posts.author_nickname','作者帖子数':'posts.author_context_json.platform_post_count',
 '作者热门帖数':'posts.author_context_json.popular_post_count','作者回复数':'posts.author_context_json.platform_reply_count',
 '作者注册时间':'posts.author_context_json.registered_at_raw','作者来自':'posts.author_context_json.declared_location',
 '作者爱车':'posts.author_context_json.declared_vehicle','作者主页':'posts.author_home_url',
 '作者热门帖链接':'posts.author_context_json.popular_post_urls_raw'}
USER_FIELDS = {
 'user_id':'users.user_id','nickname':'users.nickname','home_url':'users.home_url',
 'sex_raw':'users.sex_raw','sex_label':'users.sex_explicit / sex_inferred; source audit keeps original',
 'sex_source':'users.sex_source','following':'users.following_count','followers':'users.follower_count',
 'ip_location':'users.ip_location','csv_location':'users.declared_location',
 'post_count_in_dataset':'recomputed from posts; imported value audited in source_snapshots',
 'fetched_at':'users.profile_fetched_at','status':'users.profile_status','error':'source_snapshots audit / collection_failures'}
PARAM_FIELDS = {'specid':'product_specs.spec_id','车型名称':'product_specs.spec_name','年款':'product_specs.model_year',
 '状态':'product_specs.sale_status_raw','配置分组':'product_parameters.group_name','配置分类':'product_parameters.category',
 '配置项':'product_parameters.parameter_name','配置值':'product_parameters.value_raw'}
MODEL_FIELDS = {k:v for k,v in PARAM_FIELDS.items() if k in {'specid','车型名称','年款','状态'}} | {
 'specstatus':'product_specs.sale_status_code','厂商指导价':'product_specs.list_price_raw',
 '经销商报价':'product_specs.dealer_price_raw','车型组':'product_specs.model_group','条件标签':'product_specs.condition_tags_json'}
SERIES_FIELDS = {'seriesId':'catalog.series_id','车系名':'catalog.series_name','品牌':'catalog.brand_name',
 '厂商':'catalog.manufacturer_name','级别':'catalog.vehicle_class','指导价':'catalog.guide_price_range_raw','字母':'catalog.initial_letter'}
SOURCE_FIELDS={'posts':POST_FIELDS,'users':USER_FIELDS,'parameters':PARAM_FIELDS,'models':MODEL_FIELDS,'series':SERIES_FIELDS}
ALIASES={'posts':{'post_id','source_url','字段1_链接','title','字段1_文本','text_content','clean_text','multimodal_content',
                  'images','video_ids','author_home','author_nick','created_at','views','replies'},'users':set(),
         'parameters':set(),'models':set(),'series':set()}


def validate_columns(columns,kind):
    from .contracts import IngestionError
    if set(columns)-set(SOURCE_FIELDS[kind])-ALIASES[kind]:
        raise IngestionError('unmapped_source_columns')
