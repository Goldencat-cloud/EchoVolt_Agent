"""Deterministic tests for the semantic aggregate method and its tool wiring.

Covers: capability declarations, catalogue bindings, semantic query equivalence
with direct SQL, caliber and verification contract, plan validation for
``semantic_aggregate`` workstreams and the ``run_semantic_aggregate`` tool.

历史说明（auto-042 1.5）：本文件原以 auto-032 的 ``run_aggregate`` 原语为被测
对象；auto-039 起系统只接受 ``semantic_aggregate``，原语执行路径不再可通过
计划触达。断言意图保留，被测入口改为语义聚合。
"""
import datetime as _dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import catalog as research_catalog
from research import analysis_methods
from semantic.adapters import compat_views as db_mirror
import verifier


class PrimitiveCapabilityTests(unittest.TestCase):
    """Task 1.1: capability declarations drive form options and validation."""

    def test_capability_declarations_present(self):
        caps = research_catalog.primitive_capabilities()
        self.assertEqual(caps.get("date_range_filter"), True)
        self.assertEqual(caps.get("cross_dimension"), True)
        self.assertEqual(caps.get("brand_compare"), False)

    def test_capabilities_snapshot_is_isolated(self):
        caps = research_catalog.primitive_capabilities()
        caps["brand_compare"] = True
        self.assertFalse(research_catalog.primitive_capabilities()["brand_compare"])

    def test_primitive_catalogue_exposes_capabilities(self):
        payload = research_catalog.catalogue()["primitive"]
        self.assertEqual(payload["capabilities"], research_catalog.primitive_capabilities())
        # auto-042：原语退役后这里不再暴露 metric/dimension 绑定表。
        self.assertEqual(set(payload), {"capabilities"})


class MethodCatalogueTests(unittest.TestCase):
    """auto-042：目录只登记真实可声明的方法，不残留已退役方法名。"""

    def test_catalogue_lists_only_semantic_aggregate(self):
        methods = [entry["method"] for entry in analysis_methods.catalogue()]
        self.assertEqual(methods, [analysis_methods.SEMANTIC_METHOD])

    def test_dimension_methods_match_real_methods(self):
        for name, definition in research_catalog.DIMENSIONS.items():
            self.assertEqual(set(definition["methods"]), {analysis_methods.SEMANTIC_METHOD}, name)
        self.assertEqual(set(research_catalog.METHOD_DIMENSIONS),
                         {analysis_methods.SEMANTIC_METHOD})

    def test_research_brief_tracks_new_catalog_version(self):
        brief_path = Path(__file__).resolve().parents[1] / "research-brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        self.assertEqual(brief["catalog_version"], research_catalog.CATALOG_VERSION)
        from research import service
        service.validate_research_brief(brief)


class SemanticExecutionTests(unittest.TestCase):
    """语义聚合：确定性 SQL、口径信封、比值复算与越界拒绝。"""

    @classmethod
    def setUpClass(cls):
        cls.con = db_mirror.connect()
        cls.aspects = analysis_methods.aspects()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _run(self, params):
        return analysis_methods.run(analysis_methods.SEMANTIC_METHOD, params)

    def test_aspect_counts_match_semantic_metric_frame(self):
        """claims 是声明级全量口径，对照同为全量的 semantic_aspect_metric。"""
        result = self._run({"metrics": ["claims"], "dimensions": ["aspect"], "limit": 100})
        self.assertEqual(result["method"], analysis_methods.SEMANTIC_METHOD)
        self.assertIn("模型口径", result["caliber"])
        self.assertTrue(result["rows"])
        for row in result["rows"]:
            direct = self.con.execute(
                "SELECT claims FROM semantic_aspect_metric WHERE aspect = ?",
                (row["aspect"],)).fetchone()[0]
            self.assertEqual(row["claims"], direct)

    def test_negative_share_recomputed_and_verified(self):
        result = self._run({"metrics": ["negativeShare", "negative", "claims"],
                            "dimensions": ["aspect"], "limit": 100})
        self.assertTrue(result["rows"])
        for row in result["rows"]:
            if row["claims"]:
                self.assertAlmostEqual(
                    row["negativeShare"], row["negative"] / row["claims"], places=9)
        verdict = verifier.verify_step(result)
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_dimension_slices_sum_to_filtered_total(self):
        aspect = self.aspects[0]
        total = self._run({"metrics": ["claims"], "filters": {"aspect": aspect}})
        sliced = self._run({"metrics": ["claims"], "dimensions": ["sentiment"],
                            "filters": {"aspect": aspect}, "limit": 100})
        self.assertEqual(sum(r["claims"] for r in sliced["rows"]),
                         total["rows"][0]["claims"])

    def test_cross_dimension_grouping_sums_to_total(self):
        aspect = self.aspects[0]
        total = self._run({"metrics": ["claims"], "filters": {"aspect": aspect}})
        result = self._run({"metrics": ["claims"], "dimensions": ["sentiment", "journey"],
                            "filters": {"aspect": aspect}, "limit": 100})
        self.assertTrue(result["rows"])
        self.assertEqual(sum(r["claims"] for r in result["rows"]),
                         total["rows"][0]["claims"])
        verdict = verifier.verify_step(result)
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_envelope_carries_population_and_grain(self):
        result = self._run({"metrics": ["claims"]})
        self.assertEqual(result["population"], "experience")
        self.assertEqual(result["grain"], "claim")
        self.assertTrue(result["query_id"])
        self.assertIn("coverage", result)

    def test_unknown_metric_rejected_with_allowed_values(self):
        with self.assertRaises(ValueError) as ctx:
            self._run({"metrics": ["revenue"]})
        message = str(ctx.exception)
        self.assertTrue("revenue" in message or "allowed" in message, message)

    def test_unknown_dimension_rejected(self):
        with self.assertRaises(ValueError):
            self._run({"metrics": ["claims"], "dimensions": ["income"]})

    def test_dimension_not_allowed_for_metric_rejected(self):
        # negative 的 allowed_dimensions 不含 sentiment：跨指标混用维度应被拒。
        with self.assertRaises(ValueError):
            self._run({"metrics": ["negative"], "dimensions": ["sentiment"]})

    def test_verifier_flags_missing_model_caliber(self):
        result = self._run({"metrics": ["claims"], "dimensions": ["aspect"]})
        stripped = {**result, "caliber": "自定义口径说明"}
        verdict = verifier.verify_step(stripped)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("模型口径" in item for item in verdict["errors"]), verdict["errors"])

    def test_verifier_rejects_non_semantic_relation_in_sql(self):
        result = self._run({"metrics": ["claims"]})
        verifier.assert_semantic_only(result["sql"])  # 不抛即通过
        with self.assertRaises(ValueError):
            verifier.assert_semantic_only("SELECT * FROM raw_posts")

    def test_empty_window_is_rejected_not_silently_empty(self):
        with self.assertRaises(ValueError):
            self._run({"metrics": ["claims"],
                       "time": {"start": "1999-01-01", "end": "1999-01-31"}})


def _make_tools(context):
    import agent_tools
    return {t.name: t for t in agent_tools.build_tools(context)}


def _submit_plan(tools, plan):
    import agent_tools
    return json.loads(tools["submit_analysis_plan"].invoke(
        {"plan_json": json.dumps(plan, ensure_ascii=False)})), agent_tools


_SEMANTIC_PARAMS = {"metrics": ["claims"], "dimensions": ["sentiment"]}


class SemanticPlanAndToolTests(unittest.TestCase):
    """计划只接受 semantic_aggregate；工具执行必须与已批准参数一致。"""

    def _plan(self, **stream_overrides):
        stream = {"id": "w1", "question": "各情感观点条数", "aspect": None,
                  "method": analysis_methods.SEMANTIC_METHOD,
                  "params": dict(_SEMANTIC_PARAMS)}
        stream.update(stream_overrides)
        return {"coverage": "语义聚合工作项", "use_python": False, "workstreams": [stream]}

    def _invoke(self, tools, params):
        return json.loads(tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps(params, ensure_ascii=False)}))

    def test_plan_url_aggregate_method_rejected(self):
        payload, _ = _submit_plan(_make_tools({"submissions": []}),
                                  self._plan(method="run_aggregate"))
        self.assertEqual(payload["error"], "invalid_workstream_fields")
        self.assertEqual(payload["allowed_methods"], [analysis_methods.SEMANTIC_METHOD])

    def test_plan_accepts_semantic_workstream_and_tool_executes(self):
        tools = _make_tools({"submissions": []})
        payload, _ = _submit_plan(tools, self._plan())
        self.assertTrue(payload.get("accepted"), payload)
        approved = payload["plan"]["workstreams"][0]["params"]
        self.assertEqual(approved["metrics"], _SEMANTIC_PARAMS["metrics"])
        self.assertEqual(approved["dimensions"], _SEMANTIC_PARAMS["dimensions"])
        result = self._invoke(tools, approved)
        self.assertNotIn("error", result)
        self.assertTrue(result["verification"]["ok"], result["verification"])

    def test_tool_rejects_params_not_in_plan(self):
        tools = _make_tools({"submissions": []})
        _submit_plan(tools, self._plan())
        result = self._invoke(tools, {"metrics": ["negative"]})
        self.assertEqual(result["error"], "analysis_step_not_in_plan")

    def test_plan_rejects_invalid_metric_with_details(self):
        payload, _ = _submit_plan(_make_tools({"submissions": []}),
                                  self._plan(params={"metrics": ["revenue"]}))
        self.assertEqual(payload["error"], "invalid_workstream_fields")

    def test_plan_rejects_missing_metrics(self):
        payload, _ = _submit_plan(_make_tools({"submissions": []}),
                                  self._plan(params={"dimensions": ["aspect"]}))
        self.assertEqual(payload["error"], "invalid_workstream_fields")

    def test_duplicate_semantic_params_rejected(self):
        tools = _make_tools({"submissions": []})
        stream_a = {"id": "w1", "question": "q1", "aspect": None,
                    "method": analysis_methods.SEMANTIC_METHOD,
                    "params": dict(_SEMANTIC_PARAMS)}
        stream_b = {**stream_a, "id": "w2", "question": "q2"}
        payload, _ = _submit_plan(tools, {"coverage": "c", "use_python": False,
                                          "workstreams": [stream_a, stream_b]})
        self.assertEqual(payload["error"], "invalid_workstream_fields")

    def test_tool_rejects_malformed_params_json(self):
        tools = _make_tools({"submissions": []})
        result = json.loads(tools["run_semantic_aggregate"].invoke({"params_json": "{}"}))
        self.assertEqual(result["error"], "semantic_params_invalid")

    def test_exploration_allowed_before_plan_in_interactive_mode(self):
        """auto-042 5.4：交付链在计划提交前有探索窗口（context.interactive=True）。

        该字段的语义是"无计划时是否允许取数"，与链路是否面向人类会话无关；
        计划一旦提交，仍按 params 严格比对。
        """
        tools = _make_tools({"interactive": True, "submissions": []})
        result = json.loads(tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["claims"], "limit": 5})}))
        self.assertNotIn("error", result)

    def test_exploration_denied_without_plan_when_not_interactive(self):
        tools = _make_tools({"interactive": False, "submissions": []})
        result = json.loads(tools["run_semantic_aggregate"].invoke(
            {"params_json": json.dumps({"metrics": ["claims"], "limit": 5})}))
        self.assertEqual(result["error"], "analysis_plan_required")


class FormOptionsCapabilityTests(unittest.TestCase):
    '''Tasks 5.1/5.2: form options follow capability declarations.'''

    def test_options_follow_capability_declarations(self):
        import task_brief
        con = db_mirror.connect()
        saved = dict(research_catalog.PRIMITIVE_CAPABILITIES)
        try:
            options = task_brief.form_options(con)
            self.assertIn('time_windows', options)      # date_range_filter=True
            self.assertNotIn('compare', options)        # brand_compare=False

            research_catalog.PRIMITIVE_CAPABILITIES['date_range_filter'] = False
            options = task_brief.form_options(con)
            self.assertNotIn('time_windows', options)   # 关闭后不再承诺时间切片

            research_catalog.PRIMITIVE_CAPABILITIES['brand_compare'] = True
            options = task_brief.form_options(con)
            self.assertIn('compare', options)
        finally:
            research_catalog.PRIMITIVE_CAPABILITIES.clear()
            research_catalog.PRIMITIVE_CAPABILITIES.update(saved)
            con.close()

    def test_options_endpoint_omits_undeclared_capability(self):
        import json as _json
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        import app
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        server.daemon_threads = True
        # serve_forever 必须在后台线程运行：否则请求无人受理会一直等，
        # 而 shutdown() 也会等待一个从未启动的循环（auto-042 1.4）。
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(base + '/api/analysis/options', timeout=10) as resp:
                payload = _json.loads(resp.read().decode('utf-8'))
            self.assertIn('time_windows', payload)
            self.assertNotIn('compare', payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)


class TaskBriefDynamicFactsTests(unittest.TestCase):
    '''Task 4.3: subject brand and data status are carried by the dynamic brief.'''

    def test_brief_carries_subject_and_data_status(self):
        import agent_engine
        import config
        message = agent_engine._opening_message('测试问题', None)
        brief = message.split('\n\n---\n\n', 1)[1]
        self.assertIn('品牌范围', brief)
        self.assertIn(config.SUBJECT_BRAND, brief)
        # 数据状态以覆盖声明为准：正式快照不写"临时样本"，但必须声明口径分区。
        self.assertIn('数据覆盖声明', brief)
        self.assertIn('口径分区', brief)

    def test_brief_baseline_rows_are_registered(self):
        import agent_engine
        baseline = agent_engine._baseline(None)
        step = agent_engine._baseline_step(None, baseline)
        self.assertEqual(step["kind"], "baseline")
        self.assertTrue(step["verification"]["ok"])


class ToolContractFixtureTests(unittest.TestCase):
    """fixture 的语义契约必须与代码中的参数闭环一致。"""

    def _fixture(self):
        path = Path(__file__).resolve().parent / "fixtures" / "tool-contract.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_contract_lists_semantic_params(self):
        section = self._fixture()["semantic_method"]
        self.assertEqual(section["method"], analysis_methods.SEMANTIC_METHOD)
        self.assertEqual(sorted(section["params"]),
                         sorted(["metrics", "dimensions", "filters", "time",
                                 "order", "population", "limit"]))
        self.assertIn("模型口径", section["caliber_marker"])

    def test_contract_plan_sample_is_acceptable(self):
        tools = _make_tools({"submissions": []})
        payload, _ = _submit_plan(tools, self._fixture()["plan_samples"]["semantic"])
        self.assertTrue(payload.get("accepted"), payload)

    def test_contract_error_codes_documented(self):
        codes = self._fixture()["semantic_method"]["tool_errors"]
        for code in ("semantic_query_rejected", "analysis_step_not_in_plan"):
            self.assertIn(code, codes)


if __name__ == "__main__":
    unittest.main()
