"""auto-034 tests: deterministic SVG chart rendering for published reports."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report_charts
import report_publisher


def _meta_with_plan(workstreams: list[dict]) -> dict:
    return {"title": "t", "data_version": "v", "snapshot_hash": "h",
            "status": "published", "analysis_plan": {"workstreams": workstreams}}


class ChartsForTests(unittest.TestCase):
    """charts_for: plan intent → verified numbers → svg; no data → skipped."""

    def test_bar_chart_from_method_rows(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "各议题负面占比", "method": "negative_share_by_aspect",
            "aspect": None, "requires_evidence": False,
            "visualization": {"type": "bar", "x": "aspect", "y": "negative_share",
                              "title": "各议题负向观点占比"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "negative_share_by_aspect", "aspect": None,
             "verification": {"ok": True},
             "result": {"rows": [
                 {"aspect": "可靠性与故障", "negative_share": 0.551},
                 {"aspect": "服务与交付", "negative_share": 0.470}]}}]}
        charts = report_charts.charts_for(meta, provenance)
        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0]["title"], "各议题负向观点占比")
        self.assertIn("<svg", charts[0]["svg"])
        self.assertIn("viewBox=\"0 0", charts[0]["svg"])  # 窄容器等比缩放，不裁剪
        self.assertEqual(charts[0]["svg"].count("<rect"), 2)
        self.assertIn("55.1%", charts[0]["svg"])

    def test_line_chart_from_python_chart(self):
        meta = _meta_with_plan([{
            "id": "w2", "question": "月度走势", "method": "negative_claims_by_month",
            "aspect": "可靠性与故障", "requires_evidence": False,
            "visualization": {"type": "line", "x": "month", "y": "negative_claims",
                              "title": "月度走势"}}])
        provenance = {"verified_steps": [
            {"kind": "python", "result": {"ok": True,
             "chart": {"type": "line", "title": "月度走势",
                       "data": [{"x": "2024-03", "y": 1}, {"x": "2024-04", "y": 3}]}}}]}
        charts = report_charts.charts_for(meta, provenance)
        self.assertEqual(len(charts), 1)
        self.assertIn("<polyline", charts[0]["svg"])

    def test_missing_verified_step_skips_chart(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "q", "method": "negative_share_by_aspect",
            "visualization": {"type": "bar", "title": "占比"}}])
        self.assertEqual(report_charts.charts_for(meta, {"verified_steps": []}), [])

    def test_non_numeric_rows_skip_chart(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "q", "method": "snapshot_overview",
            "visualization": {"type": "bar", "title": "占比"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "snapshot_overview", "verification": {"ok": True},
             "result": {"rows": [{"key": "a", "value": "text"}]}}]}
        self.assertEqual(report_charts.charts_for(meta, provenance), [])

    def test_pie_chart_from_rows(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "情感构成", "method": "semantic_aggregate",
            "aspect": None, "requires_evidence": False,
            "visualization": {"type": "pie", "x": "sentiment", "y": "claims",
                              "title": "情感构成"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "semantic_aggregate", "aspect": None,
             "verification": {"ok": True},
             "result": {"rows": [{"sentiment": "负面", "claims": 60},
                                 {"sentiment": "正面", "claims": 40}]}}]}
        charts = report_charts.charts_for(meta, provenance)
        self.assertEqual(len(charts), 1)
        self.assertIn("<path", charts[0]["svg"])
        self.assertIn("60.0%", charts[0]["svg"])

    def test_semantic_camel_case_metric_matches_y(self):
        """语义层指标名（negativeShare）可与声明的 y 对齐，不因驼峰/下划线差异跳过。"""
        meta = _meta_with_plan([{
            "id": "w1", "question": "各议题负面占比", "method": "semantic_aggregate",
            "aspect": None, "requires_evidence": False,
            "visualization": {"type": "bar", "x": "aspect", "y": "negativeShare",
                              "title": "各议题负面观点占比"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "semantic_aggregate", "aspect": None,
             "verification": {"ok": True},
             "result": {"rows": [{"aspect": "可靠性与故障", "negativeShare": 0.551}]}}]}
        charts = report_charts.charts_for(meta, provenance)
        self.assertEqual(len(charts), 1)
        self.assertIn("55.1%", charts[0]["svg"])

    def test_semantic_field_in_fallbacks_without_explicit_y(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "q", "method": "semantic_aggregate",
            "visualization": {"type": "bar", "title": "占比"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "semantic_aggregate", "aspect": None,
             "verification": {"ok": True},
             "result": {"rows": [{"aspect": "a", "negativeShare": 0.5}]}}]}
        charts = report_charts.charts_for(meta, provenance)
        self.assertEqual(len(charts), 1)

    def test_table_type_not_rendered_as_image(self):
        meta = _meta_with_plan([{
            "id": "w1", "question": "q", "method": "negative_share_by_aspect",
            "visualization": {"type": "table", "title": "占比表"}}])
        provenance = {"verified_steps": [
            {"kind": "method", "method": "negative_share_by_aspect", "verification": {"ok": True},
             "result": {"rows": [{"aspect": "a", "negative_share": 0.5}]}}]}
        self.assertEqual(report_charts.charts_for(meta, provenance), [])

    def test_report_outcome_delivers_charts(self):
        """job 结果应附带 charts（前端报告视图的图表来源，auto-034 2.8）。"""
        import agent_engine
        context = {"submissions": [{"report_id": "x" * 12, "title": "t",
                                    "report_md": "# 报告", "key_findings": [],
                                    "status": "pending_review", "data_version": "v"}],
                   "verified_steps": [
                       {"kind": "method", "method": "negative_share_by_aspect",
                        "aspect": None, "verification": {"ok": True},
                        "result": {"rows": [
                            {"aspect": "可靠性与故障", "negative_share": 0.551}]}},
                       {"kind": "evidence", "aspect": "可靠性与故障",
                        "claim_ids": ["b" * 20]}],
                   "plan": {"coverage": "c", "workstreams": [{
                       "id": "w1", "question": "各议题负面占比",
                       "method": "negative_share_by_aspect", "aspect": None,
                       "requires_evidence": False,
                       "visualization": {"type": "bar", "x": "aspect",
                                         "y": "negative_share",
                                         "title": "各议题负向观点占比"}}]},
                   "tool_errors": 0, "successful_tool_calls": 2,
                   "code_failures": {}, "gate_rejections": 0, "submit_attempts": 1}
        state = {"messages": [types.SimpleNamespace(content="已完成")]}
        result = agent_engine.report_outcome(context, state, "问题", 0.0)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["charts"]), 1)
        self.assertIn("<svg", result["charts"][0]["svg"])

    def test_report_outcome_without_viz_intent_has_empty_charts(self):
        import agent_engine
        context = {"submissions": [{"report_id": "x" * 12, "title": "t",
                                    "report_md": "# 报告", "key_findings": [],
                                    "status": "pending_review", "data_version": "v"}],
                   "verified_steps": [
                       {"kind": "method", "method": "negative_share_by_aspect",
                        "aspect": None, "verification": {"ok": True},
                        "result": {"rows": [{"aspect": "a", "negative_share": 0.5}]}}],
                   "plan": {"coverage": "c", "workstreams": [{
                       "id": "w1", "question": "q",
                       "method": "negative_share_by_aspect", "aspect": None,
                       "requires_evidence": False}]},
                   "tool_errors": 0, "successful_tool_calls": 1,
                   "code_failures": {}, "gate_rejections": 0, "submit_attempts": 1}
        state = {"messages": [types.SimpleNamespace(content="已完成")]}
        result = agent_engine.report_outcome(context, state, "问题", 0.0)
        self.assertEqual(result["charts"], [])


class RenderHtmlChartTests(unittest.TestCase):
    """render_published_html embeds charts anchored to matching sections."""

    PLAN_WORKSTREAM = {
        "id": "w1", "question": "各议题负面占比", "method": "negative_share_by_aspect",
        "aspect": None, "requires_evidence": False,
        "visualization": {"type": "bar", "x": "aspect", "y": "negative_share",
                          "title": "各议题负向观点占比"}}
    PROVENANCE = {"verified_steps": [
        {"kind": "method", "method": "negative_share_by_aspect", "aspect": None,
         "verification": {"ok": True},
         "result": {"rows": [{"aspect": "可靠性与故障", "negative_share": 0.551}]}}]}

    def test_chart_embedded_after_matching_section(self):
        markdown = ("# 报告\n\n## 结论摘要\n结论。\n\n## 分项事实\n"
                    "表：各议题负向观点占比\n\n## 限制与不确定性\n分析主体：小米/SU7。")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher, "LATEST_FILE", Path(tmp) / "latest.json"), \
                 mock.patch.object(report_publisher.service, "snapshot_version", return_value="v"), \
                 mock.patch.object(report_publisher.service, "snapshot_hash", return_value="h"):
                directory = Path(tmp) / "a1b2c3d4e5f6"
                directory.mkdir()
                (directory / "report.md").write_text(markdown, encoding="utf-8")
                (directory / "provenance.json").write_text(
                    json.dumps(self.PROVENANCE), encoding="utf-8")
                (directory / "meta.json").write_text(json.dumps(
                    {**_meta_with_plan([self.PLAN_WORKSTREAM]),
                     "report_id": "a1b2c3d4e5f6", "review": {}}), encoding="utf-8")
                (Path(tmp) / "latest.json").write_text(
                    json.dumps({"report_id": "a1b2c3d4e5f6"}), encoding="utf-8")
                html_out = report_publisher.render_published_html()
        self.assertIsNotNone(html_out)
        self.assertIn("figure class=\"report-chart\"", html_out)
        self.assertIn("<svg", html_out)
        # 图表锚在包含标题文本的元素之后，而不是文末附录
        anchor_pos = html_out.find("各议题负向观点占比")
        figure_pos = html_out.find("figure class=\"report-chart\"")
        self.assertGreater(figure_pos, anchor_pos)
        self.assertLess(figure_pos, html_out.find("限制与不确定性"))

    def test_orphan_chart_appended(self):
        markdown = "# 报告\n\n## 结论摘要\n结论。\n\n## 限制与不确定性\n分析主体：小米/SU7。"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher, "LATEST_FILE", Path(tmp) / "latest.json"), \
                 mock.patch.object(report_publisher.service, "snapshot_version", return_value="v"), \
                 mock.patch.object(report_publisher.service, "snapshot_hash", return_value="h"):
                directory = Path(tmp) / "a1b2c3d4e5f6"
                directory.mkdir()
                (directory / "report.md").write_text(markdown, encoding="utf-8")
                (directory / "provenance.json").write_text(
                    json.dumps(self.PROVENANCE), encoding="utf-8")
                (directory / "meta.json").write_text(json.dumps(
                    {**_meta_with_plan([self.PLAN_WORKSTREAM]),
                     "report_id": "a1b2c3d4e5f6", "review": {}}), encoding="utf-8")
                (Path(tmp) / "latest.json").write_text(
                    json.dumps({"report_id": "a1b2c3d4e5f6"}), encoding="utf-8")
                html_out = report_publisher.render_published_html()
        self.assertIn("<h2>图表</h2>", html_out)


class CitationDecorateTests(unittest.TestCase):
    """发布视图：正文 claim_id 折叠为 [n] 角标 + 文末证据清单（auto-034 2.14）。"""

    def test_claim_ids_folded_with_footnotes(self):
        claim = "a" * 20
        markdown = (f"# 报告\n\n## 证据与归组\n交付等待漫长（claim_id: {claim}）。\n\n"
                    "## 限制与不确定性\n分析主体：小米/SU7。")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher, "LATEST_FILE", Path(tmp) / "latest.json"), \
                 mock.patch.object(report_publisher.service, "snapshot_version", return_value="v"), \
                 mock.patch.object(report_publisher.service, "snapshot_hash", return_value="h"), \
                 mock.patch.object(report_publisher.service, "evidence_details",
                                   return_value={"details": [
                                       {"claim_id": claim, "found": True,
                                        "url": "https://example.com/t/1", "date": "2026-01-02",
                                        "title": "等车三个月", "aspect": "服务与交付"}],
                                       "n_requested": 1, "n_found": 1,
                                       "data_version": "v", "snapshot_hash": "h"}):
                directory = Path(tmp) / "a1b2c3d4e5f6"
                directory.mkdir()
                (directory / "report.md").write_text(markdown, encoding="utf-8")
                (directory / "provenance.json").write_text(json.dumps(
                    {"verified_steps": [], "evidence_claim_ids": [claim]}), encoding="utf-8")
                (directory / "meta.json").write_text(json.dumps(
                    {"report_id": "a1b2c3d4e5f6", "title": "t", "status": "published",
                     "data_version": "v", "snapshot_hash": "h",
                     "analysis_plan": {"workstreams": []}, "review": {}}), encoding="utf-8")
                (Path(tmp) / "latest.json").write_text(
                    json.dumps({"report_id": "a1b2c3d4e5f6"}), encoding="utf-8")
                html_out = report_publisher.render_published_html()
        self.assertIsNotNone(html_out)
        self.assertNotIn("claim_id:", html_out)  # 正文不再裸露 hex
        self.assertIn('<sup class="cite-ref">[1]</sup>', html_out)
        self.assertIn("evidence-footnotes", html_out)
        self.assertIn("https://example.com/t/1", html_out)


if __name__ == "__main__":
    unittest.main()
