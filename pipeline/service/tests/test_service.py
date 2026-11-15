import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import service
from research import catalog as research_catalog
import json


class QueryServiceTests(unittest.TestCase):
    def test_stats_ratio_matches_claim_counts(self):
        """口径自洽：占比必须等于同行的分子/分母，帖子级计数独立。"""
        result = service.query_stats("空间与舒适性")
        row = result["data"][0]
        self.assertGreater(row["claims"], 0)
        self.assertAlmostEqual(row["negativeShare"], row["negative_claims"] / row["claims"])
        self.assertLessEqual(row["negative_posts"], row["posts"])
        if row["posts"]:
            self.assertNotAlmostEqual(row["negativeShare"], row["negative_posts"] / row["posts"])

    def test_stats_unknown_aspect_is_empty(self):
        with self.assertRaises(ValueError):
            service.query_stats("不存在的议题")

    def test_small_cohort_warns(self):
        result = service.query_stats("技术原理")
        self.assertIn("below_minimum_posts", result["warnings"])

    def test_research_brief_matches_contract(self):
        brief_path = Path(__file__).resolve().parents[1] / "research-brief.json"
        service.validate_research_brief(json.loads(brief_path.read_text(encoding="utf-8")))

    def test_research_brief_defines_metric_and_dimension_boundaries(self):
        brief_path = Path(__file__).resolve().parents[1] / "research-brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        self.assertEqual(brief["catalog_version"], research_catalog.CATALOG_VERSION)
        self.assertEqual(research_catalog.METRICS["negativeShare"]["denominator"], "该议题 claims")
        self.assertIn("子集", research_catalog.DIMENSIONS["journey"]["scope"])
        self.assertIn("不代表全量声量趋势", research_catalog.DIMENSIONS["time"]["scope"])
        self.assertNotIn("metric_definitions", brief)
        self.assertNotIn("dimension_definitions", brief)

    def test_claims_are_filtered_and_citations_present(self):
        result = service.query_claims(aspect="空间与舒适性", sentiment="负面", limit=5)
        self.assertEqual(len(result["data"]), 5)
        self.assertTrue(all(row["url"] and row["quote"] and row["claim_id"] for row in result["data"]))
        self.assertTrue(all(row["sentiment"] == "负面" for row in result["data"]))
        self.assertTrue(all("statement" in row and "comparison" in row for row in result["data"]))
        self.assertTrue(result["truncated"])

    def test_claim_ids_are_repeatable_and_scoped_to_snapshot(self):
        first = service.query_claims(aspect="空间与舒适性", limit=2)
        second = service.query_claims(aspect="空间与舒适性", limit=2)
        self.assertEqual([x["claim_id"] for x in first["data"]], [x["claim_id"] for x in second["data"]])
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])

    def test_pagination_bounds(self):
        with self.assertRaises(ValueError):
            service.query_claims(limit=21)
        with self.assertRaises(ValueError):
            service.query_claims(offset=-1)

    def test_claim_filters_validate_known_business_dimensions(self):
        for filters in ({"aspect": "不存在的方面"}, {"sentiment": "很差"},
                        {"journey": "不存在的阶段"}, {"ownership": "不存在的状态"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                service.query_claims(**filters)

    def test_health_does_not_depend_on_model(self):
        self.assertEqual(service.health()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
