"""目录导出：一次调用要能支撑一次合法查询。

目录不得成为"第二份定义"：这里的断言一半是"内容与模型一致"，另一半是
"代码里没有指标名清单"。
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.catalog import describe  # noqa: E402
from semantic.compile import QueryError  # noqa: E402
from semantic.execute import execute  # noqa: E402
from semantic.model import build_model, load_model  # noqa: E402
from semantic.spec import QuerySpec  # noqa: E402
from tests.semantic_fixture import build_fixture  # noqa: E402

CATALOG_SOURCE = Path(__file__).resolve().parents[1] / "semantic" / "catalog" / "describe.py"
MODEL_PATH = Path(__file__).resolve().parents[1] / "semantic" / "model.yaml"


class CatalogueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="semantic-catalog-"))
        cls.db_path = cls.tmpdir / "semantic.db"
        build_fixture(cls.db_path, cls.model)
        cls.catalogue = describe(model=cls.model, db_path=cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_datasets_report_grain_primary_key_and_rows(self) -> None:
        datasets = self.catalogue["datasets"]
        self.assertEqual(datasets["claim"]["grain"], "claim")
        self.assertEqual(datasets["claim_product"]["primary_key"], ["claim_id", "product_id"])
        self.assertEqual(datasets["claim"]["rows"], 6)
        self.assertEqual(datasets["claim_product"]["rows"], 5)

    def test_populations_carry_size_source_and_parent(self) -> None:
        populations = self.catalogue["populations"]
        self.assertEqual(populations["extracted"]["size"], 6)
        self.assertEqual(populations["curated"]["size"], 3)
        self.assertEqual(populations["curated"]["parent"], "su7_primary")
        self.assertEqual(populations["curated"]["source"], "rule")

    def test_static_enum_is_taken_verbatim(self) -> None:
        sentiment = self.catalogue["dimensions"]["sentiment"]
        self.assertEqual(sentiment["enum"], list(self.model.dimensions["sentiment"].enum))

    def test_enum_values_come_from_the_database(self) -> None:
        """没有静态枚举的维度按库内频次排序，最高频排前。"""
        aspect = self.catalogue["dimensions"]["aspect"]
        self.assertEqual(aspect["enum"][0], "外观与内饰")
        self.assertEqual(len(aspect["enum"]), 3)

    def test_excluded_values_never_appear_in_enums(self) -> None:
        aspect = self.catalogue["dimensions"]["aspect"]
        self.assertNotIn("政策与市场", aspect["enum"])
        self.assertIn("外观与内饰", aspect["enum"])
        self.assertEqual(aspect["excluded"], ["政策与市场", "无法判断"])
        self.assertEqual(aspect["null_label"], "未标注")

    def test_time_coverage_is_read_from_data_not_copied(self) -> None:
        month = self.catalogue["dimensions"]["time_month"]
        self.assertEqual(month["coverage"], ["2026-01", "2026-01"])
        self.assertEqual(month["grain"], "month")

    def test_metrics_carry_caliber_and_split_dimensions(self) -> None:
        metrics = self.catalogue["metrics"]
        self.assertIn("口径 experience", metrics["claims"]["caliber"])
        self.assertIn("观点×车型条数", metrics["productClaims"]["caliber"])
        self.assertIn("product", metrics["productClaims"]["allowed_dimensions"])
        self.assertNotIn("product", metrics["claims"]["allowed_dimensions"])
        self.assertEqual(metrics["negativeShare"]["numerator"], "negative")

    def test_saved_queries_expose_params_and_limits(self) -> None:
        query = self.catalogue["saved_queries"]["product_claim_volume"]
        self.assertIn("aspect", query["params"])
        self.assertEqual(query["limit"], 20)
        self.assertIn("productClaims", query["metrics"])

    def test_definition_only_mode_needs_no_database(self) -> None:
        catalogue = describe(model=self.model, db_path=self.db_path, with_values=False)
        self.assertIsNone(catalogue["datasets"]["claim"]["rows"])
        self.assertNotIn("enum", catalogue["dimensions"]["aspect"])

    def test_catalogue_drives_a_runnable_query(self) -> None:
        """6.4 的可执行示例：目录里取指标与维度，直接组装请求。"""
        catalogue = self.catalogue
        metric = "curatedClaims"
        dimension = catalogue["metrics"][metric]["allowed_dimensions"][0]
        result = execute(QuerySpec(metrics=(metric,), dimensions=(dimension,)),
                         model=self.model, db_path=self.db_path)
        self.assertGreaterEqual(result["row_count"], 1)
        self.assertEqual(result["metrics"][0]["name"], metric)

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
            describe(model=self.model, db_path=stale)
        self.assertEqual(caught.exception.code, "STALE_ARTIFACT")


class CatalogueFollowsModelTest(unittest.TestCase):
    """6.3：目录与模型同源，代码里不存在指标名清单。"""

    def test_catalogue_reflects_model_changes(self) -> None:
        document = yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))
        document["metrics"]["claimsDemo"] = {
            "label": "演示指标", "type": "simple", "dataset": "claim",
            "population": "experience", "grain": "claim", "additive": True,
            "agg": "count", "allowed_dimensions": ["aspect"]}
        document["saved_queries"]["demo_query"] = {
            "summary": "演示", "metrics": ["claimsDemo"], "dimensions": ["aspect"]}
        model = build_model(document)
        catalogue = describe(model=model, with_values=False)
        self.assertIn("claimsDemo", catalogue["metrics"])
        self.assertIn("demo_query", catalogue["saved_queries"])
        self.assertEqual(catalogue["model_version"], model.model_version)

    def test_catalogue_source_has_no_metric_names(self) -> None:
        model = load_model()
        source = CATALOG_SOURCE.read_text(encoding="utf-8")
        found = [name for name in model.metrics
                 if re.search(rf"\b{re.escape(name)}\b", source)]
        self.assertEqual(found, [], f"目录代码里出现了指标名清单：{found}")


if __name__ == "__main__":
    unittest.main()
