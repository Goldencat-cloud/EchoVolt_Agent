import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.api import make_server
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.collect.runner import run_collection
from autoinsight_ingestion.contracts import IngestionError, JobConfig
from autoinsight_ingestion.jobs import JobService
from autoinsight_ingestion.normalize.legacy import product_json
from autoinsight_ingestion.normalize.pages import forum_list, post_page, user_page
from autoinsight_ingestion.storage import Repository
from test_foundation import csv_bytes, post

POST_HTML = '''<h1>空间体验</h1><a rel="author" href="https://i.autohome.com.cn/42/home.html">楼主</a>
<time itemprop="datePublished" datetime="2026-10-20T09:00:00+08:00"></time>
<div class="post-container"><div class="tz-paragraph">甲</div><img data-src="/a.webp">
<blockquote>引用不计</blockquote><div class="signature">签名不计</div>
<div class="tz-paragraph">乙</div><div data-vid="A60XYZ"></div></div>
<div class="reply">回复不计<img src="/avatar.jpg"></div>'''
USER_HTML = '''<link rel="canonical" href="https://i.autohome.com.cn/42/home.html"><h1>昵称</h1>
<input id="hdsex" value="2"><a href="/42/followers">粉丝<span>123</span></a>
<a href="/42/following">关注<span>0</span></a><span>IP属地：上海</span>'''


def list_html(tid, date):
    return f'<li data-topicid="{tid}"><a href="/bbs/thread/abc/{tid}-1.html">标题</a><span class="athm-card-unit-information__item">{date}</span></li>'


class PageTests(unittest.TestCase):
    def test_all_segments_and_owner_boundary(self):
        r = post_page(POST_HTML, "123", "https://club.autohome.com.cn/bbs/thread/abc/123-1.html", "2026-10-21T00:00:00+00:00")
        self.assertEqual([s["kind"] for s in r.data["segments"]], ["text", "image", "text", "video"])
        self.assertEqual(r.data["text_content"], "甲\n乙")
        self.assertEqual(r.data["user_id"], "42")
        self.assertEqual(r.quality_state, "ready")

    def test_ambiguous_body_rejected(self):
        with self.assertRaises(IngestionError):
            post_page(POST_HTML + '<div class="post-container">另一楼</div>', "123", "https://club.autohome.com.cn", None)

    def test_no_longest_paragraph_fallback(self):
        with self.assertRaises(IngestionError):
            post_page("<p>很长的页面内容但不能证明是楼主</p>", "123", "https://club.autohome.com.cn", None)

    def test_list_parse(self):
        self.assertEqual(forum_list(list_html("123", "2026/10/20 09:00:00"))[0]["post_id"], "123")

    def test_empty_list_not_terminal(self):
        with self.assertRaises(IngestionError):
            forum_list("<html>网站新模板</html>")

    def test_blocked(self):
        with self.assertRaises(IngestionError):
            forum_list("用户访问安全认证")

    def test_user_identity_and_explicit_fields(self):
        r = user_page(USER_HTML, "42", "2026-10-21T00:00:00+00:00")
        self.assertEqual(r.data["sex_explicit"], "女")
        self.assertEqual(r.data["followers"], 123)
        self.assertEqual(r.data["following"], 0)

    def test_wrong_user_not_ok(self):
        with self.assertRaises(IngestionError):
            user_page(USER_HTML, "43", "2026-10-21T00:00:00+00:00")

    def test_product_title_ids_response_local(self):
        def sample(name, itemid):
            return json.dumps({"returncode": 0, "result": {"titlelist": [{"groupname": "参数", "itemtype": "车身", "items": [{"titleid": 1, "itemid": itemid, "itemname": name}]}], "datalist": [{"specid": 1, "specname": "2024款标准版", "paramconflist": [{"titleid": 1, "itemname": "100"}]}]}}).encode()
        a = list(product_json(sample("尺寸", 1), "6962"))[0]
        b = list(product_json(sample("质量", 2), "6962"))[0]
        self.assertNotEqual(a.data["parameters"][0]["source_item_key"], b.data["parameters"][0]["source_item_key"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Repository(Path(self.tmp.name) / "data")

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_time_filter_does_not_stop_at_newer_page(self):
        urls = []
        class Fake:
            def __init__(self, store, run, config, cancelled):
                self.store, self.run, self.config = store, run, config
                self.used = 0
            def get(self, url, validator=None):
                urls.append(url); self.used += 1
                if "pageindex=1" in url:
                    text = list_html("100", "2026/10/22 09:00:00")
                elif "pageindex=2" in url:
                    text = list_html("123", "2026/10/20 09:00:00")
                elif "/42/" in url:
                    text = USER_HTML
                elif 'getclicksandreplys' in url:
                    text = json.dumps({'result':[{'topicid':123,'views':1,'replys':0}]})
                else:
                    text = POST_HTML
                task = self.store.task(self.run, "http", url)
                body = text.encode()
                response = self.store.response(task, body, {"url": url, "http_status": 200}, "2026-10-21T00:00:00+00:00", "http_body")
                return {"task_id": task, "response_id": response, "body": body, "text": text, "retrieved_at": "2026-10-21T00:00:00+00:00"}
            def fail(self, task, code):
                raise AssertionError(code)
        config = JobConfig.parse({"mode": "collect", "kind": "posts", "allow_network": True, "max_requests": 8,
                                  "max_pages": 2, "start": "2026-10-19", "end": "2026-10-21"})
        result = run_collection(self.store, config, transport_factory=Fake)
        self.assertEqual(self.store.verify()["counts"]["posts"], 1)
        self.assertTrue(any("pageindex=2" in u for u in urls))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["coverage_status"], "partial")

    def test_network_host_allowlist(self):
        run = self.store.begin_run({})
        transport = Transport(self.store, run, JobConfig())
        with self.assertRaises(IngestionError):
            transport.get("https://example.com/")
        self.assertEqual(transport.used, 0)

    def test_resume_does_not_reuse_old_page(self):
        url = "https://i.autohome.com.cn/42/home.html"
        previous = self.store.begin_run({})
        task = self.store.task(previous, "http", url)
        self.store.response(task, USER_HTML.encode(), {"url": url, "http_status": 200}, "2026-10-21T00:00:00+00:00", "http_body")
        run = self.store.begin_run({})
        config = JobConfig.parse({"mode": "collect", "allow_network": True, "max_requests": 1})
        transport = Transport(self.store, run, config); transport.resume_from = previous
        from unittest.mock import MagicMock
        response=MagicMock(); response.__enter__.return_value=response
        response.status=200; response.read.return_value=USER_HTML.encode()
        with patch.object(transport.opener, "open", return_value=response):
            result = transport.get(url)
        self.assertEqual(transport.used, 1)
        self.assertNotEqual(result["retrieved_at"], "2026-10-21T00:00:00+00:00")

    def test_budget_blocks_retry(self):
        config = JobConfig.parse({"mode": "collect", "allow_network": True, "max_requests": 1, "max_attempts": 2})
        transport = Transport(self.store, self.store.begin_run({}), config)
        import urllib.error
        with patch.object(transport.opener, "open", side_effect=urllib.error.URLError("test")), patch("autoinsight_ingestion.collect.http.time.sleep"):
            with self.assertRaises(IngestionError):
                transport.get("https://i.autohome.com.cn/42/home.html")
        self.assertEqual(transport.used, 1)
        self.assertEqual(self.store.db.execute("SELECT json_array_length(attempts_json) FROM collection_runs WHERE run_id=?",(transport.run_id,)).fetchone()[0], 1)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        source = self.path / "source.csv"; source.write_bytes(csv_bytes([post()]))
        self.store = Repository(self.path / "data")
        self.service = JobService(self.store, {"fixture": {"path": str(source), "kind": "posts"}})
        self.server = make_server(self.service, port=0, token="test-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.service.close(); self.store.close(); self.tmp.cleanup()

    def request(self, method, path, body=None, key="test", auth=True, origin=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json", "Idempotency-Key": key}
        if auth:
            headers["Authorization"] = "Bearer test-token"
        if origin:
            headers["Origin"] = origin
        client.request(method, path, json.dumps(body) if body is not None else "", headers)
        response = client.getresponse(); result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_create_poll_and_repeat(self):
        status, result = self.request("POST", "/v1/ingestion/jobs", {"source": "fixture"})
        self.assertEqual(status, 202)
        self.service.queue.join()
        status, result = self.request("GET", "/v1/ingestion/jobs/" + result["job_id"])
        self.assertEqual(status, 200); self.assertEqual(result["state"], "partial")
        self.assertFalse(result['result']['publishable'])
        _, duplicate = self.request("POST", "/v1/ingestion/jobs", {"source": "fixture"})
        self.assertEqual(result["job_id"], duplicate["job_id"])
        self.assertNotIn(str(self.path), json.dumps(result))

    def test_unknown_job(self):
        self.assertEqual(self.request("GET", "/v1/ingestion/jobs/" + "0" * 32)[0], 404)

    def test_no_arbitrary_file_or_url(self):
        for body in [{"path": "C:/secret"}, {"url": "https://example.com"}, {"source": "unknown"}]:
            self.assertEqual(self.request("POST", "/v1/ingestion/jobs", body)[0], 400)

    def test_network_requires_server_optin(self):
        body = {"config": {"mode": "collect", "max_requests": 1, "allow_network": True}}
        self.assertEqual(self.request("POST", "/v1/ingestion/jobs", body)[0], 400)

    def test_idempotency_key_conflict(self):
        self.request("POST", "/v1/ingestion/jobs", {"source": "fixture"})
        self.assertEqual(self.request("POST", "/v1/ingestion/jobs", {"source": "fixture", "config": {"max_pages": 2}})[0], 409)

    def test_auth_and_browser_rejected(self):
        self.assertEqual(self.request("GET", "/v1/ingestion/jobs/" + "0" * 32, auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/v1/ingestion/jobs/" + "0" * 32, origin="https://example.com")[0], 403)

    def test_cancel_running_and_resume(self):
        entered, release = threading.Event(), threading.Event()
        from autoinsight_ingestion.jobs import read_input as actual
        def blocked(*args):
            entered.set(); release.wait(3); return actual(*args)
        with patch("autoinsight_ingestion.jobs.read_input", side_effect=blocked):
            _, result = self.request("POST", "/v1/ingestion/jobs", {"source": "fixture"})
            entered.wait(3)
            route = "/v1/ingestion/jobs/" + result["job_id"]
            self.assertEqual(self.request("POST", route + "/cancel")[0], 202)
            release.set(); self.service.queue.join()
        self.assertEqual(self.request("GET", route)[1]["state"], "cancelled")
        self.assertEqual(self.request("POST", route + "/resume")[0], 202)
        self.service.queue.join()
        self.assertEqual(self.request("GET", route)[1]["state"], "partial")


if __name__ == "__main__":
    unittest.main()
