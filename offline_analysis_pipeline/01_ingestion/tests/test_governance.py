import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from urllib.parse import urlsplit,parse_qs

from autoinsight_ingestion.contracts import JobConfig,IngestionError
from autoinsight_ingestion.storage import Repository
from autoinsight_ingestion.storage.repository import TABLES
from autoinsight_ingestion.ingest import import_bytes,replay
from autoinsight_ingestion.normalize.legacy import parse
from autoinsight_ingestion.normalize.pages import forum_list
from autoinsight_ingestion.standard import project
from autoinsight_ingestion.collect.runner import run_collection
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.field_contract import POST_FIELDS
from test_foundation import post,csv_bytes
from test_service import list_html,POST_HTML,USER_HTML


def complete_post(tid='123'):
    row=post(tid,full=[['text','正文']])
    row.update({'帖子相对时间':'2026/10/20 09:00:00','发布时间':'2026-10-20 09:00:00',
                '浏览数':'100','回帖数':'0','作者昵称':'作者','列表图片数':'0','帖子标签':'讨论',
                '作者信息':'{"UserId":42}','是否匹配正文':'是','作者帖子数':'3',
                '作者热门帖数':'0','作者回复数':'1','作者注册时间':'2020-01-01',
                '作者来自':'上海','作者爱车':'小米SU7','作者热门帖链接':'https://example.invalid/post',
                '作者昵称_列表页':'作者','作者主页_列表页':'https://i.autohome.com.cn/42/home.html'})
    return row


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Repository(Path(self.tmp.name)/'data')
    def tearDown(self): self.store.close(); self.tmp.cleanup()

    def test_exactly_eight_tables_no_legacy_views(self):
        names={r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names,set(TABLES))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0],0)

    def test_legacy_columns_all_accounted_for(self):
        row=complete_post()
        for key in POST_FIELDS: row.setdefault(key,'')
        record=list(parse(csv_bytes([row]),'posts'))[0]
        table,data=project(record)
        self.assertEqual(table,'posts'); self.assertEqual(data['reply_count'],0)
        self.assertEqual(json.loads(data['author_context_json'])['declared_vehicle'],'小米SU7')
        self.assertEqual(record.audit['legacy_body_match_status'],'是')

    def test_unknown_column_fails_closed_keeps_raw(self):
        row=complete_post(); row['unexpected_new_field']='value'
        with self.assertRaises(IngestionError): import_bytes(self.store,csv_bytes([row]),'posts',{})
        self.assertEqual(self.store.verify()['counts']['posts'],0)
        self.assertEqual(self.store.verify()['counts']['source_snapshots'],1)

    def test_new_batch_blank_not_hidden_by_old_rows(self):
        row=complete_post()
        good=import_bytes(self.store,csv_bytes([row]),'posts',{})
        self.assertTrue(good['counts']['batch_quality']['passed'])
        for key in ['作者帖子数','作者热门帖数','作者回复数','作者爱车','作者热门帖链接']: row[key]=''
        bad=import_bytes(self.store,csv_bytes([row]),'posts',{})
        self.assertEqual(bad['status'],'partial'); self.assertFalse(bad['publishable'])
        self.assertIn('author_context.declared_vehicle',bad['counts']['batch_quality']['all_blank_fields']['posts'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)

    def test_old_user_replay_cannot_regress_new(self):
        def load(followers,t):
            return import_bytes(self.store,csv_bytes([dict(user_id='42',nickname='name',followers=str(followers),following='0',status='ok',fetched_at=t)]),'users',{},retrieved_at=t)
        old=load(1,'2026-10-20T00:00:00+00:00'); load(2,'2026-10-21T00:00:00+00:00')
        replay(self.store,old['response_id'])
        self.assertEqual(self.store.db.execute('SELECT follower_count FROM users').fetchone()[0],2)
        self.assertEqual(self.store.verify()['counts']['source_snapshots'],2)

    def test_equal_time_conflict_does_not_choose_by_hash(self):
        first=complete_post(); second=dict(first,帖子标题='不同标题')
        import_bytes(self.store,csv_bytes([first]),'posts',{},retrieved_at='2026-10-21T00:00:00+00:00')
        result=import_bytes(self.store,csv_bytes([second]),'posts',{},retrieved_at='2026-10-21T00:00:00+00:00')
        self.assertEqual(result['counts']['conflict'],1)
        self.assertEqual(self.store.db.execute('SELECT title FROM posts').fetchone()[0],first['帖子标题'])

    def test_declared_source_priority_not_filename_selects_reference(self):
        row=complete_post(); import_bytes(self.store,csv_bytes([row]),'posts',{'source_priority':20})
        old=dict(row,帖子标题='旧标题')
        result=import_bytes(self.store,csv_bytes([old]),'posts',{'source_priority':10})
        self.assertEqual(result['counts']['older_skipped'],1)

    def test_http_200_blank_retries_and_records_budget(self):
        config=JobConfig.parse(dict(mode='collect',allow_network=True,max_requests=2,max_attempts=2))
        tr=Transport(self.store,self.store.begin_run({}),config)
        response=MagicMock(); response.__enter__.return_value=response
        response.status=200; response.read.return_value=b''
        with patch.object(tr.opener,'open',return_value=response),patch('autoinsight_ingestion.collect.http.time.sleep'):
            with self.assertRaises(IngestionError): tr.get('https://club.m.autohome.com.cn/x',validator=forum_list)
        self.assertEqual(tr.used,2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM collection_checkpoints').fetchone()[0],0)
        self.assertGreater(self.store.db.execute('SELECT COUNT(*) FROM collection_failures').fetchone()[0],0)


class IncrementalTests(unittest.TestCase):
    setUp=GovernanceTests.setUp
    tearDown=GovernanceTests.tearDown
    def run_pages(self,pages,fail_detail=False,fail_user=False,**options):
        store=self.store
        class Fake:
            def __init__(self,store,run,config,cancelled): self.store,self.run,self.config,self.used=store,run,config,0
            def get(self,url,validator=None):
                if self.used>=self.config.max_requests: raise IngestionError('request_budget_exhausted')
                self.used+=1
                if 'pageindex=' in url: text=pages.get(int(parse_qs(urlsplit(url).query)['pageindex'][0]),'')
                elif 'getclicksandreplys' in url: text=json.dumps({'result':[{'topicid':123,'views':1,'replys':0}]})
                elif 'i.autohome.com.cn' in url:
                    if fail_user: raise IngestionError('http_error')
                    text=USER_HTML
                else:
                    if fail_detail: raise IngestionError('detail_unavailable')
                    text=POST_HTML
                task=store.task(self.run,'http',url)
                rid=store.response(task,text.encode(),{'url':url,'http_status':200},'2026-10-21T00:00:00+00:00','http_body')
                return dict(task_id=task,response_id=rid,text=text,body=text.encode(),retrieved_at='2026-10-21T00:00:00+00:00',parsed=validator(text) if validator else None)
        cfg=JobConfig.parse(dict(mode='collect',allow_network=True,max_requests=options.get('max_requests',20),
             max_pages=options.get('max_pages',5),series_id='6962',start=options.get('start','2026-10-18'),overlap_days=2))
        with patch('autoinsight_ingestion.collect.runner.now',return_value='2026-10-21T00:00:00+00:00'):
            return run_collection(store,cfg,transport_factory=Fake,cancelled=options.get('cancelled',lambda:False))

    def test_reaching_lower_bound_advances_even_if_user_fails(self):
        result=self.run_pages({1:list_html('123','2026/10/20 09:00:00'),2:list_html('1','2026/10/17 09:00:00')},fail_user=True)
        self.assertTrue(result['counts']['checkpoint_advanced'])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(self.store.db.execute('SELECT checked_until FROM collection_checkpoints').fetchone()[0],'2026-10-21T00:00:00+00:00')

    def test_known_id_does_not_end_scan(self):
        import_bytes(self.store,csv_bytes([complete_post()]),'posts',{})
        result=self.run_pages({1:list_html('123','2026/10/20 09:00:00'),2:list_html('1','2026/10/17 09:00:00')})
        self.assertEqual(result['counts']['pages'],2)
        self.assertTrue(result['counts']['checkpoint_advanced'])
        self.assertEqual(self.store.verify()['counts']['posts'],1)

    def test_detail_failure_no_checkpoint_then_rescan_recovers(self):
        pages={1:list_html('123','2026/10/20 09:00:00'),2:list_html('1','2026/10/17 09:00:00')}
        first=self.run_pages(pages,fail_detail=True)
        self.assertFalse(first['counts']['checkpoint_advanced'])
        second=self.run_pages(pages)
        self.assertTrue(second['counts']['checkpoint_advanced'])

    def test_pinned_old_post_does_not_end_first_page(self):
        pinned=list_html('1','2000/01/01 00:00:00').replace('<li ','<li data-istop="1" ')
        result=self.run_pages({1:pinned+list_html('123','2026/10/20 09:00:00'),2:list_html('2','2026/10/17 09:00:00')})
        self.assertTrue(result['counts']['checkpoint_advanced']); self.assertEqual(result['counts']['pages'],2)

    def test_unmarked_disorder_no_checkpoint(self):
        result=self.run_pages({1:list_html('1','2000/01/01 00:00:00')+list_html('123','2026/10/20 09:00:00')})
        self.assertEqual(result['error_code'],'publication_order_violation')
        self.assertFalse(result['counts']['checkpoint_advanced'])

    def test_empty_before_bound_keeps_committed_data(self):
        result=self.run_pages({1:list_html('123','2026/10/20 09:00:00'),2:''})
        self.assertEqual(self.store.verify()['counts']['posts'],1)
        self.assertFalse(result['counts']['checkpoint_advanced'])
        self.assertIsNotNone(self.store.db.execute('SELECT page_number FROM collection_failures WHERE page_number=2').fetchone())

    def test_page_limit_and_budget_do_not_advance(self):
        pages={1:list_html('123','2026/10/20 09:00:00')}
        for opts in [dict(max_pages=1),dict(max_requests=1)]:
            result=self.run_pages(pages,**opts)
            self.assertFalse(result['counts']['checkpoint_advanced'])

    def test_overlap_derived_from_success_checkpoint(self):
        pages={1:list_html('123','2026/10/20 09:00:00'),2:list_html('1','2026/10/17 09:00:00')}
        self.run_pages(pages)
        result=self.run_pages(pages,start='')
        self.assertEqual(result['counts']['window_start'],'2026-10-19T00:00:00+00:00')

    def test_cancelled_does_not_advance(self):
        result=self.run_pages({},cancelled=lambda:True)
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual(self.store.verify()['counts']['collection_checkpoints'],0)
