"""Cross-stage tests for analysis-plan gating and evidence flow."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_tools


def make_tools(context):
    return {tool.name: tool for tool in agent_tools.build_tools(context)}


def workstream(stream_id, aspect, method="semantic_aggregate", evidence=False):
    """语义计划样例：议题写在 params.filters 里，工作项 aspect 恒为 null。"""
    params = {"metrics": ["curatedNegative"] if evidence else ["negativeShare", "claims"],
              "dimensions": ["aspect"],
              "filters": {"aspect": aspect}}
    return {"id": stream_id, "question": f"{aspect}反馈表现如何？",
            "aspect": None, "method": method, "params": params,
            "requires_evidence": evidence}


def accepted_plan(*streams, use_python=False):
    return {"coverage": "比较问题中指定议题的统计口径并核对证据",
            "workstreams": list(streams), "use_python": use_python}


class AgentWorkflowTests(unittest.TestCase):
    def test_multi_aspect_plan_runs_each_analysis_before_results_are_accepted(self):
        context = {"submissions": []}
        tools = make_tools(context)
        plan = accepted_plan(
            workstream("reliability", "可靠性与故障"),
            workstream("comfort", "空间与舒适性"))
        accepted = json.loads(tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(plan, ensure_ascii=False)}))
        self.assertTrue(accepted["accepted"])

        results = []
        for aspect in ("可靠性与故障", "空间与舒适性"):
            params = {"metrics": ["negativeShare", "claims"], "dimensions": ["aspect"],
                      "filters": {"aspect": aspect}}
            result = json.loads(tools["run_semantic_aggregate"].invoke(
                {"params_json": json.dumps(params, ensure_ascii=False)}))
            self.assertNotIn("error", result)
            self.assertTrue(result["rows"])
            results.append(result)

        self.assertEqual(len(context["verified_steps"]), 2)
        self.assertEqual(context["successful_tool_calls"], 3)
        self.assertEqual([r["rows"][0]["aspect"] for r in results],
                         ["可靠性与故障", "空间与舒适性"])

    def test_analysis_cannot_run_before_plan_or_outside_plan(self):
        context = {"submissions": []}
        tools = make_tools(context)
        def params_for(aspect):
            return json.dumps({"metrics": ["negativeShare", "claims"],
                               "dimensions": ["aspect"],
                               "filters": {"aspect": aspect}}, ensure_ascii=False)

        blocked = json.loads(tools["run_semantic_aggregate"].invoke(
            {"params_json": params_for("可靠性与故障")}))
        self.assertEqual(blocked["error"], "analysis_plan_required")

        plan = accepted_plan(workstream("reliability", "可靠性与故障"))
        tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(plan, ensure_ascii=False)})
        blocked = json.loads(tools["run_semantic_aggregate"].invoke(
            {"params_json": params_for("空间与舒适性")}))
        self.assertEqual(blocked["error"], "analysis_step_not_in_plan")

    def test_interactive_agent_can_choose_tools_without_plan_workflow(self):
        context = {"interactive": True, "submissions": []}
        tools = make_tools(context)
        stats = json.loads(tools["run_semantic_aggregate"].invoke({
            "params_json": json.dumps({"metrics": ["negativeShare", "claims"],
                                       "dimensions": ["aspect"],
                                       "filters": {"aspect": "空间与舒适性"}},
                                      ensure_ascii=False)}))
        self.assertNotIn("error", stats)
        self.assertTrue(context["verified_steps"])

        with patch.object(agent_tools.sandbox, "run_code",
                          return_value={"ok": True, "stdout": "", "result": 4}):
            code = json.loads(tools["python_analyze"].invoke({"code": "result = 2 + 2"}))
        self.assertTrue(code["ok"])
        self.assertIn("4", code.get("stdout", "") + json.dumps(code.get("result")))

        evidence = json.loads(tools["get_negative_evidence"].invoke({
            "aspect": "空间与舒适性", "limit": 2}))
        self.assertTrue(evidence["data"])

    def test_invalid_dimension_and_unknown_aspect_are_rejected(self):
        context = {"submissions": []}
        tools = make_tools(context)
        bad_dimension = workstream("bad", "可靠性与故障")
        bad_dimension["params"]["dimensions"] = ["income"]
        response = json.loads(tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(accepted_plan(bad_dimension), ensure_ascii=False)}))
        self.assertEqual(response["error"], "invalid_workstream_fields")

        unknown = workstream("unknown", "不存在的议题")
        response = json.loads(tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(accepted_plan(unknown), ensure_ascii=False)}))
        self.assertEqual(response["error"], "invalid_workstream_fields")

    def test_report_submission_is_blocked_until_every_workstream_finishes(self):
        context = {"submissions": []}
        tools = make_tools(context)
        plan = accepted_plan(workstream("reliability", "可靠性与故障"))
        tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(plan, ensure_ascii=False)})
        response = json.loads(tools["submit_report"].invoke({
            "title": "可靠性分析", "markdown": "# 可靠性分析\n\n依据：待补。",
            "key_findings": "[]"}))
        self.assertEqual(response["error"], "analysis_plan_incomplete")
        self.assertEqual(response["workstreams"], ["reliability"])
        self.assertEqual(context["submissions"], [])
        # 被拒的提交由 submit_attempts/gate_rejections 记账：不占错误预算，
        # 也不算一次成功调用（否则每次门禁拒绝都白送调用预算）。
        self.assertEqual(context.get("tool_errors", 0), 0)
        self.assertEqual(context["successful_tool_calls"], 1)

    def test_python_analysis_requires_explicit_plan_authorization(self):
        context = {"submissions": []}
        tools = make_tools(context)
        plan = accepted_plan(workstream("reliability", "可靠性与故障"), use_python=False)
        tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(plan, ensure_ascii=False)})
        response = json.loads(tools["python_analyze"].invoke({"code": "result = 1 + 1"}))
        self.assertEqual(response["error"], "python_not_authorized_by_plan")

    def test_required_evidence_is_available_only_for_planned_topic(self):
        context = {"submissions": []}
        tools = make_tools(context)
        plan = accepted_plan(workstream("comfort", "空间与舒适性", evidence=True))
        tools["submit_analysis_plan"].invoke(
            {"plan_json": json.dumps(plan, ensure_ascii=False)})
        blocked = json.loads(tools["get_negative_evidence"].invoke(
            {"aspect": "可靠性与故障"}))
        self.assertEqual(blocked["error"], "evidence_not_in_plan")
        evidence = json.loads(tools["get_negative_evidence"].invoke(
            {"aspect": "空间与舒适性", "limit": 3}))
        self.assertTrue(evidence["data"])
        self.assertTrue(all(row["claim_id"] and row["quote"] and row["url"]
                            for row in evidence["data"]))

    def test_successful_python_analyze_does_not_consume_error_budget(self):
        """沙箱成功结果原样带出 "error": None；守卫按 error 真值判定，
        否则每次成功的代码分析都会白耗一次错误预算（预算上限 6 次）。"""
        context = {"submissions": [], "interactive": True}
        tools = make_tools(context)
        with patch.object(agent_tools.sandbox, "run_code",
                          return_value={"ok": True, "stdout": "", "result": 1,
                                        "error": None}):
            payload = json.loads(tools["python_analyze"].invoke({"code": "result = 1"}))
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["error"])
        self.assertEqual(context.get("tool_errors", 0), 0)
        self.assertEqual(context["successful_tool_calls"], 1)

    def test_failed_python_analyze_counts_one_error(self):
        context = {"submissions": [], "interactive": True}
        tools = make_tools(context)
        with patch.object(agent_tools.sandbox, "run_code",
                          return_value={"ok": False, "stdout": "", "error": "boom"}):
            payload = json.loads(tools["python_analyze"].invoke({"code": "result = 1"}))
        self.assertFalse(payload["ok"])
        self.assertEqual(context["tool_errors"], 1)   # 工具内部记账，守卫不得重复累加


if __name__ == "__main__":
    unittest.main()
