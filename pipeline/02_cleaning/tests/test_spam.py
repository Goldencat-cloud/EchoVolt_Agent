# -*- coding: utf-8 -*-
"""spam 单测：对应 spec「水军与广告识别」。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from corpus_cleaning.spam import compute_spam, reasons_to_json  # noqa: E402


def _row(pid, aid, key, published="2026-09-01", reg="2024-01-01", cnt=100, excluded=""):
    return {"post_id": pid, "author_id": aid, "norm_key": key, "excluded": excluded,
            "published_at": published, "registered_at_raw": reg, "platform_post_count": cnt}


class TestKeyFilter(unittest.TestCase):
    def test_short_key_not_template(self):
        rows = [_row("p1", "A", "小米su7"), _row("p2", "B", "小米su7")]
        self.assertEqual(compute_spam(rows), {})  # 长度<8 的常见短句不算协同模板

    def test_excluded_row_not_template(self):
        key = "一段足够长的重复模板文本内容"
        rows = [_row("p1", "A", key, excluded="system_junk"), _row("p2", "B", key)]
        self.assertNotIn("p1", compute_spam(rows))
        self.assertNotIn("p2", compute_spam(rows))  # 任一行为已剔除 → 整组不算


class TestSpam(unittest.TestCase):
    def test_same_author_repeat(self):
        rows = [_row(f"p{i}", "A", "same text") for i in range(3)] + [_row("q1", "B", "normal")]
        out = compute_spam(rows)
        for i in range(3):
            self.assertEqual(out[f"p{i}"]["spam_suspect"], 1)
            self.assertIn("r1_same_author_repeat", out[f"p{i}"]["spam_reasons"])
        self.assertNotIn("q1", out)

    def test_same_author_two_posts_not_spam(self):
        out = compute_spam([_row("p1", "A", "k"), _row("p2", "A", "k")])
        self.assertEqual(out.get("p1", {}).get("spam_suspect", 0), 0)

    def test_cross_author_same_key(self):
        rows = [_row("p1", "A", "template"), _row("p2", "B", "template")]
        out = compute_spam(rows)
        for pid in ("p1", "p2"):
            self.assertEqual(out[pid]["spam_suspect"], 1)
            self.assertIn("r2_cross_author_key", out[pid]["spam_reasons"])
            self.assertEqual(out[pid]["spam_reasons"]["r2_cross_author_key"]["post_ids"], ["p1", "p2"])

    def test_new_account_burst(self):
        rows = [_row("p1", "A", "k1", published="2026-09-10", reg="2026-09-01", cnt=3)]
        out = compute_spam(rows)
        self.assertEqual(out["p1"]["spam_suspect"], 1)
        r = out["p1"]["spam_reasons"]["r3_new_account_burst"]
        self.assertEqual(r["gap_days"], 9)

    def test_old_account_not_burst(self):
        rows = [_row("p1", "A", "k1", published="2026-09-01", reg="2024-01-01", cnt=3)]
        self.assertNotIn("p1", compute_spam(rows))

    def test_missing_fields_skip(self):
        rows = [{"post_id": "p1", "author_id": "A", "norm_key": "k",
                 "published_at": None, "registered_at_raw": None, "platform_post_count": None}]
        self.assertNotIn("p1", compute_spam(rows))

    def test_reasons_json_serializable(self):
        out = compute_spam([_row("p1", "A", "template"), _row("p2", "B", "template")])
        self.assertIsInstance(json.loads(reasons_to_json(out["p1"]["spam_reasons"])), dict)


if __name__ == "__main__":
    unittest.main()
