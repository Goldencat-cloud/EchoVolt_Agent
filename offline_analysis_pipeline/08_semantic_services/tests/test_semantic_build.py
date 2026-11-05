"""构建层的回归测试：口径阶梯的规模、包含关系与产物幂等。

这里断言的是"规模基线"，不是代码行数：上游重跑或口径改动一旦让某一级人数变化，
基线必须被显式更新，而不是让新数字悄悄替换旧结论。
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.build import runner  # noqa: E402
from semantic.model import load_model  # noqa: E402
from semantic.spec import ModelError  # noqa: E402

# 与 design.md D6 / proposal.md 记录的阶梯一致；改动口径必须同时更新这里。
BASELINE = {
    "extracted": 26936,
    "su7_linked": 18087,
    "su7_primary": 7024,
    "experience": 3356,
    "firsthand": 942,
    "curated": 819,
}


class BuildRegressionTest(unittest.TestCase):
    """一次真实构建喂给多个断言；源数据缺失时跳过而不是失败。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="semantic-build-"))
        cls.db_path = cls.tmpdir / "semantic.db"
        try:
            cls.result = runner.build(model=cls.model, db_path=cls.db_path, force=True)
        except ModelError as exc:  # 数据源不在本机
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
            raise unittest.SkipTest(f"构建输入不可用：{exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self) -> None:
        self.con = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)

    def tearDown(self) -> None:
        self.con.close()

    def scalar(self, sql: str, params: tuple = ()) -> int:
        return self.con.execute(sql, params).fetchone()[0]

    def test_ladder_matches_baseline(self) -> None:
        self.assertEqual(self.result["ladder"], BASELINE)

    def test_every_claim_belongs_to_root_population(self) -> None:
        claims = self.scalar("SELECT COUNT(*) FROM fct_claim")
        # 断言对外视图而不是物理表：查询侧只准碰 semantic_* 关系。
        members = self.scalar(
            "SELECT COUNT(*) FROM semantic_population WHERE population = 'extracted'")
        self.assertEqual(members, claims)

    def test_population_members_are_inside_their_parent(self) -> None:
        """包含关系不是靠谓词文案保证，而是逐条核对成员表。"""
        violations = {}
        for name, population in self.model.populations.items():
            if population.dataset != "claim" or not population.parent:
                continue
            outside = self.scalar(
                "SELECT COUNT(*) FROM semantic_population c WHERE c.population = ? "
                "AND NOT EXISTS (SELECT 1 FROM semantic_population p "
                "WHERE p.population = ? AND p.claim_id = c.claim_id)",
                (name, population.parent))
            if outside:
                violations[name] = outside
        self.assertEqual(violations, {})

    def test_population_table_agrees_with_ladder(self) -> None:
        counts = dict(self.con.execute(
            "SELECT population, COUNT(*) FROM semantic_population GROUP BY population"))
        for name, expected in self.result["ladder"].items():
            self.assertEqual(counts.get(name), expected, name)

    def test_ownership_is_materialized_on_the_fact_row(self) -> None:
        """成员判定要落在事实行上；列不存在或全空都会让 curated 静默变成 0。"""
        columns = {row[1] for row in self.con.execute("PRAGMA table_info(fct_claim)")}
        self.assertIn("ownership", columns)
        claims = self.scalar("SELECT COUNT(*) FROM fct_claim")
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM fct_claim WHERE ownership IS NOT NULL"),
            claims)

    def test_rebuild_without_force_is_up_to_date(self) -> None:
        again = runner.build(model=self.model, db_path=self.db_path)
        self.assertEqual(again["status"], "up_to_date")

    def test_views_are_generated_from_the_model_without_internal_columns(self) -> None:
        relations = {dataset.relation for dataset in self.model.datasets.values()}
        # 口径成员也以 semantic_* 视图对外，便于"只准碰语义层"的静态检查成立。
        relations.add("semantic_population")
        views = {row[0] for row in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'")}
        self.assertEqual(views, relations)
        claim_columns = {row[1] for row in self.con.execute("PRAGMA table_info(semantic_claim)")}
        self.assertIn("ownership", claim_columns)
        for internal in ("post_uid", "evidence_json", "comparison_json"):
            self.assertNotIn(internal, claim_columns)

    def test_claim_product_records_multi_attribution(self) -> None:
        """一条观点提到多个车型要落多行；否则多归属口径无法成立。"""
        claims = self.scalar("SELECT COUNT(*) FROM fct_claim")
        pairs = self.scalar("SELECT COUNT(*) FROM fct_claim_product")
        self.assertGreaterEqual(pairs, claims)
        multi = self.scalar(
            "SELECT COUNT(*) FROM (SELECT claim_id FROM fct_claim_product "
            "GROUP BY claim_id HAVING COUNT(*) > 1)")
        self.assertGreater(multi, 0)

    def test_catalogue_matches_the_built_artifact(self) -> None:
        """真实规模下：口径规模与模型一致，超大取值空间不整表枚举。"""
        from semantic.catalog import describe

        catalogue = describe(model=self.model, db_path=self.db_path)
        self.assertEqual(catalogue["populations"]["curated"]["size"], BASELINE["curated"])
        self.assertEqual(set(catalogue["metrics"]), set(self.model.metrics))
        claim_id = catalogue["dimensions"]["claim_id"]
        self.assertTrue(claim_id["enum_truncated"])
        self.assertEqual(claim_id["distinct_values"], BASELINE["extracted"])
        self.assertNotIn("enum", claim_id)

    def test_query_runs_against_the_built_artifact(self) -> None:
        """构建 → 视图 → 编译 → 执行，整条链路在真实产物上跑通一次。"""
        from semantic.execute import execute
        from semantic.spec import QuerySpec

        result = execute(QuerySpec(metrics=("curatedClaims",)), model=self.model,
                         db_path=self.db_path)
        self.assertEqual(result["rows"], [{"curatedClaims": BASELINE["curated"]}])
        self.assertEqual(result["model_version"], self.model.model_version)


if __name__ == "__main__":
    unittest.main()
