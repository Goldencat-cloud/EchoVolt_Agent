"""模型层的契约测试：结构、引用完整性、不可变性与分层依赖方向。

这些用例的作用不是覆盖代码行，而是把"定义错了必须失败"这条规则钉住：
任何一条失效，坏定义就能变成对外发布的数字。
"""

from __future__ import annotations

import ast
import dataclasses
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.model import build_model, load_model  # noqa: E402
from semantic.spec import ModelError, Population, render_caliber  # noqa: E402

PACKAGE = Path(__file__).resolve().parents[1] / "semantic"
MODEL_PATH = PACKAGE / "model.yaml"


def raw_model() -> dict:
    """真实模型的可变副本，供反例用例改动。"""
    return yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))


class ModelShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_model()

    def test_model_declares_expected_shape(self) -> None:
        self.assertEqual(set(self.model.datasets),
                         {"claim", "claim_product", "post", "mention", "product", "user"})
        self.assertEqual(len(self.model.relationships), 6)
        self.assertEqual(set(self.model.populations),
                         {"extracted", "su7_linked", "su7_primary", "experience",
                          "firsthand", "curated"})
        self.assertEqual(self.model.datasets["claim"].grain, "claim")
        self.assertEqual(self.model.datasets["mention"].primary_key,
                         ("post_id", "product_id"))
        self.assertEqual(self.model.datasets["claim"].population, "experience")

    def test_ladder_is_a_chain_of_rules_below_su7_primary(self) -> None:
        experience = self.model.populations["experience"]
        self.assertEqual(experience.parent, "su7_primary")
        self.assertEqual(experience.source, "rule")
        # curated 由两条规则分支取并集，必须留在 su7_primary 之内才能保证父子包含关系。
        curated = self.model.populations["curated"]
        self.assertEqual(curated.source, "rule")
        self.assertEqual(curated.parent, "su7_primary")
        self.assertIn("ownership", curated.filter or "")
        self.assertIsNotNone(curated.note)

    def test_domain_objects_are_immutable(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.model.datasets["claim"].grain = "post"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            self.model.metrics["claims"] = None  # type: ignore[index]
        with self.assertRaises(TypeError):
            self.model.dimensions["sentiment"].alias["混合"] = "正面"  # type: ignore[index]

    def test_caliber_text_is_derived_from_fields(self) -> None:
        metric = self.model.metrics["negativeShare"]
        text = render_caliber(metric, self.model.populations["experience"])
        self.assertIn("negative ÷ claims", text)
        self.assertIn("观点条数", text)
        self.assertIn("口径 experience", text)
        self.assertIn("不可跨分组相加", text)

    def test_frozen_population_is_marked_in_caliber(self) -> None:
        # 冻结来源仍受支持：口径文案必须如实写出"不可由规则重算"，不能伪装成规则。
        frozen = Population(name="frozen_demo", dataset="claim", source="frozen")
        text = render_caliber(self.model.metrics["curatedClaims"], frozen)
        self.assertIn("冻结成员", text)

    def test_rule_population_is_not_marked_frozen(self) -> None:
        text = render_caliber(self.model.metrics["curatedClaims"],
                              self.model.populations["curated"])
        self.assertNotIn("冻结成员", text)

    def test_metric_promotes_unit_only_by_declaring_count_distinct(self) -> None:
        posts = self.model.metrics["posts"]
        self.assertEqual(posts.grain, "post")
        self.assertEqual(posts.agg, "count_distinct")
        self.assertEqual(posts.field, "post_id")

    def test_curated_and_experience_metrics_are_distinct_names(self) -> None:
        self.assertNotEqual(self.model.metrics["negativeShare"].population,
                            self.model.metrics["curatedNegativeShare"].population)
        self.assertNotEqual(self.model.metrics["negativeShare"].name,
                            self.model.metrics["curatedNegativeShare"].name)


class ModelRejectionTest(unittest.TestCase):
    def assert_rejected(self, mutate, expected: str) -> None:
        """反例必须因指定原因失败——否则用例会在错误的检查上假通过。"""
        document = raw_model()
        mutate(document)
        with self.assertRaises(ModelError) as caught:
            build_model(document)
        self.assertIn(expected, str(caught.exception))

    def test_missing_grain_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            del document["datasets"]["claim"]["grain"]
        self.assert_rejected(mutate, "缺少必填字段 'grain'")

    def test_missing_primary_key_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            del document["datasets"]["post"]["primary_key"]
        self.assert_rejected(mutate, "缺少必填字段 'primary_key'")

    def test_mixed_grain_dataset_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["datasets"]["claim"]["grain"] = ["claim", "post"]
        self.assert_rejected(mutate, "单一粒度")

    def test_undefined_relationship_target_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["relationships"][0]["to"]["dataset"] = "ghost"
        self.assert_rejected(mutate, "未定义的数据集 'ghost'")

    def test_metric_with_unknown_population_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["metrics"]["claims"]["population"] = "nope"
        self.assert_rejected(mutate, "未定义的口径 'nope'")

    def test_ratio_without_numerator_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            del document["metrics"]["negativeShare"]["numerator"]
        self.assert_rejected(mutate, "缺少必填字段 'numerator'")

    def test_ratio_across_populations_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["metrics"]["curatedNegativeShare"]["numerator"] = "negative"
        self.assert_rejected(mutate, "跨口径比率不允许")

    def test_population_cycle_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["populations"]["extracted"]["parent"] = "curated"
        self.assert_rejected(mutate, "循环引用")

    def test_population_parent_on_another_dataset_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["populations"]["orphan"] = {
                "dataset": "post", "source": "rule", "parent": "experience",
                "filter": "1 = 1"}
        self.assert_rejected(mutate, "不一致")

    def test_expression_containing_sql_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["populations"]["su7_linked"]["filter"] = "1 = 1; DROP TABLE t"
        self.assert_rejected(mutate, "SQL 关键字")

    def test_metric_dimension_without_relationship_path_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["datasets"]["orphan"] = {
                "relation": "semantic_orphan", "source": "dim_orphan",
                "grain": "user", "primary_key": "user_id", "description": "孤立数据集"}
            document["dimensions"]["orphan_dim"] = {
                "dataset": "orphan", "column": "x", "type": "categorical",
                "label": "孤立维度", "enum_source": "query"}
            document["metrics"]["claims"]["allowed_dimensions"].append("orphan_dim")
        self.assert_rejected(mutate, "没有声明的关系路径")

    def test_saved_query_with_unknown_metric_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["saved_queries"]["negative_share_by_aspect"]["metrics"] = ["ghost"]
        self.assert_rejected(mutate, "未定义的指标 'ghost'")

    def test_saved_query_dimension_outside_metric_contract_is_rejected(self) -> None:
        """命名查询若用了指标不允许的维度，必须在加载期失败，而不是调用时才发现。"""
        def mutate(document: dict) -> None:
            document["saved_queries"]["curated_sentiment_mix"]["dimensions"] = ["claim_id"]
        self.assert_rejected(mutate, "allowed_dimensions")

    def test_static_enum_alias_must_point_at_a_real_value(self) -> None:
        def mutate(document: dict) -> None:
            document["dimensions"]["sentiment"]["alias"] = {"混合": "不清楚"}
        self.assert_rejected(mutate, "不在枚举中")

    def test_ratio_cannot_be_declared_additive(self) -> None:
        def mutate(document: dict) -> None:
            document["metrics"]["negativeShare"]["additive"] = True
        self.assert_rejected(mutate, "不可声明为可加")


class LayeringTest(unittest.TestCase):
    """分层只为防重复：下层不得反向引用上层，否则又会多出第二份实现。"""

    LAYERS = {"spec": 0, "model": 1, "build": 2, "compile": 2,
              "execute": 3, "catalog": 3, "adapters": 4}

    def test_imports_only_point_downward(self) -> None:
        violations: list[str] = []
        for path in PACKAGE.rglob("*.py"):
            parts = path.relative_to(PACKAGE).parts
            if len(parts) < 2:
                continue
            source_layer = self.LAYERS.get(parts[0])
            if source_layer is None:
                continue
            package_parts = ("semantic",) + parts[:-1]
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                target = self._resolve_import(node, package_parts)
                if target is None:
                    continue
                target_layer = self.LAYERS.get(target)
                if target_layer is None:
                    continue
                if target_layer > source_layer:
                    violations.append(
                        f"{path.name}: {parts[0]} 引用了上层 {target}")
        self.assertEqual(violations, [], "存在反向依赖：" + "; ".join(violations))

    @staticmethod
    def _resolve_import(node: ast.AST, package_parts: tuple[str, ...]) -> str | None:
        if isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                base = package_parts[:keep]
                parts = base + tuple((node.module or "").split(".")) if node.module else base
            else:
                parts = tuple((node.module or "").split("."))
            return parts[1] if len(parts) > 1 and parts[0] == "semantic" else None
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = tuple(alias.name.split("."))
                if len(parts) > 1 and parts[0] == "semantic":
                    return parts[1]
        return None


if __name__ == "__main__":
    unittest.main()
