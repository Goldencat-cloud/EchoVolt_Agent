"""语义层方法接入报告链路：计划可声明 → 执行可登记 → 门禁认账。

这是 B 方案的验收点：新引擎的数字必须能进 verified_steps，否则报告会因
"数字找不到出处"被拒，而数据其实是查得到的。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_tools  # noqa: E402
from research import analysis_methods  # noqa: E402
import report_gate  # noqa: E402
import verifier  # noqa: E402
from semantic.adapters import api as semantic_api  # noqa: E402


def _tools(context: dict) -> dict:
    return {tool.name: tool for tool in agent_tools.build_tools(context)}


def _plan_payload(**param_overrides):
    params = {"metrics": ["claims"], "dimensions": ["aspect"], "limit": 3}
    params.update(param_overrides)
    return json.dumps({
        "coverage": "按议题看观点量",
        "use_python": False,
        "workstreams": [{"id": "w1", "question": "各议题观点量", "aspect": None,
                         "method": analysis_methods.SEMANTIC_METHOD, "params": params}],
    })


class SemanticMethodTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context: dict = {}
        self.tools = _tools(self.context)

    def plan(self, **overrides) -> dict:
        return json.loads(self.tools["submit_analysis_plan"].invoke(
            {"plan_json": _plan_payload(**overrides)}))

    def test_plan_accepts_semantic_workstream_with_params(self) -> None:
        accepted = self.plan()
        self.assertTrue(accepted.get("accepted"), accepted)
        stream = accepted["plan"]["workstreams"][0]
        self.assertEqual(stream["method"], analysis_methods.SEMANTIC_METHOD)
        self.assertEqual(stream["params"]["metrics"], ["claims"])
        self.assertFalse(stream["requires_evidence"])

    def test_run_records_a_verifiable_step(self) -> None:
        self.plan()
        payload = json.loads(self.tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["claims"], "dimensions": ["aspect"],
                                        "limit": 3})}))
        self.assertNotIn("error", payload, payload)
        self.assertTrue(payload["verification"]["ok"], payload["verification"])
        self.assertIn("模型口径", payload["caliber"])
        self.assertGreater(payload["row_count"], 0)
        steps = self.context["verified_steps"]
        self.assertEqual(steps[-1]["method"], analysis_methods.SEMANTIC_METHOD)
        self.assertTrue(steps[-1]["verification"]["ok"])

    def test_params_must_match_the_approved_plan(self) -> None:
        self.plan()
        payload = json.loads(self.tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["posts"], "limit": 3})}))
        self.assertEqual(payload["error"], "analysis_step_not_in_plan")

    def test_unknown_metric_is_rejected_without_recording_a_step(self) -> None:
        self.plan()
        payload = json.loads(self.tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["ghost"], "limit": 3})}))
        self.assertEqual(payload["error"], "semantic_params_invalid")
        self.assertNotIn("verified_steps", self.context)

    def test_plan_rejects_unknown_semantic_names_before_execution(self) -> None:
        """指标/维度/过滤/口径名越界要在计划阶段整单拒绝，而不是拖到执行期。"""
        for overrides in ({"metrics": ["ghost"]}, {"dimensions": ["ghost"]},
                          {"filters": {"ghost": "x"}}, {"population": "ghost"}):
            with self.subTest(overrides=overrides):
                rejected = self.plan(**overrides)
                self.assertEqual(rejected.get("error"), "invalid_workstream_fields", rejected)
                self.assertNotIn("plan", self.context)

    def test_report_gate_accepts_numbers_from_the_semantic_step(self) -> None:
        self.plan()
        result = json.loads(self.tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["claims"], "dimensions": ["aspect"],
                                        "limit": 3})}))
        claims = int(result["rows"][0]["claims"])
        aspect = result["rows"][0]["aspect"]
        verdict = report_gate.validate_submission(
            title="小米 SU7 议题观点量",
            markdown=(f"## 结论摘要\n{aspect} 共 {claims} 条观点。\n"
                      "分析主体：小米 SU7；品牌范围：本次仅统计该车型。\n"
                      "数据版本 2026-11-03。\n"
                      "## 证据与归组\n按议题聚合，口径为模型口径。\n"
                      "## 限制与不确定性\n样本覆盖有限。\n"),
            key_findings=[f"{aspect} 观点量为 {claims} 条"],
            data_version="2026-11-03",
            evidence_claim_ids=set(),
            verified_steps=self.context["verified_steps"],
            plan=self.context["plan"],
        )
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_verifier_rejects_a_tampered_row(self) -> None:
        step = analysis_methods.run(analysis_methods.SEMANTIC_METHOD,
                                    {"metrics": ["claims"], "dimensions": ["aspect"],
                                     "limit": 3})
        tampered = {**step, "rows": [dict(row) for row in step["rows"]]}
        tampered["rows"][0]["claims"] = 999999
        verdict = verifier.verify_step(tampered)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("不一致" in item for item in verdict["errors"]), verdict["errors"])

    def test_engine_only_touches_semantic_relations(self) -> None:
        result = analysis_methods.run(analysis_methods.SEMANTIC_METHOD,
                                      {"metrics": ["negativeShare"], "dimensions": ["aspect"],
                                       "limit": 2})
        verifier.assert_semantic_only(result["sql"])
        self.assertIn("semantic_population", result["sql"])

    def test_tool_specs_are_published_once(self) -> None:
        names = {spec["name"] for spec in semantic_api.tool_specs()}
        self.assertEqual(names, {"semantic_catalogue", "semantic_query", "semantic_saved"})


if __name__ == "__main__":
    unittest.main()
