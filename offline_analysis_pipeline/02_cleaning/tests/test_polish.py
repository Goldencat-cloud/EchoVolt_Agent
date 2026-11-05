# -*- coding: utf-8 -*-
"""polish 单测：对应 spec「深度净化 polished_text」「隐私脱敏」「多模态平行清洗」。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from corpus_cleaning.polish import norm_key, polish_multimodal, polish_text  # noqa: E402


class TestNormKey(unittest.TestCase):
    def test_nfkc_lower_space(self):
        self.assertEqual(norm_key("ＳＵ７  Max\t\n 顶"), "su7 max 顶")

    def test_empty(self):
        self.assertEqual(norm_key("   "), "")


class TestPolishText(unittest.TestCase):
    def test_symbol_strip(self):
        s = "关注@车友001 讨论 #提车日记# 详见 https://x.com/a?b=1 与 www.autohome.com.cn"
        out = polish_text(s)
        self.assertNotIn("@", out)
        self.assertNotIn("#", out)
        self.assertNotIn("http", out)
        self.assertIn("关注", out)

    def test_fullwidth_punct_kept(self):
        self.assertIn("，！？", polish_text("好，！？的"))

    def test_fullwidth_digit_normalized(self):
        self.assertEqual(polish_text("价格２２万"), "价格22万")

    def test_html_entity(self):
        self.assertEqual(polish_text("A&amp;B&lt;C&#65;"), "A&B<CA")

    def test_emoji_removed_no_column(self):
        out = polish_text("好车🚗👍")
        self.assertEqual(out, "好车")

    def test_phone_masked(self):
        self.assertEqual(polish_text("打13812345678"), "打138****5678")

    def test_qq_masked(self):
        self.assertEqual(polish_text("加QQ：12345678"), "加QQ****")
        self.assertEqual(polish_text("开奇瑞QQ3的车"), "开奇瑞QQ3的车")  # 非QQ号不误伤

    def test_longdigit_masked(self):
        self.assertEqual(polish_text("微信号1234567xy"), "微信号****xy")

    def test_whitespace_collapsed(self):
        self.assertEqual(polish_text("  a\n\n b   c  "), "a b c")

    def test_empty(self):
        self.assertEqual(polish_text(""), "")


class TestPolishMultimodal(unittest.TestCase):
    SEGMENTS = json.dumps([
        {"kind": "text", "value": "看图１23🚗 https://img.example/1.jpg"},
        {"kind": "image", "value": "https://club2.autoimg.cn/a.jpg"},
        {"kind": "video", "value": "vid_123"},
    ], ensure_ascii=False)

    def test_text_cleaned_media_kept_in_order(self):
        out, before, after = polish_multimodal(self.SEGMENTS)
        obj = json.loads(out)
        self.assertEqual([seg["kind"] for seg in obj], ["text", "image", "video"])
        # 媒体段 URL/ID 原样保留（SHALL NOT 剥离）
        self.assertEqual(obj[1]["value"], "https://club2.autoimg.cn/a.jpg")
        self.assertEqual(obj[2]["value"], "vid_123")
        self.assertEqual(obj[0]["value"], "看图123")  # text 段同款净化，URL 剥离
        self.assertEqual((before, after), (2, 2))

    def test_invalid_json_passthrough(self):
        out, b, a = polish_multimodal("not-json")
        self.assertEqual((out, b, a), ("not-json", 0, 0))

    def test_empty(self):
        self.assertEqual(polish_multimodal("")[0], "")


if __name__ == "__main__":
    unittest.main()
