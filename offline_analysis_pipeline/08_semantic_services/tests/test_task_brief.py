"""Deterministic tests for the task-brief context refactor (auto-030 8.1-8.3).

Covers: brief content from the real snapshot (coverage/enums/baseline), brand
ladder, trim order, baseline provenance through the report gate, and the
config single-source length limit. No LLM configured.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_engine
import config
from semantic.adapters import compat_views as db_mirror
import report_gate
import task_brief


def make_brief(question="近三个月充电体验的负面反馈为何变多？", aspect=None, **brief):
    con = db_mirror.connect()
    try:
        baseline = agent_engine._baseline(aspect)
        return task_brief.build_task_brief(question, aspect, baseline, brief or None, con)
    finally:
        con.close()


class TaskBriefContentTests(unittest.TestCase):
    """8.1: the brief carries coverage, enums and baseline instead of samples."""

    @classmethod
    def setUpClass(cls):
        cls.brief = make_brief()
        con = db_mirror.connect()
        try:
            cls.coverage = task_brief.snapshot_coverage(con)
            cls.first_aspect = con.execute(
                "SELECT aspect FROM semantic_aspect_metric ORDER BY claims DESC"
            ).fetchone()[0]
            cls.negative_sentiment = con.execute(
                "SELECT sentiment FROM semantic_claim_fact WHERE sentiment = '负面'"
            ).fetchone()
        finally:
            con.close()

    def test_coverage_declaration_present(self):
        self.assertIn("## 数据覆盖声明", self.brief)
        self.assertIn(self.coverage["version"], self.brief)
        self.assertIn(self.coverage["snapshot_hash"], self.brief)
        self.assertIn(str(self.coverage["date_min"]), self.brief)
        self.assertIn(str(self.coverage["date_max"]), self.brief)
        self.assertIn("精选子集", self.brief)
        self.assertIn("kind=baseline", self.brief)

    def test_brand_list_present_and_ladder_default(self):
        self.assertIn("品牌清单", self.brief)
        brand_names = task_brief._brand_names(self.coverage["brands"])
        self.assertTrue(brand_names)
        self.assertIn(brand_names[0], self.brief)

    def test_enums_replaces_sample_rows(self):
        self.assertIn("aspect 取值", self.brief)
        self.assertIn(self.first_aspect, self.brief)
        self.assertIn("sentiment 取值", self.brief)
        self.assertIn("负面", self.brief)
        # The old 3-sample-row JSON dump is gone: no escaped JSON blob opener.
        self.assertNotIn('{"question":', self.brief)
        self.assertNotIn('"overview":', self.brief)
        # Long-text fields are described, not shipped.
        claims_section = self.brief.split("### frames.claims")[1].split("### frames.evidence")[0]
        self.assertIn("不经本简报", claims_section)

    def test_baseline_table_rendered(self):
        self.assertIn("## 预置基准", self.brief)
        if agent_engine._baseline(None).get("rows"):
            self.assertIn("| aspect | negative_share | claims | negative |", self.brief)

    def test_action_block_precedes_dynamic_brief(self):
        message = agent_engine._opening_message("测试问题", None)
        self.assertIn("submit_analysis_plan", message)
        # Cache contract: static action block first, dynamic brief after.
        self.assertLess(message.index("请读取 deep-analysis 技能"),
                        message.index("# 任务简报"))


class TrimTests(unittest.TestCase):
    """8.1: trim order — samples first, baseline rows, enum top-N; never coverage."""

    def test_trim_keeps_coverage_and_shrinks_optional_parts(self):
        full = make_brief()
        with patch.object(config, "BRIEF_MAX_CHARS", 3000):
            trimmed = make_brief()
        self.assertLess(len(trimmed), len(full))
        self.assertIn("## 数据覆盖声明", trimmed)
        self.assertIn("日期范围", trimmed)

    def test_default_brief_within_budget(self):
        self.assertLessEqual(len(make_brief()), config.BRIEF_MAX_CHARS)


class BrandLadderTests(unittest.TestCase):
    """D11 ladder. Current policy (BRAND_MULTI_ENABLED=False): SU7 subject fixed.
    Multi-brand branch is flag-gated for a later change (Owner 2026-10-27)."""

    BRANDS = [("小米", "SU7", 7281), ("特斯拉", "Model 3", 399)]

    def test_subject_brand_pinned_when_unspecified(self):
        result = task_brief.resolve_brand_scope(None, self.BRANDS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["brand"], config.SUBJECT_BRAND)
        self.assertFalse(result["needs_clarification"])
        self.assertIn("固定分析主体", result["note"])

    def test_subject_brand_accepted_in_brand_or_series_form(self):
        self.assertEqual(
            task_brief.resolve_brand_scope("小米", self.BRANDS)["brand"], "小米")
        self.assertEqual(
            task_brief.resolve_brand_scope("小米/SU7", self.BRANDS)["brand"], "小米")

    def test_other_brand_rejected_while_multi_disabled(self):
        result = task_brief.resolve_brand_scope("特斯拉", self.BRANDS)
        self.assertFalse(result["ok"])
        self.assertIn("仅开放", result["note"])
        self.assertIn("小米/SU7", result["note"])

    def test_multi_brand_branch_stays_available_behind_flag(self):
        result = task_brief.resolve_brand_scope(None, self.BRANDS, multi_enabled=True)
        self.assertTrue(result["needs_clarification"])
        self.assertIsNone(result["brand"])
        self.assertIn("小米", result["note"])
        self.assertIn("特斯拉", result["note"])
        self.assertEqual(
            task_brief.resolve_brand_scope("特斯拉", self.BRANDS, multi_enabled=True)["brand"],
            "特斯拉")

    def test_unknown_brand_rejected_with_available_list(self):
        result = task_brief.resolve_brand_scope("蔚来", self.BRANDS, multi_enabled=True)
        self.assertFalse(result["ok"])
        self.assertIn("可用", result["note"])


class BaselineProvenanceGateTests(unittest.TestCase):
    """8.2: baseline numbers pass the gate; foreign numbers still rejected."""

    def _validate(self, markdown, steps):
        return report_gate.validate_submission(
            title="充电体验分析", markdown=markdown,
            key_findings=["结论一", "结论二", "结论三"],
            data_version="V2.3", evidence_claim_ids={"abcdefabcdefabcdef01"},
            verified_steps=steps)

    BASELINE_STEP = {
        "kind": "baseline", "aspect": "充电与补能",
        "rows": [{"aspect": "充电与补能", "negative_share": 0.203125,
                  "claims": 64, "negative": 13}],
        "caliber": "全量声明级口径",
        "verification": {"ok": True, "checks": ["server_precomputed_baseline"]}}
    METHOD_STEP = {
        "kind": "method", "aspect": "充电与补能",
        "verification": {"ok": True},
        "result": {"rows": [{"aspect": "充电与补能", "negative_share": 0.42}]}}

    def test_baseline_numbers_are_reportable(self):
        markdown = (
            "# 报告\n\n## 结论摘要\n充电与补能负面占比 0.203125。\n\n"
            "## 分项事实\n对比值 0.42。\n\n## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n"
            "## 限制与不确定性\n精选子集。分析主体：小米/SU7，其余品牌为共现对比信息。\n\n"
            "## 待验证问题\n快充投诉。\n\n数据版本：V2.3")
        gate = self._validate(markdown, [self.BASELINE_STEP, self.METHOD_STEP])
        self.assertTrue(gate["ok"], gate["errors"])

    def test_foreign_numbers_still_rejected(self):
        markdown = (
            "# 报告\n\n## 结论摘要\n虚假占比 0.777。\n\n"
            "## 分项事实\n对比值 0.42。\n\n## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n"
            "## 限制与不确定性\n精选子集。品牌范围：小米/SU7 主体。\n\n"
            "## 待验证问题\n无。\n\n数据版本：V2.3")
        gate = self._validate(markdown, [self.BASELINE_STEP, self.METHOD_STEP])
        self.assertFalse(gate["ok"])
        self.assertTrue(any("0.777" in error for error in gate["errors"]))

    def test_length_limit_single_source(self):
        self.assertEqual(report_gate.config.REPORT_MAX_CHARS, config.REPORT_MAX_CHARS)
        filler = "#" * (config.REPORT_MAX_CHARS + 1)
        markdown = (
            f"{filler}\n\n## 结论摘要\n0.203125。\n\n## 分项事实\n0.42。\n\n"
            "## 证据与归组\nabcdefabcdefabcdef01。\n\n## 限制与不确定性\n精选子集。"
            "分析主体：小米/SU7。\n\n## 待验证问题\n无。\n\n数据版本：V2.3")
        gate = self._validate(markdown, [self.BASELINE_STEP, self.METHOD_STEP])
        self.assertFalse(gate["ok"])
        self.assertTrue(any("字符" in error for error in gate["errors"]))


class BaselineStepTests(unittest.TestCase):
    """8.2: engine records baseline into the provenance ledger."""

    def test_baseline_step_shape(self):
        step = agent_engine._baseline_step(None, {"rows": [{"aspect": "a"}],
                                                  "caliber": "口径"})
        self.assertEqual(step["kind"], "baseline")
        self.assertTrue(step["verification"]["ok"])
        self.assertEqual(step["rows"], [{"aspect": "a"}])
        self.assertNotIn("result", step)


class BrandScopeDeclarationGateTests(unittest.TestCase):
    """8.7 剩余：gate 确定性检查——正文必须含品牌范围声明（D11）。"""

    STEP = {"kind": "method", "aspect": "充电与补能", "verification": {"ok": True},
            "result": {"rows": [{"aspect": "充电与补能", "negative_share": 0.42}]}}

    def _markdown(self, declaration: str) -> str:
        return (f"# 报告\n\n## 结论摘要\n占比 0.42。\n\n## 分项事实\n0.42。\n\n"
                f"## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n## 限制与不确定性\n"
                f"精选子集。{declaration}\n\n## 待验证问题\n无。\n\n数据版本：V2.3")

    def _validate(self, markdown):
        return report_gate.validate_submission(
            title="充电体验分析", markdown=markdown,
            key_findings=["结论一", "结论二", "结论三"],
            data_version="V2.3", evidence_claim_ids={"abcdefabcdefabcdef01"},
            verified_steps=[self.STEP])

    def test_missing_declaration_rejected(self):
        gate = self._validate(self._markdown("精选子集边界如实说明。"))
        self.assertFalse(gate["ok"])
        self.assertTrue(any("品牌范围声明" in error for error in gate["errors"]))
        self.assertIn("brand_scope_declaration", gate["checks"])

    def test_subject_mention_without_marker_rejected(self):
        # 提到 SU7 但没有「分析主体/品牌范围」声明字样 → 仍拒绝
        gate = self._validate(self._markdown("SU7 车型表现如上。"))
        self.assertFalse(gate["ok"])

    def test_declaration_with_analysis_subject_marker_passes(self):
        gate = self._validate(self._markdown("分析主体：小米/SU7，其余品牌为共现对比信息。"))
        self.assertTrue(gate["ok"], gate["errors"])

    def test_declaration_with_brand_scope_marker_passes(self):
        gate = self._validate(self._markdown("品牌范围：小米/SU7 主体。"))
        self.assertTrue(gate["ok"], gate["errors"])


class ValidateBriefTests(unittest.TestCase):
    """4.1：brief{topic, brand?, time_window?, compare?} 服务端校验，与简报同源。"""

    @classmethod
    def setUpClass(cls):
        cls.coverage = task_brief.snapshot_coverage()
        cls.window = [str(cls.coverage["date_min"])[:10], str(cls.coverage["date_max"])[:10]]

    def _in_range_window(self) -> str:
        return f"{self.window[0]} ~ {self.window[1]}"

    def _out_of_range_window(self) -> str:
        return "1999-01-01 ~ 1999-12-31"

    def test_none_brief_stays_compatible(self):
        clean, rejection = task_brief.validate_brief(None)
        self.assertIsNone(clean)
        self.assertIsNone(rejection)

    def test_missing_topic_rejected(self):
        clean, rejection = task_brief.validate_brief({"brand": "小米"})
        self.assertIsNone(clean)
        self.assertEqual(rejection["error"], "invalid_brief")
        self.assertIn("topic", rejection["message"])

    def test_time_window_out_of_range_returns_allowed_interval(self):
        clean, rejection = task_brief.validate_brief(
            {"topic": "充电体验", "time_window": self._out_of_range_window()})
        self.assertIsNone(clean)
        self.assertEqual(rejection["error"], "time_window_out_of_range")
        self.assertEqual(rejection["allowed_time_window"], self.window)

    def test_time_window_format_and_order_validated(self):
        _, rejection = task_brief.validate_brief(
            {"topic": "t", "time_window": "去年到今年"})
        self.assertEqual(rejection["error"], "invalid_time_window")
        _, rejection = task_brief.validate_brief(
            {"topic": "t", "time_window": f"{self.window[1]} ~ {self.window[0]}"})
        self.assertEqual(rejection["error"], "invalid_time_window")

    def test_non_open_brand_rejected_with_available_list(self):
        clean, rejection = task_brief.validate_brief({"topic": "t", "brand": "特斯拉"})
        self.assertIsNone(clean)
        self.assertEqual(rejection["error"], "brand_not_available")
        self.assertIn("小米", rejection["allowed_brands"])

    def test_valid_brief_normalized(self):
        clean, rejection = task_brief.validate_brief({
            "topic": "  充电体验  ",
            "brand": "小米/SU7",
            "time_window": self._in_range_window(),
            "compare": "自身历史"})
        self.assertIsNone(rejection)
        self.assertEqual(clean["topic"], "充电体验")
        self.assertEqual(clean["brand"], "小米")
        self.assertEqual(clean["time_window"], self._in_range_window())
        self.assertEqual(clean["compare"], "自身历史")


class ReportLayeringGateTests(unittest.TestCase):
    """8.9：核心三段必填、类型章节注入、内部词禁词、空结果规则（D12）。"""

    STEP = {"kind": "method", "aspect": "充电与补能", "verification": {"ok": True},
            "result": {"rows": [{"aspect": "充电与补能", "negative_share": 0.42}]}}

    def _validate(self, markdown, steps=None, plan=None):
        return report_gate.validate_submission(
            title="充电体验分析", markdown=markdown,
            key_findings=["结论一", "结论二", "结论三"],
            data_version="V2.3", evidence_claim_ids={"abcdefabcdefabcdef01"},
            verified_steps=steps if steps is not None else [self.STEP],
            plan=plan)

    CORE_MD = ("# 报告\n\n## 结论摘要\n占比 0.42。\n\n"
               "## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n"
               "## 限制与不确定性\n精选子集。分析主体：小米/SU7。\n\n数据版本：V2.3")

    def test_core_three_sections_only_without_plan(self):
        # 无 plan 时只要求核心三段；分项事实/待验证问题不再强制
        gate = self._validate(self.CORE_MD)
        self.assertTrue(gate["ok"], gate["errors"])

    def test_missing_core_section_rejected(self):
        markdown = self.CORE_MD.replace("## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n", "")
        gate = self._validate(markdown)
        self.assertFalse(gate["ok"])
        self.assertTrue(any("缺少章节：证据与归组" in e for e in gate["errors"]))

    def test_compare_plan_advises_matrix_section_without_blocking(self):
        # Owner 2026-10-28：对比矩阵/归因分析由问题决定，gate 只建议不阻断
        plan = {"workstreams": [{"id": "w1", "question": "q", "dimension": "product",
                                 "aspect": None, "method": "co_mention_products",
                                 "requires_evidence": False}]}
        gate = self._validate(self.CORE_MD, plan=plan)
        self.assertTrue(gate["ok"], gate["errors"])
        self.assertTrue(any("对比矩阵" in w for w in gate["warnings"]))
        gate = self._validate(self.CORE_MD + "\n\n## 对比矩阵\n共现提及对比。\n", plan=plan)
        self.assertTrue(gate["ok"], gate["errors"])
        self.assertFalse(any("对比矩阵" in w for w in gate["warnings"]))

    def test_trend_plan_advises_attribution_section_without_blocking(self):
        plan = {"workstreams": [{"id": "w1", "question": "q", "dimension": "time",
                                 "aspect": "充电与补能", "method": "negative_claims_by_month",
                                 "requires_evidence": False}]}
        gate = self._validate(self.CORE_MD, plan=plan)
        self.assertTrue(gate["ok"], gate["errors"])
        self.assertTrue(any("归因分析" in w for w in gate["warnings"]))

    def test_banned_internal_terms_rejected_but_claim_citation_allowed(self):
        gate = self._validate(self.CORE_MD + "\n每个 workstream 一节。")
        self.assertFalse(gate["ok"])
        self.assertTrue(any("内部实现词" in e and "workstream" in e for e in gate["errors"]))
        gate = self._validate(self.CORE_MD + "\n典型抱怨（claim_id: abcdefabcdefabcdef01）。")
        self.assertTrue(gate["ok"], gate["errors"])

    def test_empty_result_step_requires_limitation_explanation(self):
        empty_step = {"kind": "method", "aspect": "可靠性与故障",
                      "verification": {"ok": True, "empty_result": True,
                                       "errors": [], "checks": []},
                      "result": {"rows": []}}
        steps = [self.STEP, empty_step]
        gate = self._validate(self.CORE_MD, steps=steps)
        self.assertFalse(gate["ok"])
        self.assertTrue(any("结果为空" in e for e in gate["errors"]))
        explained = self.CORE_MD.replace(
            "## 限制与不确定性\n精选子集。分析主体：小米/SU7。\n",
            "## 限制与不确定性\n精选子集。分析主体：小米/SU7。"
            "可靠性与故障议题查询结果为空，无法得出结论。\n")
        gate = self._validate(explained, steps=steps)
        self.assertTrue(gate["ok"], gate["errors"])





if __name__ == "__main__":
    unittest.main()
