# -*- coding: utf-8 -*-
"""annotate 单测：对应 spec「删除帖与空行剔除」「review_required 定级」「系统废串与纯符号」
「文本去重」「车主分群」。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from corpus_cleaning.annotate import (  # noqa: E402
    classify_advertising,
    classify_excluded,
    dedup,
    has_media,
    parse_segments,
)

SEG_IMG = parse_segments('[{"kind":"image","value":"https://x/a.jpg"}]')
SEG_TEXT = parse_segments('[{"kind":"text","value":"你好"}]')


class TestExcluded(unittest.TestCase):
    def test_post_deleted(self):
        ex, _ = classify_excluded("本楼已被删除 或者内容不存在", "本楼已被删除 或者内容不存在", "", False)
        self.assertEqual(ex, "post_deleted")

    def test_pure_media_kept(self):
        ex, _ = classify_excluded("", "", "", has_media(SEG_IMG))
        self.assertEqual(ex, "")  # 纯图帖保留，polished_text 为空

    def test_empty_no_media(self):
        ex, _ = classify_excluded("", "", "", False)
        self.assertEqual(ex, "empty_no_media")

    def test_system_junk(self):
        ex, _ = classify_excluded("点击展开查看详情", "点击展开查看详情", "", False)
        self.assertEqual(ex, "system_junk")

    def test_gibberish_symbols(self):
        ex, _ = classify_excluded("***。·，", "***。·，", "", False)
        self.assertEqual(ex, "gibberish")

    def test_pure_emoji_not_gibberish(self):
        ex, _ = classify_excluded("🚗👍", "🚗👍", "", False)
        self.assertEqual(ex, "")  # 空/纯 emoji 不标 gibberish

    def test_expressive_punct_not_gibberish(self):
        ex, _ = classify_excluded("？！……", "？！……", "", False)
        self.assertEqual(ex, "")

    def test_no_post_removed_category(self):
        # Owner 指示：不做疑似删除标注；删除标记文本仍按 post_deleted
        ex, _ = classify_excluded("内容没了，疑似被删", "内容没了，疑似被删", "", False)
        self.assertEqual(ex, "")


class TestAdvertising(unittest.TestCase):
    def test_combo_hits(self):
        hit, reasons = classify_advertising("低价出售，加微信 che12345 详谈")
        self.assertTrue(hit)
        self.assertIn("contact_pattern", reasons)
        self.assertIn("promo_keyword", reasons)

    def test_promo_alone_not_hit(self):
        hit, _ = classify_advertising("这车广告打得好，优惠力度大")
        self.assertFalse(hit)

    def test_contact_alone_not_hit(self):
        hit, _ = classify_advertising("加微信 su7owner01 交流")
        self.assertFalse(hit)

    def test_url_stack_auxiliary_only(self):
        hit, reasons = classify_advertising("看这里 https://a.cn/1 https://a.cn/2 https://a.cn/3")
        self.assertFalse(hit)  # 外链堆叠单独不构成 advertising
        self.assertIn("url_stack", reasons)


class TestDedup(unittest.TestCase):
    def test_norm_merge_and_first_kept(self):
        from corpus_cleaning.polish import norm_key
        raw = ["su7 顶", "ＳＵ７ 顶", "SU7 顶", "别的"]
        rows = [(f"p{i}", norm_key(k)) for i, k in enumerate(raw, 1)]
        group_by, dup_by, gid = dedup(rows)
        self.assertEqual(dup_by, {"p1": False, "p2": True, "p3": True, "p4": False})
        self.assertEqual(group_by["p1"], group_by["p2"] == group_by["p3"] and group_by["p1"])
        self.assertEqual(gid, 2)

    def test_empty_key_not_grouped(self):
        group_by, dup_by, _ = dedup([("p1", ""), ("p2", "")])
        self.assertEqual((group_by["p1"], group_by["p2"]), (0, 0))
        self.assertFalse(any(dup_by.values()))


class TestParseSegments(unittest.TestCase):
    def test_kinds(self):
        segs = parse_segments('[{"kind":"text","value":"a"},{"kind":"image","value":"u"}]')
        self.assertEqual(has_media(segs), True)

    def test_invalid(self):
        self.assertEqual(parse_segments("broken"), [])


if __name__ == "__main__":
    unittest.main()
