"""Public wording stays distinct from internal analysis keys."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import terminology


class TerminologyTests(unittest.TestCase):
    def test_metric_caliber_is_plain_and_unit_specific(self):
        text = terminology.metric_caliber()
        self.assertIn("负面观点条数 ÷ 全部观点条数", text)
        self.assertIn("帖子数是另一统计单位", text)
        for internal in ("claims", "negativeShare", "声明级", "workstream", "MCP", "SQL"):
            self.assertNotIn(internal, text)

    def test_internal_dimensions_have_public_labels(self):
        self.assertEqual(terminology.public_dimension("journey"), "用户所处阶段")
        self.assertNotIn("journey", terminology.public_dimension("journey"))

    def test_internal_phases_have_public_labels(self):
        self.assertEqual(terminology.public_phase("planning"), "梳理研究问题")
        self.assertEqual(terminology.public_phase("unknown_internal_phase"), "正在分析")


if __name__ == "__main__":
    unittest.main()
