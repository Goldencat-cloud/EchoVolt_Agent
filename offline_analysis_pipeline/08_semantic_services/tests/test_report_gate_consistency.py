"""auto-032 task 7.x: report-gate consistency fixes (design D7).

覆盖：纯量化报告不强制观点引用、溯源来源剔除元数字、展示舍入、叙述数字清洗、
空结果解释鲁棒化、hash 上下文排除、章节行首匹配、key_findings 下限收缩、
submit_report 门禁拒绝不计入工具错误预算。
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_tools
import report_gate
from research import service

_CLAIM = "a" * 20
_HASH20 = "b1b2b3b4b5b6b7b8b9b0aa"
_VERSION = service.snapshot_version()

_BASELINE_STEP = {"kind": "baseline", "method": "baseline", "aspect": None,
                  "verification": {"ok": True},
                  "rows": [{"aspect": "可靠性与故障", "claims": 98, "negative": 54,
                            "negative_share": 0.551}]}

_METHOD_STEP = {"kind": "method", "method": "aspect_scope_compare",
                "aspect": "可靠性与故障", "verification": {"ok": True},
                "result": {"rows": [{"aspect": "可靠性与故障", "negative_share": 0.551}]}}

def _plan(method="aspect_scope_compare", requires_evidence=False):
    return {"use_python": False, "workstreams": [
        {"id": "w1", "question": "负面占比", "aspect": "可靠性与故障",
         "method": method, "requires_evidence": requires_evidence}]}

def _markdown(citation=None, limits="分析主体：小米/SU7，其余品牌仅为共现对比信息。"):
    cite = f"依据 claim_id: {citation}。" if citation else "本报告为纯量化分析，未引用观点原文。"
    return (f"# 报告\n\n## 结论摘要\n可靠性与故障负面占比 55.1%（全量声明级口径）。\n\n"
            f"## 证据与归组\n{cite}\n\n"
            f"## 限制与不确定性\n{limits}\n\n数据版本：{_VERSION}")

def _gate(markdown, plan=None, key_findings=None, claim_ids=None):
    return report_gate.validate_submission(
        title="可靠性报告", markdown=markdown,
        key_findings=key_findings if key_findings is not None else ["一", "二", "三"],
        data_version=_VERSION,
        evidence_claim_ids={_CLAIM} if claim_ids is None else claim_ids,
        verified_steps=[_METHOD_STEP, _BASELINE_STEP], plan=plan or _plan())


class QuantOnlyPlanTests(unittest.TestCase):
    """7.1：纯量化计划不强制观点引用；需证据计划仍强制。"""

    def test_quant_only_plan_without_citation_passes(self):
        gate = _gate(_markdown(), plan=_plan(requires_evidence=False))
        self.assertTrue(gate["ok"], "; ".join(gate["errors"]))
        self.assertTrue(any("未引用观点证据" in w for w in gate["warnings"]))

    def test_evidence_plan_without_citation_rejected(self):
        gate = _gate(_markdown(), plan=_plan(method="top_negative_claims",
                                             requires_evidence=True))
        self.assertFalse(gate["ok"])
        self.assertTrue(any("至少需要引用一条" in e for e in gate["errors"]))

    def test_evidence_plan_with_citation_passes(self):
        gate = _gate(_markdown(citation=_CLAIM),
                     plan=_plan(method="top_negative_claims", requires_evidence=True),
                     claim_ids={_CLAIM})
        self.assertTrue(gate["ok"], "; ".join(gate["errors"]))


class ProvenanceBoundaryTests(unittest.TestCase):
    """7.2：元数字不入可比来源；叙述数字清洗；展示舍入。"""

    def test_sql_metadata_numbers_not_usable(self):
        step = {"kind": "method", "method": "negative_share_by_aspect", "aspect": None,
                "verification": {"ok": True},
                "result": {"rows": [{"aspect": "可靠性与故障", "negative_share": 0.551}],
                           "sql": "SELECT ... LIMIT 16", "elapsed_ms": 123,
                           "row_count": 1, "params": {"limit": 16}}}
        md = _markdown().replace("55.1%", "55.1%。本方法最多返回 16 行")
        gate = report_gate.validate_submission(
            title="可靠性报告", markdown=md, key_findings=["一", "二", "三"],
            data_version=_VERSION, evidence_claim_ids=set(),
            verified_steps=[step], plan=_plan(method="negative_share_by_aspect"))
        self.assertFalse(gate["ok"], "SQL/耗时元数字不得充当溯源依据")
        self.assertTrue(any("16" in e for e in gate["errors"] if "未在分析工具结果中找到" in e))

    def test_narrative_numbers_cleaned(self):
        md = _markdown().replace(
            "55.1%（全量声明级口径）",
            "55.1%（全量声明级口径）。观察截至 10 月 28 日，近 3 月排名第 1 的议题未见变化")
        gate = _gate(md)
        self.assertEqual([e for e in gate["errors"] if "未在分析工具结果中找到" in e], [],
                         "叙述数字被误判：" + "; ".join(gate["errors"]))

    def test_display_rounding_accepted_and_misrounding_rejected(self):
        step = {"kind": "method", "method": "aspect_scope_compare", "aspect": "可靠性与故障",
                "verification": {"ok": True},
                "result": {"rows": [{"aspect": "可靠性与故障", "negative_share": 0.203125}]}}
        md = _markdown().replace("55.1%", "20.3%").replace("20.3%（全量", "占 20%（全量")
        # 20% 整数百分数不在容差内（0.20 vs 0.203125 差 0.0031 > 0.0005）
        gate = report_gate.validate_submission(
            title="可靠性报告", markdown=md, key_findings=["一", "二", "三"],
            data_version=_VERSION, evidence_claim_ids=set(),
            verified_steps=[step], plan=_plan())
        self.assertFalse(gate["ok"], "整数百分数 20% 不应通过 0.203125 的溯源")
        md2 = _markdown().replace("55.1%", "占比 0.2（全量声明级口径）")
        gate2 = report_gate.validate_submission(
            title="可靠性报告", markdown=md2, key_findings=["一", "二", "三"],
            data_version=_VERSION, evidence_claim_ids=set(),
            verified_steps=[step], plan=_plan())
        self.assertEqual([e for e in gate2["errors"] if "未在分析工具结果中找到" in e], [],
                         "展示舍入 0.2 应通过 0.203125 溯源：" + "; ".join(gate2["errors"]))
        md3 = md2.replace("占比 0.2（全量", "占比 0.24（全量")
        gate3 = report_gate.validate_submission(
            title="可靠性报告", markdown=md3, key_findings=["一", "二", "三"],
            data_version=_VERSION, evidence_claim_ids=set(),
            verified_steps=[step], plan=_plan())
        self.assertTrue(any("0.24" in e for e in gate3["errors"] if "未在分析工具结果中找到" in e),
                        "0.24 不得通过 0.203125 的舍入判定")


class EmptyResultExplanationTests(unittest.TestCase):
    """7.3：空结果解释的同义表述与全表空路径。"""

    _EMPTY = {"kind": "method", "method": "aspect_scope_compare", "aspect": "可靠性与故障",
              "verification": {"ok": True, "empty_result": True}, "result": {"rows": []}}

    def test_synonym_wording_accepted(self):
        gate = report_gate.validate_submission(
            title="可靠性报告", markdown=_markdown(
                citation=_CLAIM,
                limits="分析主体：小米/SU7。可靠性与故障议题未返回结果，已在分析中覆盖。"),
            key_findings=["一", "二", "三"], data_version=_VERSION,
            evidence_claim_ids={_CLAIM}, verified_steps=[self._EMPTY, _BASELINE_STEP],
            plan=_plan())
        self.assertEqual([e for e in gate["errors"] if "为空" in e], [],
                         "同义表述被误拒：" + "; ".join(gate["errors"]))

    def test_table_empty_explained_by_method_name(self):
        step = dict(self._EMPTY, aspect=None)
        gate = report_gate.validate_submission(
            title="可靠性报告", markdown=_markdown(
                citation=_CLAIM,
                limits="分析主体：小米/SU7。aspect_scope_compare 查询未返回结果。"),
            key_findings=["一", "二", "三"], data_version=_VERSION,
            evidence_claim_ids={_CLAIM}, verified_steps=[step, _BASELINE_STEP],
            plan=_plan())
        self.assertEqual([e for e in gate["errors"] if "为空" in e], [],
                         "全表空结果仍被死锁拒绝：" + "; ".join(gate["errors"]))

    def test_unexplained_empty_still_rejected(self):
        gate = report_gate.validate_submission(
            title="可靠性报告", markdown=_markdown(citation=_CLAIM),
            key_findings=["一", "二", "三"], data_version=_VERSION,
            evidence_claim_ids={_CLAIM}, verified_steps=[self._EMPTY, _BASELINE_STEP],
            plan=_plan())
        self.assertTrue(any("为空" in e for e in gate["errors"]))


class GateMiscConsistencyTests(unittest.TestCase):
    """7.3/7.4：hash 上下文、章节行首匹配、key_findings 下限、预算不重复扣费。"""

    def test_hash_context_hex_not_treated_as_claim(self):
        md = _markdown(citation=_CLAIM).replace("数据版本：", f"快照 hash 前 20 位：{_HASH20}。数据版本：")
        gate = _gate(md)
        self.assertEqual([e for e in gate["errors"] if "未返回的 claim_id" in e], [],
                         "hash 被误判为未知 claim_id：" + "; ".join(gate["errors"]))

    def test_section_requires_line_start(self):
        md = _markdown().replace("## 结论摘要\n", "")
        md = md.replace("本报告为纯量化分析", "本报告包含结论摘要字样但不设该章节。纯量化分析")
        gate = _gate(md)
        self.assertTrue(any("缺少章节：结论摘要" in e for e in gate["errors"]))

    def test_findings_lower_bound_follows_workstream_count(self):
        gate = _gate(_markdown(), plan=_plan(), key_findings=["仅一条结论"])
        self.assertTrue(gate["ok"], "; ".join(gate["errors"]))
        gate2 = _gate(_markdown(), plan=_plan(), key_findings=[str(i) for i in range(6)])
        self.assertTrue(any("关键结论必须为" in e for e in gate2["errors"]))

    def test_length_error_reports_current_size(self):
        md = _markdown() + "补" * (report_gate_config_length() )
        gate = _gate(md)
        self.assertTrue(any("当前" in e for e in gate["errors"] if "超过" in e))

    def test_gate_rejection_does_not_burn_tool_error_budget(self):
        context = {"interactive": True, "submissions": [], "code_failures": {},
                   "verified_steps": [_METHOD_STEP, _BASELINE_STEP,
                                      {"kind": "method", "method": "top_negative_claims",
                                       "aspect": "可靠性与故障",
                                       "verification": {"ok": True},
                                       "result": {"rows": [
                                           {"claim_id": "a" * 20, "quote": "x"}]}},
                                      {"kind": "evidence", "aspect": "可靠性与故障",
                                       "claim_ids": ["a" * 20],
                                       "result": {"data": [{"claim_id": "a" * 20}]}},
                                      ], "evidence_claim_ids": {"a" * 20},
                   "tool_errors": 0, "successful_tool_calls": 0,
                   "submit_attempts": 0,
                   "plan": _plan(method="top_negative_claims", requires_evidence=True)}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        payload = json.loads(tools["submit_report"].invoke({
            "title": "可靠性报告", "markdown": _markdown(),  # 缺证据引用但计划需证据 → 拒
            "key_findings": json.dumps(["一", "二", "三"], ensure_ascii=False)}))
        self.assertEqual(payload.get("error"), "report_gate_failed", payload)
        self.assertEqual(context["tool_errors"], 0, "gate 拒绝不应消耗工具错误预算")
        self.assertEqual(context["gate_rejections"], 1)

    def test_gate_rejection_count_survives_kernel_context(self):
        """auto-041：经字典桥写入后，内核侧 metrics 必须反映真实拒绝次数。"""
        from kernel.context import RunContext
        from kernel.profile import DELIVERABLE

        ctx = RunContext(budget=DELIVERABLE.budget, interactive=True,
                         plan=_plan(method="top_negative_claims", requires_evidence=True))
        for step in (_METHOD_STEP, _BASELINE_STEP,
                     {"kind": "method", "method": "top_negative_claims",
                      "aspect": "可靠性与故障", "verification": {"ok": True},
                      "result": {"rows": [{"claim_id": "a" * 20, "quote": "x"}]}},
                     {"kind": "evidence", "aspect": "可靠性与故障",
                      "claim_ids": ["a" * 20],
                      "result": {"data": [{"claim_id": "a" * 20}]}}):
            ctx.record_step(step)
        ctx.evidence_ids = {"a" * 20}
        tools = {t.name: t for t in agent_tools.build_tools(ctx.tool_context())}
        payload = json.loads(tools["submit_report"].invoke({
            "title": "可靠性报告", "markdown": _markdown(),
            "key_findings": json.dumps(["一", "二", "三"], ensure_ascii=False)}))
        self.assertEqual(payload.get("error"), "report_gate_failed", payload)
        self.assertEqual(ctx.tool_errors, 0)
        self.assertEqual(ctx.tool_context()["gate_rejections"], 1)
        self.assertEqual(ctx.metrics()["gate_rejections"], 1)


def report_gate_config_length():
    import config
    return config.REPORT_MAX_CHARS + 1


if __name__ == "__main__":
    unittest.main()
