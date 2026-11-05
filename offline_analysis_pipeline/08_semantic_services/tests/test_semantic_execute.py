"""执行层：用手搭的小库跑通"口径 → SQL → 行"的完整链路。

用例不依赖真实快照，因此断言的是行为（成员、排除值、空值标签、薄样本、陈旧产物），
而不是某一版数据的规模。
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.compile import QueryError  # noqa: E402
from semantic.execute import execute, execute_saved  # noqa: E402
from semantic.model import load_model  # noqa: E402
from semantic.spec import QuerySpec  # noqa: E402
from tests.semantic_fixture import build_fixture  # noqa: E402


class ExecuteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="semantic-exec-"))
        cls.db_path = cls.tmpdir / "semantic.db"
        build_fixture(cls.db_path, cls.model)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def run_query(self, **kwargs):
        return execute(QuerySpec(**kwargs), model=self.model, db_path=self.db_path)

    def test_counts_follow_the_declared_population(self) -> None:
        result = self.run_query(metrics=("claims",))
        self.assertEqual(result["rows"], [{"claims": 6}])
        self.assertEqual(result["population"], "experience")

    def test_excluded_values_drop_out_and_nulls_get_their_label(self) -> None:
        result = self.run_query(metrics=("claims",), dimensions=("aspect",),
                                order=({"field": "claims", "dir": "desc"},))
        counts = {row["aspect"]: row["claims"] for row in result["rows"]}
        self.assertNotIn("政策与市场", counts)
        self.assertEqual(counts["未标注"], 1)
        self.assertEqual(counts["外观与内饰"], 2)

    def test_ratio_is_computed_in_one_pass(self) -> None:
        # 负面 3 条 / 体验口径 6 条，两个计数在同一次聚合里完成。
        result = self.run_query(metrics=("negativeShare", "negative", "claims"))
        row = result["rows"][0]
        self.assertEqual((row["negative"], row["claims"]), (3, 6))
        self.assertAlmostEqual(row["negativeShare"], 3 / 6)

    def test_post_metric_deduplicates_within_the_population(self) -> None:
        result = self.run_query(metrics=("posts",))
        self.assertEqual(result["rows"], [{"posts": 2}])

    def test_dimension_lives_on_the_joined_post(self) -> None:
        result = self.run_query(metrics=("claims",), dimensions=("ownership",))
        counts = {row["ownership"]: row["claims"] for row in result["rows"]}
        self.assertEqual(counts, {"当前拥有": 3, "明确未拥有": 3})

    def test_multi_attribution_counts_each_product_once(self) -> None:
        """一条观点提到 2 个车型时，两个车型各记 1 次；不能加回观点数。"""
        result = self.run_query(metrics=("productClaims",), dimensions=("product",))
        counts = {row["product"]: row["productClaims"] for row in result["rows"]}
        self.assertEqual(counts, {"prodA": 4, "prodB": 1})
        # 观点数仍是 6：多归属表比观点行多，两级不在同一个查询里混用。
        self.assertEqual(self.run_query(metrics=("claims",))["rows"], [{"claims": 6}])

    def test_multi_attribution_posts_are_deduplicated(self) -> None:
        result = self.run_query(metrics=("productPosts",), dimensions=("product",))
        counts = {row["product"]: row["productPosts"] for row in result["rows"]}
        self.assertEqual(counts, {"prodA": 2, "prodB": 1})

    def test_product_label_comes_from_the_product_tree(self) -> None:
        result = self.run_query(metrics=("productClaims",),
                                dimensions=("product", "product_label"))
        self.assertTrue(all(row["product_label"] for row in result["rows"]))

    def test_thin_groups_are_flagged_not_deleted(self) -> None:
        result = self.run_query(metrics=("claims",), dimensions=("aspect",))
        flagged = {entry["row"] for entry in result["coverage"]["thin_buckets"]}
        self.assertTrue(flagged)
        self.assertEqual(len(result["rows"]), 4)

    def test_empty_result_is_an_empty_set_not_an_error(self) -> None:
        result = self.run_query(metrics=("claims",), dimensions=("aspect",),
                                filters={"aspect": "不存在的议题"})
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["row_count"], 0)

    def test_envelope_carries_caliber_and_version(self) -> None:
        result = self.run_query(metrics=("claims",))
        self.assertEqual(len(result["query_id"]), 16)
        self.assertEqual(result["model_version"], self.model.model_version)
        self.assertIn("口径 experience", result["metrics"][0]["caliber"])

    def test_saved_query_expands_params(self) -> None:
        result = execute_saved("curated_sentiment_mix", {"aspect": "充电与补能"},
                               model=self.model, db_path=self.db_path)
        self.assertEqual(result["rows"], [{"sentiment": "负面", "curatedClaims": 1}])

    def test_saved_query_requires_its_param(self) -> None:
        with self.assertRaises(QueryError) as caught:
            execute_saved("curated_sentiment_mix", {}, model=self.model, db_path=self.db_path)
        self.assertEqual(caught.exception.code, "MISSING_PARAM")

    def test_stale_artifact_is_refused(self) -> None:
        stale = self.tmpdir / "stale.db"
        shutil.copy(self.db_path, stale)
        con = sqlite3.connect(stale)
        try:
            con.execute("UPDATE meta SET value = '1999-01-01.0' WHERE key = 'model_version'")
            con.commit()
        finally:
            con.close()
        with self.assertRaises(QueryError) as caught:
            execute(QuerySpec(metrics=("claims",)), model=self.model, db_path=stale)
        self.assertEqual(caught.exception.code, "STALE_ARTIFACT")


if __name__ == "__main__":
    unittest.main()
