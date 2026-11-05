"""Runtime credential injection and bounded redirect handling; no cookie value may persist."""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.collect.credentials import cookie_header, load_cookies
from autoinsight_ingestion.collect.http import Transport
from autoinsight_ingestion.collect.runner import run_collection
from autoinsight_ingestion.contracts import IngestionError, JobConfig
from autoinsight_ingestion.storage import Repository

STORAGE = {
    "cookies": [
        {"name": "sessionid", "value": "S1", "domain": ".autohome.com.cn", "path": "/", "expires": 4102444800, "httpOnly": False, "secure": False},
        {"name": "stale", "value": "X", "domain": ".autohome.com.cn", "path": "/", "expires": 1000000000, "httpOnly": False, "secure": False},
        {"name": "sessionvid", "value": "V", "domain": ".autohome.com.cn", "path": "/", "expires": -1, "httpOnly": False, "secure": False},
        {"name": "clubonly", "value": "C", "domain": "club.autohome.com.cn", "path": "/", "expires": 4102444800, "httpOnly": False, "secure": False},
        {"name": "foreign", "value": "F", "domain": "example.com", "path": "/", "expires": 4102444800, "httpOnly": False, "secure": False},
    ],
    "origins": [],
}


class CredentialUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "auth.json")
        Path(self.path).write_text(json.dumps(STORAGE), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_header_domain_scoping(self):
        cookies = load_cookies(self.path)
        self.assertEqual(len(cookies), 5)
        header = cookie_header(cookies, "club.autohome.com.cn", at_time=1800000000)
        self.assertIn("sessionid=S1", header)
        self.assertIn("clubonly=C", header)
        self.assertIn("sessionvid=V", header)
        self.assertNotIn("stale=", header)
        self.assertNotIn("foreign", header)
        self.assertIsNone(cookie_header(cookies, "other.org", at_time=1800000000))
        self.assertIsNone(cookie_header(cookies, "autohome.com.cn.evil.io", at_time=1800000000))

    def test_all_expired_yields_no_header(self):
        expired = [{"name": "a", "value": "b", "domain": ".autohome.com.cn", "path": "/", "expires": 1000000000}]
        self.assertIsNone(cookie_header(expired, "i.autohome.com.cn", at_time=1800000000))

    def test_missing_file(self):
        with self.assertRaises(IngestionError) as ctx:
            load_cookies(str(Path(self.tmp.name) / "nope.json"))
        self.assertEqual(ctx.exception.code, "credential_file_missing")

    def test_invalid_format(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(IngestionError) as ctx:
            load_cookies(str(bad))
        self.assertEqual(ctx.exception.code, "credential_file_invalid")
        bad2 = Path(self.tmp.name) / "bad2.json"
        bad2.write_text('{"origins": []}', encoding="utf-8")
        with self.assertRaises(IngestionError) as ctx2:
            load_cookies(str(bad2))
        self.assertEqual(ctx2.exception.code, "credential_file_invalid")


class TransportCredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Repository(Path(self.tmp.name) / "data")
        self.path = str(Path(self.tmp.name) / "auth.json")
        Path(self.path).write_text(json.dumps(STORAGE), encoding="utf-8")
        self.config = JobConfig.parse({"mode": "collect", "allow_network": True, "max_requests": 5, "max_attempts": 1})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def transport(self):
        return Transport(self.store, self.store.begin_run({}), self.config)

    @staticmethod
    def ok_response(body=b"<html>ok</html>"):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = body
        response.headers = {}
        return response

    @staticmethod
    def redirect(target, url="https://i.autohome.com.cn/12/home.html"):
        return urllib.error.HTTPError(url, 301, "Moved Permanently", {"Location": target}, io.BytesIO(b""))

    def test_attach_missing_file_rejected_and_disabled(self):
        transport = self.transport()
        with self.assertRaises(IngestionError) as ctx:
            transport.attach_credentials(str(Path(self.tmp.name) / "nope.json"))
        self.assertEqual(ctx.exception.code, "credential_file_missing")
        self.assertIsNone(transport.credential_path)

    def test_cookie_sent_and_persisted_state_scrubbed(self):
        transport = self.transport()
        transport.attach_credentials(self.path)
        seen = {}

        def side(req, timeout):
            seen["cookie"] = req.headers.get("Cookie")
            return self.ok_response()

        with patch.object(transport.opener, "open", side_effect=side):
            transport.get("https://i.autohome.com.cn/42/home.html")
        self.assertIn("sessionid=S1", seen["cookie"])
        meta = json.loads(self.store.db.execute("SELECT provenance_json FROM source_snapshots").fetchone()[0])
        self.assertEqual(meta["credentials"], "provided")
        self.assertNotIn("S1", json.dumps(meta))

    def test_absent_state_recorded_without_credentials(self):
        transport = self.transport()
        with patch.object(transport.opener, "open", return_value=self.ok_response()):
            transport.get("https://i.autohome.com.cn/42/home.html")
        meta = json.loads(self.store.db.execute("SELECT provenance_json FROM source_snapshots").fetchone()[0])
        self.assertEqual(meta["credentials"], "absent")

    def test_redirect_followed_once_within_allowlist(self):
        transport = self.transport()
        transport.attach_credentials(self.path)
        cookies_sent = []

        def side(req, timeout):
            cookies_sent.append(req.headers.get("Cookie"))
            if "home.html" in req.full_url:
                raise self.redirect("https://club.autohome.com.cn/frontnc/user/home/12")
            return self.ok_response(b"<html>profile</html>")

        with patch.object(transport.opener, "open", side_effect=side):
            result = transport.get("https://i.autohome.com.cn/12/home.html")
        self.assertEqual(transport.used, 2)
        self.assertEqual(result["text"], "<html>profile</html>")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0], 2)
        metas = [json.loads(r[0]) for r in self.store.db.execute("SELECT provenance_json FROM source_snapshots")]
        redirected = [m for m in metas if m.get("redirect_target")]
        self.assertEqual(len(redirected), 1)
        self.assertEqual(redirected[0]["http_status"], 301)
        self.assertEqual(redirected[0]["credentials"], "provided")
        self.assertIn("sessionid=S1", cookies_sent[0])
        self.assertNotIn("clubonly", cookies_sent[0])
        self.assertIn("clubonly=C", cookies_sent[1])

    def test_redirect_outside_allowlist_rejected(self):
        transport = self.transport()
        with patch.object(transport.opener, "open", side_effect=lambda req, timeout: self.redirect("https://example.com/x")):
            with self.assertRaises(IngestionError) as ctx:
                transport.get("https://i.autohome.com.cn/12/home.html")
        self.assertEqual(ctx.exception.code, "redirect_rejected")
        self.assertGreater(self.store.db.execute("SELECT COUNT(*) FROM collection_failures WHERE error_code='redirect_rejected'").fetchone()[0], 0)

    def test_second_redirect_rejected(self):
        transport = self.transport()

        def always_redirect(req, timeout):
            raise self.redirect("https://club.autohome.com.cn/b", url=req.full_url)

        with patch.object(transport.opener, "open", side_effect=always_redirect):
            with self.assertRaises(IngestionError) as ctx:
                transport.get("https://i.autohome.com.cn/12/home.html")
        self.assertEqual(ctx.exception.code, "redirect_rejected")
        self.assertEqual(transport.used, 2)

    def test_run_config_records_credential_state(self):
        config = JobConfig.parse({"mode": "collect", "kind": "users", "allow_network": True, "max_requests": 5})

        class Fake:
            def __init__(self, store, run, cfg, cancelled):
                self.used = 0

            def get(self, url, validator=None):
                raise IngestionError("cancelled")

        result = run_collection(self.store, config, user_ids=["42"], transport_factory=Fake, credential_path=self.path)
        self.assertEqual(result["status"], "interrupted")
        run_config = json.loads(self.store.db.execute("SELECT config_json FROM collection_runs").fetchone()[0])
        self.assertEqual(run_config.get("credentials"), "provided")
        self.assertNotIn(str(self.tmp.name), json.dumps(run_config))
        self.assertNotIn("auth.json", json.dumps(run_config))


if __name__ == "__main__":
    unittest.main()
