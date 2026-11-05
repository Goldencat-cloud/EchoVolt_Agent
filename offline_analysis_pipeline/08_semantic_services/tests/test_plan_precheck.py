"""计划预检的分层边界：端点只判语法/结构，工具判方法/参数语义。

回归背景：端点曾自建一份 JSON 形状判据，与工具的语义判据并行演化，
导致"端点放行、工具拒绝"的无效运行。现在两者共用同一解析入口。
"""
from __future__ import annotations

import json
import unittest

import agent_tools


def _plan(**stream: object) -> str:
    return json.dumps({"coverage": "测试覆盖",
                       "workstreams": [{"id": "w1", **stream}]}, ensure_ascii=False)


class PlanShapeTests(unittest.TestCase):
    def test_invalid_json_reports_single_problem(self):
        self.assertEqual(agent_tools.plan_shape_problems("{"), ["plan_json 不是合法 JSON"])

    def test_non_object_plan_rejected(self):
        self.assertEqual(agent_tools.plan_shape_problems("[]"), ["草案必须是对象"])

    def test_empty_workstreams_rejected(self):
        plan = json.dumps({"workstreams": []})
        self.assertEqual(agent_tools.plan_shape_problems(plan), ["workstreams 必须是非空数组"])

    def test_legacy_method_passes_shape_check(self):
        """端点不判方法名：方法语义由工具与门禁负责（保持既有 202 行为）。"""
        plan = _plan(method="negative_claims_by_month", question="月度负面趋势")
        self.assertEqual(agent_tools.plan_shape_problems(plan), [])


class PlanSemanticTests(unittest.TestCase):
    def test_unknown_method_reported_by_tool_precheck(self):
        plan = _plan(method="negative_claims_by_month", question="月度负面趋势")
        self.assertTrue(agent_tools.plan_problems(plan))

    def test_tool_precheck_covers_every_shape_problem(self):
        for raw in ("{", "[]", json.dumps({"workstreams": []})):
            self.assertEqual(agent_tools.plan_problems(raw),
                             agent_tools.plan_shape_problems(raw))


if __name__ == "__main__":
    unittest.main()
