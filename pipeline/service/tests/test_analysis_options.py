"""auto-031 backend: form options, aspects preview, schema v2, chart data.

Deterministic tests over the frozen snapshot; no LLM, no network.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import clarify
import agent_tools
import jobs
import report_gate
import report_session
import task_brief
from research import service

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_tools
import report_gate
import task_brief
from research import service

BASELINE_STEP = {"kind": "baseline", "aspect": None,
                 "result": {"rows": [{"aspect": "充电与补能", "negative_share": 0.203125}]}}


class FormOptionsTests(unittest.TestCase):
    """1.1：选项目录与简报覆盖声明同源；时间窗口全部落在覆盖区间内。"""

    @classmethod
    def setUpClass(cls):
        cls.options = task_brief.form_options()

    def test_subjects_only_open_subject(self):
        subjects = self.options["subjects"]
        self.assertEqual([s["value"] for s in subjects], ["小米/SU7"])
        self.assertTrue(subjects[0]["open"])

    def test_time_windows_within_coverage_and_increasing(self):
        coverage = self.options["coverage"]
        windows = self.options["time_windows"]
        for window in windows:
            self.assertGreaterEqual(window["start"], coverage["date_min"])
            self.assertLessEqual(window["end"], coverage["date_max"])
        self.assertEqual(windows[-1]["key"], "all")
        self.assertEqual(windows[-1]["start"], coverage["date_min"])

    def test_coverage_metadata_present(self):
        coverage = self.options["coverage"]
        self.assertIn("version", coverage)
        self.assertIn("brand_scope_note", coverage)


class AspectsPreviewTests(unittest.TestCase):
    """1.3：按议题探索预览三段数据 + 口径标注 + 非法议题报错。"""

    def test_preview_known_aspect(self):
        known = sorted(service._known_aspects())
        out = service.aspects_preview(known[:2])
        self.assertEqual(out["n_aspects"], 2)
        for item in out["aspects"]:
            self.assertIn("sample_size", item)
            self.assertIn("support_insufficient", item)
            self.assertIsInstance(item["monthly_counts"], list)
            for row in item["monthly_counts"]:
                self.assertRegex(row["month"], r"^\d{4}-\d{2}$")
            for rep in item["representative"]:
                self.assertEqual(len(rep["claim_id"]), 20)
        self.assertIn("精选口径", out["caliber"])
        self.assertEqual(out["support_threshold"], 5)

    def test_unknown_aspect_raises(self):
        with self.assertRaises(ValueError):
            service.aspects_preview(["不存在的议题"])

    def test_tool_path_with_aspects_param(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0, "successful_tool_calls": 0}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        known = sorted(service._known_aspects())
        payload = json.loads(tools["semantic_overview"].invoke(
            {"aspects": json.dumps(known[:1], ensure_ascii=False)}))
        self.assertEqual(payload["aspects"][0]["aspect"], known[0])

    def test_tool_path_rejects_bad_params(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0, "successful_tool_calls": 0}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        for bad in ("not json", "[]", '["不存在的议题"]', '{"a":1}'):
            payload = json.loads(tools["semantic_overview"].invoke({"aspects": bad}))
            self.assertIn("error", payload, bad)

    def test_tool_path_without_param_keeps_legacy_overview(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0, "successful_tool_calls": 0}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        payload = json.loads(tools["semantic_overview"].invoke({}))
        self.assertIn("metrics", payload)
        self.assertIn("usage", payload)


def _plan_context(plan: dict) -> dict:
    return {"interactive": True, "submissions": [], "verified_steps": [],
            "evidence_claim_ids": set(), "code_failures": {},
            "tool_errors": 0, "successful_tool_calls": 0, "plan": plan}


def _submit_plan(plan: dict) -> dict:
    context = {"interactive": True, "submissions": [], "verified_steps": [],
               "evidence_claim_ids": set(), "code_failures": {},
               "tool_errors": 0, "successful_tool_calls": 0}
    tools = {t.name: t for t in agent_tools.build_tools(context)}
    return json.loads(tools["submit_analysis_plan"].invoke({"plan_json": json.dumps(plan, ensure_ascii=False)}))


class SchemaV2PlanTests(unittest.TestCase):
    """2.1/2.2：visualization 校验、旧计划兼容、大纲投影。"""

    BASE = {"coverage": "c", "use_python": False,
            "workstreams": [{"id": "w1", "question": "q", "aspect": None,
                             "method": "semantic_aggregate",
                             "params": {"metrics": ["negativeShare"],
                                        "filters": {"aspect": "充电与补能"}},
                             "requires_evidence": False}]}

    def test_valid_visualization_normalized(self):
        plan = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        plan["workstreams"][0]["visualization"] = {
            "type": "bar", "x": "aspect", "y": "negative_share", "title": "各议题负面占比"}
        payload = _submit_plan(plan)
        self.assertTrue(payload["accepted"])
        stored_viz = payload["plan"]["workstreams"][0]["visualization"]
        self.assertEqual(stored_viz, {"type": "bar", "x": "aspect",
                                      "y": "negative_share", "title": "各议题负面占比"})

    def test_invalid_visualization_type_rejected(self):
        plan = json.loads(json.dumps(self.BASE, ensure_ascii=False))
        plan["workstreams"][0]["visualization"] = {"type": "3d-surface"}
        payload = _submit_plan(plan)
        self.assertIn("error", payload)
        self.assertIn("bar/line/pie/table", json.dumps(payload, ensure_ascii=False))

    def test_legacy_plan_without_visualization_still_accepted(self):
        payload = _submit_plan(json.loads(json.dumps(self.BASE, ensure_ascii=False)))
        self.assertTrue(payload["accepted"])

    def test_outline_projection_shape(self):
        plan = {"workstreams": [
            {"id": "w1", "question": "负面分布", "aspect": "充电与补能",
             "method": "negative_share_by_aspect", "requires_evidence": False,
             "visualization": {"type": "bar", "title": "负面占比图"}},
            {"id": "w2", "question": "原文引证", "aspect": "充电与补能",
             "method": "top_negative_claims", "requires_evidence": True}]}
        items = task_brief.outline_projection(plan)
        self.assertEqual([i["order"] for i in items], [1, 2])
        self.assertEqual(items[0]["visualization"],
                         {"type": "bar", "title": "负面占比图"})
        self.assertIsNone(items[1]["visualization"])


class ChartDataTests(unittest.TestCase):
    """3.1/3.2：python_analyze 的 chart 键透传/降级；图表数值并入数字溯源。"""

    def _invoke_python(self, code: str) -> tuple[dict, dict]:
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "code_failures": {},
                   "tool_errors": 0, "successful_tool_calls": 0,
                   "plan": {"use_python": True, "workstreams": []}}
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        payload = json.loads(tools["python_analyze"].invoke({"code": code}))
        return payload, context

    def test_valid_chart_passes_through_and_recorded(self):
        code = ("rows = frames.metrics.to_dict('records')[:2]\n"
                "result = {'count': len(rows)}\n"
                "chart = {'type': 'bar', 'title': '占比', 'x_label': '议题', "
                "'y_label': '负面占比', 'data': "
                "[{'x': r['aspect'], 'y': r['negative_share']} for r in rows]}")
        payload, context = self._invoke_python(code)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertIn("chart", payload)
        self.assertEqual(payload["chart"]["type"], "bar")
        python_steps = [s for s in context["verified_steps"] if s.get("kind") == "python"]
        self.assertIn("chart", (python_steps[-1].get("result") or {}))

    def test_invalid_chart_type_dropped_with_warning(self):
        code = ("result = 1\n"
                "chart = {'type': 'hologram', 'title': 'x', 'data': []}")
        payload, _ = self._invoke_python(code)
        self.assertTrue(payload["ok"])
        self.assertNotIn("chart", payload)
        self.assertIn("chart_invalid_dropped", payload.get("warnings", []))

    def test_missing_title_dropped(self):
        code = "result = 1\nchart = {'type': 'bar', 'data': []}"
        payload, _ = self._invoke_python(code)
        self.assertTrue(payload["ok"])
        self.assertNotIn("chart", payload)
        self.assertIn("chart_invalid_dropped", payload.get("warnings", []))

    def test_chart_numbers_count_as_provenance(self):
        """3.2：图表数值在分析结果里 → 报告引用通过；编造数值被拒。"""
        chart_step = {"kind": "python", "result": {"ok": True,
                      "chart": {"type": "bar", "title": "占比",
                                "data": [{"x": "充电与补能", "y": 0.203125}]}}}
        evidence_step = {"kind": "method", "aspect": "充电与补能",
                         "verification": {"ok": True},
                         "result": {"rows": [{"claim_id": "abcdefabcdefabcdef01"}]}}
        markdown = ("# 报告\n\n## 结论摘要\n图表显示 0.203125。\n\n"
                    "## 证据与归组\n依据 abcdefabcdefabcdef01。\n\n## 限制与不确定性\n"
                    "分析主体：小米/SU7。\n\n数据版本：V2.3")
        steps = [BASELINE_STEP, chart_step, evidence_step]
        gate = report_gate.validate_submission(
            title="t", markdown=markdown, key_findings=["一", "二", "三"],
            data_version="V2.3", evidence_claim_ids={"abcdefabcdefabcdef01"},
            verified_steps=steps)
        self.assertTrue(gate["ok"], gate["errors"])
        forged = markdown.replace("0.203125", "0.777")
        gate = report_gate.validate_submission(
            title="t", markdown=forged, key_findings=["一", "二", "三"],
            data_version="V2.3", evidence_claim_ids={"abcdefabcdefabcdef01"},
            verified_steps=steps)
        self.assertFalse(gate["ok"])


class AnalysisOptionsEndpointTests(unittest.TestCase):
    """1.2：GET /api/analysis/options 与简报覆盖声明一致。"""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_options_endpoint_matches_brief_coverage(self):
        with urllib.request.urlopen(self.base + "/api/analysis/options") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        coverage = task_brief.snapshot_coverage()
        self.assertEqual([s["value"] for s in payload["subjects"]], ["小米/SU7"])
        self.assertEqual(payload["coverage"]["version"], coverage["version"])
        for window in payload["time_windows"]:
            self.assertGreaterEqual(window["start"], str(coverage["date_min"])[:10])
            self.assertLessEqual(window["end"], str(coverage["date_max"])[:10])
