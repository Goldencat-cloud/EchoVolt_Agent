import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from autoinsight_ingestion.contracts import JobConfig,IngestionError
from autoinsight_ingestion.normalize.author import author_card,attach_card_to_post
from autoinsight_ingestion.normalize.pages import post_page
from autoinsight_ingestion.normalize.legacy import parse
from autoinsight_ingestion.standard import project
from autoinsight_ingestion.storage import Repository
from autoinsight_ingestion.collect.runner import run_collection
from autoinsight_ingestion.ingest import replay
from autoinsight_ingestion.jobs import JobService
from autoinsight_ingestion.api import make_server
from test_foundation import csv_bytes
from test_service import POST_HTML,USER_HTML,list_html
from test_governance import complete_post

CARD='''<div class="user-card"><a class="name" href="https://i.autohome.com.cn/42/home.html">昵称</a>
<a class="count-item"><strong>3</strong>帖子</a>
<a class="count-item" href="https://i.autohome.com.cn/42/hot"><strong>0</strong>热门</a>
<a class="count-item"><strong>1</strong>回复</a>
<div class="user-profile">注册<div class="profile-text">2020-01-01</div></div>
<div class="user-profile">来自<a class="profile-text">上海</a></div>
<a class="profile-cars-item">小米SU7</a></div>'''


class CardParserTests(unittest.TestCase):
    def test_five_fields_and_real_zero(self):
        rec=author_card(CARD,'42','2026-10-21T00:00:00+00:00')
        _,d=project(rec)
        self.assertEqual(d['platform_post_count'],3)
        self.assertEqual(d['popular_post_count'],0)
        self.assertEqual(d['platform_reply_count'],1)
        self.assertEqual(d['declared_vehicle'],'小米SU7')
        self.assertEqual(json.loads(d['popular_post_urls_json']),['https://i.autohome.com.cn/42/hot'])

    def test_wrong_identity_rejected(self):
        with self.assertRaises(IngestionError): author_card(CARD,'43',None)

    def test_counter_missing_not_zero(self):
        with self.assertRaises(IngestionError): author_card(CARD.replace('<strong>1</strong>回复','回复'),'42',None)

    def test_security_page_not_profile(self):
        with self.assertRaises(IngestionError): author_card('用户访问安全认证'+CARD,'42',None)

    def test_multiple_vehicles_preserved_not_ownership(self):
        card=author_card(CARD+'<a class="profile-cars-item">Model 3</a>','42',None)
        self.assertEqual(card.data['declared_vehicle'],'小米SU7 | Model 3')

    def test_absent_vehicle_is_not_displayed(self):
        rec=author_card(CARD.replace('<a class="profile-cars-item">小米SU7</a>',''),'42',None)
        self.assertIsNone(rec.data['declared_vehicle'])
        self.assertEqual(rec.data['field_availability']['declared_vehicle']['state'],'not_displayed')

    def test_legacy_and_live_same_counter_contract(self):
        legacy=list(parse(csv_bytes([complete_post()]),'posts'))[0]
        live=post_page(POST_HTML,'123','https://club.autohome.com.cn/bbs/thread/abc/123-1.html','2026-10-21T00:00:00+00:00')
        attach_card_to_post(live,author_card(CARD,'42','2026-10-21T00:00:00+00:00'),'card-id')
        a=json.loads(project(legacy)[1]['author_context_json'])
        b=json.loads(project(live)[1]['author_context_json'])
        for k in ['platform_post_count','popular_post_count','platform_reply_count','declared_vehicle']:
            self.assertEqual(a[k],b[k]); self.assertEqual(type(a[k]),type(b[k]))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Repository(Path(self.tmp.name)/'data'); self.urls=[]
    def tearDown(self): self.store.close(); self.tmp.cleanup()

    def transport(self,fail_home=False):
        urls=self.urls
        class Fake:
            def __init__(self,store,run,config,cancelled): self.store,self.run,self.config,self.used=store,run,config,0
            def get(self,url,validator=None):
                if self.used>=self.config.max_requests: raise IngestionError('request_budget_exhausted')
                self.used+=1; urls.append(url)
                if '/getdetailusertpl/' in url: text=CARD
                elif 'getclicksandreplys' in url:
                    text=json.dumps({'result':[dict(topicid=123,views=10,replys=0),dict(topicid=124,views=20,replys=1)]})
                elif 'pageindex=1' in url:
                    text=list_html('123','2026/10/20 09:00:00')+list_html('124','2026/10/20 08:00:00')
                elif 'pageindex=' in url: text=list_html('1','2026/10/17 00:00:00')
                elif 'i.autohome.com.cn' in url:
                    if fail_home: raise IngestionError('http_error')
                    text=USER_HTML
                else: text=POST_HTML
                task=self.store.task(self.run,'http',url)
                rid=self.store.response(task,text.encode(),dict(url=url,http_status=200),'2026-10-21T00:00:00+00:00','http_body')
                return dict(task_id=task,response_id=rid,text=text,body=text.encode(),retrieved_at='2026-10-21T00:00:00+00:00',parsed=validator(text) if validator else None)
        return Fake

    def test_two_posts_one_card_sql_and_offline_replay(self):
        cfg=JobConfig.parse(dict(mode='collect',allow_network=True,max_requests=20,start='2026-10-18',max_pages=2))
        result=run_collection(self.store,cfg,transport_factory=self.transport())
        self.assertEqual(sum('/getdetailusertpl/' in u for u in self.urls),1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],2)
        for row in self.store.db.execute('SELECT author_context_json FROM posts'):
            context=json.loads(row[0]); self.assertEqual(context['popular_post_count'],0)
            self.assertEqual(context['declared_vehicle'],'小米SU7')
            self.assertIsNotNone(self.store.db.execute('SELECT 1 FROM source_snapshots WHERE snapshot_id=?',(context['source_snapshot_id'],)).fetchone())
        self.assertEqual(self.store.db.execute('SELECT platform_post_count,popular_post_count,platform_reply_count FROM users').fetchone()[:],(3,0,1))
        before=self.store.logical_export()
        for rid, in self.store.db.execute('SELECT snapshot_id FROM source_snapshots').fetchall(): replay(self.store,rid)
        self.assertEqual(before,self.store.logical_export())
        self.assertTrue(result['counts']['checkpoint_advanced'])

    def test_home_failure_preserves_card_and_post_fields(self):
        cfg=JobConfig.parse(dict(mode='collect',kind='users',allow_network=True,max_requests=5))
        result=run_collection(self.store,cfg,user_ids=['42'],transport_factory=self.transport(fail_home=True))
        row=self.store.db.execute('SELECT platform_post_count,popular_post_count,platform_reply_count,declared_vehicle FROM users').fetchone()
        self.assertEqual(tuple(row),(3,0,1,'小米SU7'))
        self.assertEqual(result['status'],'partial'); self.assertFalse(result['publishable'])
        self.assertGreater(self.store.verify()['counts']['collection_failures'],0)

    def test_http_job_to_sql_uses_same_projection(self):
        fake=self.transport()
        def run(store,cfg,**kwargs): return run_collection(store,cfg,transport_factory=fake,**kwargs)
        service=JobService(self.store,allow_network=True)
        server=make_server(service,port=0,token='test')
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with patch('autoinsight_ingestion.jobs.run_collection',side_effect=run):
                client=http.client.HTTPConnection('127.0.0.1',server.server_port)
                payload=dict(config=dict(mode='collect',kind='users',allow_network=True,max_requests=5),user_ids=['42'])
                client.request('POST','/v1/ingestion/jobs',json.dumps(payload),{'Authorization':'Bearer test','Content-Type':'application/json','Idempotency-Key':'author-test'})
                response=client.getresponse(); data=json.loads(response.read()); client.close()
                self.assertEqual(response.status,202); service.queue.join()
                self.assertEqual(service.status(data['job_id'])['state'],'succeeded')
                self.assertEqual(tuple(self.store.db.execute('SELECT platform_post_count,popular_post_count,platform_reply_count FROM users').fetchone()),(3,0,1))
        finally:
            server.shutdown(); server.server_close(); thread.join(); service.close()
