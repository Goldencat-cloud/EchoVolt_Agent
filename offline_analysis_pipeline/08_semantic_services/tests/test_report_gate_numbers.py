"""Bug repro: report_gate counts decimal section numbers (2.1/2.2) as data numbers.

复现截图 bug 的根因：Agent 用「### 2.1 标题」式小节编号撰写长报告时，
report_gate 的数字溯源把 2.1/2.2 当成未溯源统计数字拒绝提交；
3 次提交机会耗尽后（submit_attempt_limit）无过审报告，job failed，
前端呈现「深度分析未完成」。E2E 证据：data/e2e-runs/20261028-210531-repro
（第一次 submit_report 被拒，未溯源数字含 2.1, 2.2, 2.3, 2.4…）。
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
_BASELINE_STEP = {"kind": "baseline", "method": "baseline", "aspect": None,
                  "verification": {"ok": True},
                  "rows": [{"aspect": "可靠性与故障", "claims": 98, "negative": 54,
                            "negative_share": 0.551}]}
_MONTH_STEP = {"kind": "method", "method": "negative_claims_by_month",
               "aspect": "可靠性与故障", "verification": {"ok": True},
               "result": {"rows": [{"month": "2024-03", "n": 1},
                                   {"month": "2024-04", "n": 3}]}}


def _plan() -> dict:
    return {"use_python": False, "workstreams": [
        {"id": "w1", "question": "月度走势", "dimension": "time",
         "aspect": "可靠性与故障", "method": "negative_claims_by_month",
         "requires_evidence": False}]}


def _markdown() -> str:
    version = service.snapshot_version()
    return (
        "# 报告\n\n## 结论摘要\n可靠性与故障月度负面说法分散（2024-03 为 1 条，"
        "2024-04 为 3 条，全量声明级口径）。\n\n"
        "## 归因分析\n\n### 2.1 月度分布不足以判定趋势\n"
        "负面说法合计 4 条，样本量过小。\n\n"
        "### 2.2 未见单月集中爆发\n"
        "各月分布接近长尾。\n\n"
        "## 证据与归组\n引文见 claim_id: " + _CLAIM + "。\n\n"
        "## 限制与不确定性\n分析主体为小米/SU7，其余品牌仅为共现对比信息。\n\n"
        f"数据版本：{version}")


class SectionNumberFalsePositiveTests(unittest.TestCase):
    """小节编号 2.1/2.2 不应被当作报告统计数字做溯源比对。"""

    def _gate(self, markdown: str) -> dict:
        return report_gate.validate_submission(
            title="月度走势报告", markdown=markdown, key_findings=["一", "二", "三"],
            data_version=service.snapshot_version(), evidence_claim_ids={_CLAIM},
            verified_steps=[_BASELINE_STEP, _MONTH_STEP], plan=_plan())

    def test_section_numbers_not_flagged(self):
        gate = self._gate(_markdown())
        numeric_errors = [e for e in gate["errors"] if "未在分析工具结果中找到的数字" in e]
        self.assertEqual(numeric_errors, [],
                         "小节编号被误判为未溯源数字：" + "; ".join(numeric_errors))
        self.assertTrue(gate["ok"], "; ".join(gate["errors"]))

    def test_fabricated_numbers_still_rejected(self):
        bad = _markdown().replace("样本量过小", "样本量过小，占比 63.7%")
        gate = self._gate(bad)
        self.assertFalse(gate["ok"], "编造数字必须仍被拒绝")
        self.assertTrue(any("63.7%" in e for e in gate["errors"]))


class SubmitPathReproTests(unittest.TestCase):
    """submit_report 工具路径复现：小节编号导致 gate 拒绝（修复前应失败）。"""

    def test_submit_with_numbered_headings(self):
        context = {"interactive": True, "submissions": [], "code_failures": {},
                   "verified_steps": [_BASELINE_STEP, _MONTH_STEP],
                   "evidence_claim_ids": {_CLAIM}, "tool_errors": 0,
                   "successful_tool_calls": 0, "submit_attempts": 0,
                   "plan": _plan()}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        payload = json.loads(tools["submit_report"].invoke({
            "title": "月度走势报告", "markdown": _markdown(),
            "key_findings": json.dumps(["一", "二", "三"], ensure_ascii=False)}))
        self.assertNotIn("error", payload,
                         "小节编号触发 gate 拒绝：" + json.dumps(payload, ensure_ascii=False)[:400])
        self.assertTrue(payload.get("report_id"))


if __name__ == "__main__":
    unittest.main()
