"""Acceptance-defect fixes: list-time fallback for publication time; listSpec price metadata."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.normalize.legacy import product_json, product_list
from autoinsight_ingestion.normalize.pages import post_page
from autoinsight_ingestion.standard import project

POST_HTML_NO_TIME = ('<h1>空间体验</h1>'
                     '<a rel="author" href="https://i.autohome.com.cn/42/home.html">楼主</a>'
                     '<div class="post-container"><div class="tz-paragraph">甲</div>'
                     '<img data-src="/a.webp"><div class="tz-paragraph">乙</div></div>')
HINT = {"post_id": "123", "published_raw": "2026/10/21 14:07:01", "user_id": "42",
        "author_home": "https://i.autohome.com.cn/42/home.html", "response_id": "r1"}

LIST_SPEC = {"returncode": 0, "result": {"seriesname": "小米SU7", "seriesid": 6962,
    "list": [{"type": "0x000c", "name": "0.0升 320马力", "speclist": [
        {"id": 76173, "name": "2026款 后驱标准版", "price": "21.99万", "pricetips": "厂商指导价:",
         "iselectric": 1, "iswaitsell": 0}]}],
    "otherlist": [{"type": "0x0002", "name": "未售", "speclist": [
        {"id": 74430, "name": "2024款 SU7 L 猜想图", "price": "暂无报价", "iselectric": 1, "iswaitsell": 1}]}]}}

PARAM_SPEC = {"returncode": 0, "result": {"titlelist": [], "datalist": [
    {"specid": 76173, "specname": "2026款 后驱标准版", "specstatus": "在售", "paramconflist": []},
    {"specid": 74430, "specname": "2024款 SU7 L 猜想图", "specstatus": "待售", "paramconflist": []}]}}


class ListTimeFallbackTests(unittest.TestCase):
    def test_fallback_uses_list_time_with_basis(self):
        record = post_page(POST_HTML_NO_TIME, "123", "https://club.autohome.com.cn/bbs/thread/abc/123-1.html",
                           "2026-10-21T00:00:00+00:00", HINT)
        self.assertEqual(record.data["time"]["value"], "2026-10-21T14:07:01+08:00")
        self.assertEqual(record.data["time"]["basis"], "list_page_time")
        self.assertEqual(record.data["time"]["precision"], "second")
        self.assertEqual(record.data["time"]["raw"], "2026/10/21 14:07:01")

    def test_fallback_day_precision(self):
        hint = dict(HINT, published_raw="2026/10/17")
        record = post_page(POST_HTML_NO_TIME, "123", "https://club.autohome.com.cn/bbs/thread/abc/123-1.html",
                           "2026-10-21T00:00:00+00:00", hint)
        self.assertEqual(record.data["time"]["value"], "2026-10-17")
        self.assertEqual(record.data["time"]["basis"], "list_page_time")
        self.assertEqual(record.data["time"]["precision"], "day")

    def test_no_fallback_when_hint_mismatches(self):
        record = post_page(POST_HTML_NO_TIME, "123", "https://club.autohome.com.cn/bbs/thread/abc/123-1.html",
                           "2026-10-21T00:00:00+00:00", dict(HINT, post_id="999"))
        self.assertIsNone(record.data["time"]["value"])
        self.assertEqual(record.data["time"]["basis"], "unknown")

    def test_detail_time_still_wins(self):
        html = ('<h1>标题</h1><a rel="author" href="https://i.autohome.com.cn/42/home.html">楼主</a>'
                '<time itemprop="datePublished" datetime="2026-10-20T09:00:00+08:00"></time>'
                '<div class="post-container"><div class="tz-paragraph">甲</div></div>')
        record = post_page(html, "123", "https://club.autohome.com.cn/bbs/thread/abc/123-1.html",
                           "2026-10-21T00:00:00+00:00", HINT)
        self.assertEqual(record.data["time"]["basis"], "explicit")
        self.assertEqual(record.data["time"]["value"], "2026-10-20T09:00:00+08:00")


class ProductPriceTests(unittest.TestCase):
    def test_list_spec_metadata_merged_into_records(self):
        spec_meta = product_list(__import__("json").dumps(LIST_SPEC).encode("utf-8"))
        self.assertEqual(spec_meta["76173"]["list_price_raw"], "21.99万")
        self.assertEqual(spec_meta["76173"]["model_group"], "0.0升 320马力")
        self.assertEqual(spec_meta["76173"]["condition_tags"], ["electric"])
        self.assertEqual(spec_meta["74430"]["model_group"], "未售")
        self.assertIn("wait_sell", spec_meta["74430"]["condition_tags"])
        records = list(product_json(__import__("json").dumps(PARAM_SPEC).encode("utf-8"), "6962", spec_meta))
        by_id = {r.source_id: r for r in records}
        self.assertEqual(by_id["76173"].data["list_price_raw"], "21.99万")
        self.assertEqual(by_id["76173"].data["model_group"], "0.0升 320马力")
        self.assertTrue(by_id["74430"].data["is_concept"])
        table, projected = project(by_id["76173"])
        self.assertEqual(table, "product_specs")
        self.assertEqual(projected["list_price_raw"], "21.99万")
        self.assertEqual(projected["model_group"], "0.0升 320马力")
        self.assertIsNone(projected.get("dealer_price_raw"))

    def test_dealer_price_absent_not_fabricated(self):
        spec_meta = product_list(__import__("json").dumps(LIST_SPEC).encode("utf-8"))
        self.assertNotIn("dealer_price_raw", spec_meta["76173"])


class LegacyViewReplySuffixTests(unittest.TestCase):
    def test_views_replies_with_site_suffix_parsed(self):
        from test_foundation import csv_bytes, post
        row = post()
        row["浏览数"] = "4499 浏览"
        row["回帖数"] = "15 回帖"
        from autoinsight_ingestion.normalize.legacy import posts
        records = list(posts(csv_bytes([row]).replace(b"\xef\xbb\xbf", b""), "2026-10-21T00:00:00+00:00"))
        record = records[0]
        self.assertEqual(record.data["views"], 4499)
        self.assertEqual(record.data["replies"], 15)

    def test_plain_numbers_still_work(self):
        from test_foundation import csv_bytes, post
        from autoinsight_ingestion.normalize.legacy import posts
        row = post()
        row["浏览数"] = "1.2万"
        row["回帖数"] = "300"
        records = list(posts(csv_bytes([row]).replace(b"\xef\xbb\xbf", b""), "2026-10-21T00:00:00+00:00"))
        self.assertEqual(records[0].data["views"], 12000)
        self.assertEqual(records[0].data["replies"], 300)


class TagShapeUnificationTests(unittest.TestCase):
    def test_csv_tags_become_string_array(self):
        import json as jsonlib
        from test_foundation import csv_bytes, post
        from autoinsight_ingestion.normalize.legacy import posts
        from autoinsight_ingestion.standard import project
        row = post()
        row["帖子标签"] = "问题"
        row["作者帖子数"] = "186"
        record = list(posts(csv_bytes([row]).replace(b"\xef\xbb\xbf", b""), "2026-10-21T00:00:00+00:00"))[0]
        table, projected = project(record)
        self.assertEqual(table, "posts")
        self.assertEqual(jsonlib.loads(projected["tags_json"]), ["问题"])
        context = jsonlib.loads(projected["author_context_json"])
        self.assertEqual(context["platform_post_count"], 186)
        self.assertIsInstance(context["platform_post_count"], int)

    def test_empty_tags_become_empty_array_not_null(self):
        import json as jsonlib
        from test_foundation import csv_bytes, post
        from autoinsight_ingestion.normalize.legacy import posts
        from autoinsight_ingestion.standard import project
        record = list(posts(csv_bytes([post()]).replace(b"\xef\xbb\xbf", b""), "2026-10-21T00:00:00+00:00"))[0]
        table, projected = project(record)
        self.assertEqual(jsonlib.loads(projected["tags_json"]), [])

    def test_model_condition_tags_become_array(self):
        import json as jsonlib
        from autoinsight_ingestion.normalize.legacy import models
        from autoinsight_ingestion.standard import project
        content = ("\ufeffspecid,车型名称,年款,状态,配置分组,配置分类,配置项,配置值\n"
                   "67500,2026款 后驱标准版,2026,在售,车身,尺寸,长度,4997\n").encode("utf-8")
        record = list(models(content, "6962"))[0]
        self.assertEqual(record.data["condition_tags"], [])
        row2 = ("67500,2026款 后驱标准版,2026,在售,车身,尺寸,长度,4997,固定齿比 / 三厢\n").encode("utf-8")
        header = ("specid,车型名称,年款,状态,配置分组,配置分类,配置项,配置值,条件标签\n").encode("utf-8")
        record2 = list(models(header + row2, "6962"))[0]
        self.assertEqual(record2.data["condition_tags"], ["固定齿比", "三厢"])
        table, projected = project(record2)
        self.assertEqual(table, "product_specs")
        self.assertEqual(jsonlib.loads(projected["condition_tags_json"]), ["固定齿比", "三厢"])


if __name__ == "__main__":
    unittest.main()
