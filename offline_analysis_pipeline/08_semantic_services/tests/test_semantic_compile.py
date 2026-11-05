"""编译契约：请求 → 计划 → SQL 的确定性，以及拒绝路径的错误码。

这些用例不连库：一旦 SQL 的形状变了（连接方向、口径成员、比率分母保护），
这里必须先红，而不是等到报告里的数字变了才发现。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.compile import QueryError, compile_query  # noqa: E402
from semantic.model import build_model, load_model  # noqa: E402
from semantic.spec import QuerySpec  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parents[1] / "semantic" / "model.yaml"


class CompileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def compile(self, **kwargs):
        return compile_query(QuerySpec(**kwargs), self.model)

    def test_claim_query_filters_by_population_membership(self) -> None:
        sql, params, plan = self.compile(metrics=("claims",), dimensions=("aspect",))
        self.assertIn("FROM semantic_population WHERE population = ?", sql)
        self.assertEqual(params[0], plan.population)
        self.assertIn('GROUP BY t0."aspect"', sql)
        self.assertEqual(plan.population, "experience")
        self.assertEqual(plan.grain, "claim")

    def test_ratio_expands_into_its_parts_with_zero_guard(self) -> None:
        sql, _params, _plan = self.compile(metrics=("negativeShare",), dimensions=("aspect",))
        self.assertIn("NULLIF", sql)
        self.assertIn('COUNT(CASE WHEN t0."sentiment" = \'负面\' THEN 1 END)', sql)
        self.assertIn("COUNT(*)", sql)

    def test_post_grain_metric_counts_distinct_posts(self) -> None:
        sql, _params, plan = self.compile(metrics=("posts",), dimensions=("journey",))
        self.assertIn('COUNT(DISTINCT t0."post_id")', sql)
        self.assertEqual(plan.grain, "post")

    def test_post_filter_is_alias_qualified(self) -> None:
        sql, _params, _plan = self.compile(metrics=("negativePosts",))
        self.assertIn('COUNT(DISTINCT CASE WHEN t0."sentiment" = \'负面\' THEN t0."post_id" END)', sql)

    def test_excluded_values_are_dropped_but_nulls_are_kept(self) -> None:
        sql, params, _plan = self.compile(metrics=("claims",), dimensions=("aspect",))
        self.assertIn('(t0."aspect" IS NULL OR t0."aspect" NOT IN (?, ?))', sql)
        self.assertIn("政策与市场", params)

    def test_dimension_on_post_joins_many_to_one(self) -> None:
        sql, _params, plan = self.compile(metrics=("claims",), dimensions=("ownership",))
        self.assertIn('LEFT JOIN "semantic_post" AS t1 ON t1."post_id" = t0."post_id"', sql)
        self.assertIn('t1."ownership_status" AS "ownership"', sql)
        self.assertEqual(len(plan.joins), 1)

    def test_filter_alias_is_normalised_before_binding(self) -> None:
        _sql, params, _plan = self.compile(
            metrics=("claims",), dimensions=("sentiment",), filters={"sentiment": "混合"})
        self.assertIn("正负混合", params)
        self.assertNotIn("混合", params)

    def test_time_window_uses_declared_coverage(self) -> None:
        _sql, params, _plan = self.compile(
            metrics=("claims",), dimensions=("time_month",),
            time={"start": "2026-01", "end": "2026-03"})
        self.assertIn("2026-01", params)
        self.assertIn("2026-03", params)

    def test_multi_attribution_metric_lives_on_claim_product_grain(self) -> None:
        sql, params, plan = self.compile(metrics=("productClaims",), dimensions=("product",))
        self.assertIn('FROM "semantic_claim_product" AS t0', sql)
        self.assertIn("FROM semantic_population WHERE population = ?", sql)
        self.assertIn('LEFT JOIN "semantic_product" AS t1 ON t1."node_id" = t0."product_id"', sql)
        self.assertEqual(plan.grain, "claim_product")
        self.assertEqual(params[0], "experience")

    def test_label_dimension_joins_the_same_product_node(self) -> None:
        sql, _params, plan = self.compile(metrics=("productClaims",),
                                          dimensions=("product", "product_label"))
        self.assertEqual(sql.count('LEFT JOIN "semantic_product"'), 1)
        self.assertIn('t1."label" AS "product_label"', sql)
        self.assertEqual(len(plan.joins), 1)

    def test_claim_metric_rejects_product_dimension(self) -> None:
        """观点级指标不能按车型切：一条观点提到多个车型时没有唯一归属，须改用 productClaims。"""
        with self.assertRaises(QueryError) as caught:
            compile_query(QuerySpec(metrics=("claims",), dimensions=("product",)), self.model)
        self.assertEqual(caught.exception.code, "DIMENSION_NOT_ALLOWED")
        self.assertEqual(caught.exception.details.get("dimension"), "product")

    def test_compilation_is_deterministic(self) -> None:
        kwargs = dict(metrics=("negativeShare", "posts"), dimensions=("aspect", "time_month"))
        first = self.compile(**kwargs)
        second = self.compile(**kwargs)
        self.assertEqual(first[0], second[0])
        self.assertEqual(first[1], second[1])

    def test_saved_query_shapes_compile_or_fail_for_known_reasons(self) -> None:
        """命名查询要么能编译，要么给出明确错误码；不允许"编译成功但结果错"。"""
        allowed = {}
        for name, saved in self.model.saved_queries.items():
            if saved.kind == "meta":
                continue
            spec = QuerySpec(
                metrics=saved.metrics, dimensions=saved.dimensions,
                filters={key: "外观与内饰" if isinstance(value, str) and value.startswith("$")
                         else value for key, value in saved.filters.items()},
                order=saved.order, limit=saved.limit or 100, population=saved.population)
            try:
                compile_query(spec, self.model)
            except QueryError as exc:
                allowed[name] = exc.code
        # 每个命名查询都必须能编译：口径不同用不同指标表达，不靠运行期拒绝。
        self.assertEqual(allowed, {})


class CompileRejectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()

    def assert_code(self, expected: str, **kwargs) -> None:
        with self.assertRaises(QueryError) as caught:
            compile_query(QuerySpec(**kwargs), self.model)
        self.assertEqual(caught.exception.code, expected)
        self.assertTrue(caught.exception.as_dict().get("message"))

    def test_unknown_metric_lists_available(self) -> None:
        with self.assertRaises(QueryError) as caught:
            compile_query(QuerySpec(metrics=("ghost",)), self.model)
        self.assertEqual(caught.exception.code, "UNKNOWN_METRIC")
        self.assertIn("claims", caught.exception.details.get("metrics", []))

    def test_unknown_dimension(self) -> None:
        self.assert_code("UNKNOWN_DIMENSION", metrics=("claims",), dimensions=("ghost",))

    def test_dimension_outside_metric_contract(self) -> None:
        # 负面观点占比的可切分维度不含 sentiment（分子已固定为负面）。
        self.assert_code("DIMENSION_NOT_ALLOWED",
                         metrics=("negativeShare",), dimensions=("sentiment",))

    def test_too_many_dimensions(self) -> None:
        self.assert_code("TOO_MANY_DIMENSIONS",
                         metrics=("claims",), dimensions=("aspect", "sentiment", "journey"))

    def test_limit_above_policy(self) -> None:
        self.assert_code("LIMIT_EXCEEDED", metrics=("claims",), limit=999)

    def test_population_override_must_match_every_metric(self) -> None:
        self.assert_code("POPULATION_MISMATCH", metrics=("negative",), population="curated")

    def test_metrics_across_populations_are_rejected(self) -> None:
        self.assert_code("POPULATION_MISMATCH", metrics=("claims", "curatedClaims"))

    def test_one_to_many_dimension_is_rejected_instead_of_inflating(self) -> None:
        """给 mention 挂一个维度，构造必须经过 post→mention 的 1:N 路径。"""
        document = yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))
        document["dimensions"]["mention_status"] = {
            "dataset": "mention", "column": "status", "type": "categorical",
            "label": "提及来源", "enum_source": "query"}
        document["metrics"]["posts"]["allowed_dimensions"].append("mention_status")
        model = build_model(document)
        with self.assertRaises(QueryError) as caught:
            compile_query(QuerySpec(metrics=("posts",), dimensions=("mention_status",)), model)
        self.assertEqual(caught.exception.code, "FANOUT_RISK")

    def test_order_field_must_be_in_the_query(self) -> None:
        self.assert_code("UNKNOWN_FIELD", metrics=("claims",),
                         order=({"field": "posts", "dir": "desc"},))

    def test_empty_metric_list_is_rejected(self) -> None:
        self.assert_code("UNKNOWN_METRIC", metrics=())

    def test_time_window_outside_coverage(self) -> None:
        self.assert_code("OUT_OF_COVERAGE", metrics=("claims",), dimensions=("time_month",),
                         time={"start": "2019-01", "end": "2019-06"})


if __name__ == "__main__":
    unittest.main()
