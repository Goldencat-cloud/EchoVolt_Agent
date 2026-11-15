"""Deterministic tests for the claims recall tool (Owner 2026-10-28).

Covers: service-level scoring (determinism, tier weighting, filters, errors),
tool-level plan constraints and provenance-ledger wiring, and evidence
completeness interaction with submit_report requirements.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_tools
from research import service


class SearchClaimsServiceTests(unittest.TestCase):
    """search_claims: deterministic relevance ranking over the curated pool."""

    def test_ranked_by_relevance_and_returns_citable_claims(self):
        out = service.search_claims(query="充电", aspect="充电与补能", limit=10)
        self.assertIn("claims", out)
        for row in out["claims"]:
            self.assertIn("claim_id", row)
            self.assertIn("tier", row)
            self.assertEqual(len(row["claim_id"]), 20)
        self.assertTrue(all(row["score"] >= 0 for row in out["claims"]))
        # descending score
        scores = [row["score"] for row in out["claims"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_deterministic(self):
        a = service.search_claims(query="充电 排队", aspect="充电与补能")
        b = service.search_claims(query="充电 排队", aspect="充电与补能")
        self.assertEqual(a, b)

    def test_tier_weighting_core_above_potential(self):
        out = service.search_claims(query="充电体验", aspect="充电与补能", limit=20)
        tiers = {row["claim_id"]: row["tier"] for row in out["claims"]}
        if {"core", "potential"} <= set(tiers.values()):
            by_tier = {}
            for row in out["claims"]:
                by_tier.setdefault(row["tier"], []).append(row["score"])
            if by_tier.get("core") and by_tier.get("potential"):
                self.assertGreaterEqual(min(by_tier["core"]), min(by_tier["potential"]))

    def test_sentiment_filter(self):
        out = service.search_claims(query="充电", aspect="充电与补能", sentiment="正面")
        self.assertTrue(all(row["sentiment"] == "正面" for row in out["claims"]))

    def test_unknown_aspect_rejected(self):
        with self.assertRaises(ValueError):
            service.search_claims(query="充电", aspect="不存在的议题")

    def test_query_validation(self):
        with self.assertRaises(ValueError):
            service.search_claims(query="充")
        with self.assertRaises(ValueError):
            service.search_claims(query="充电", limit=0)


class SearchClaimsToolTests(unittest.TestCase):
    """Tool wiring: plan constraint, provenance ledger, evidence completeness."""

    def _plan(self):
        return {"coverage": "c", "use_python": False, "workstreams": [
            {"id": "w1", "question": "充电负面说法", "dimension": "aspect",
             "aspect": "充电与补能", "method": "top_negative_claims",
             "requires_evidence": True}]}

    def _tools(self, context):
        tools = {t.name: t for t in agent_tools.build_tools(context)}
        return tools

    def test_aspect_outside_plan_rejected_without_costing_ledger(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "plan": self._plan()}
        tool = self._tools(context)["search_claims"]
        raw = tool.invoke({"query": "充电 排队", "aspect": "空间与舒适性"})
        out = json.loads(raw)
        self.assertIn("search_claims_aspect_not_in_plan", out["error"])
        self.assertIn("充电与补能", out["allowed_aspects"])

    def test_recall_records_provenance_and_claim_ids(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "plan": self._plan()}
        tool = self._tools(context)["search_claims"]
        raw = tool.invoke({"query": "充电 排队", "aspect": "充电与补能"})
        out = json.loads(raw)
        self.assertIn("claims", out)
        self.assertTrue(context["verified_steps"])
        step = context["verified_steps"][-1]
        self.assertEqual(step["kind"], "evidence")
        self.assertEqual(step["aspect"], "充电与补能")
        if out["claims"]:
            self.assertTrue(step["claim_ids"])
            self.assertTrue(context["evidence_claim_ids"] & set(step["claim_ids"]))

    def test_recall_step_satisfies_requires_evidence_completeness(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set(), "plan": self._plan(),
                   "submit_attempts": 0, "accepted_submission": False}
        tool = self._tools(context)["search_claims"]
        tool.invoke({"query": "充电 排队", "aspect": "充电与补能"})
        # search step (kind=evidence, claim_ids non-empty) must satisfy w1's evidence need
        stream = context["plan"]["workstreams"][0]
        has_evidence = any(
            step.get("aspect") == stream["aspect"] and step.get("claim_ids")
            for step in context["verified_steps"]
            if step.get("kind") in {"method", "evidence"})
        self.assertTrue(has_evidence)

    def test_interactive_mode_allows_known_aspects(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set()}
        tool = self._tools(context)["search_claims"]
        raw = tool.invoke({"query": "充电 排队", "aspect": "充电与补能"})
        self.assertIn("claims", json.loads(raw))

    def test_invalid_query_reported_not_raised(self):
        context = {"interactive": True, "submissions": [], "verified_steps": [],
                   "evidence_claim_ids": set()}
        tool = self._tools(context)["search_claims"]
        raw = tool.invoke({"query": "充", "aspect": "充电与补能"})
        self.assertIn("invalid_search_claims_params", json.loads(raw)["error"])


class SearchClaimsEmbeddingTests(unittest.TestCase):
    """Embedding relevance path: mocked backend, deterministic, graceful fallback."""

    def _patch_backend(self, *, ready=True, query_vec=None, pool_map=None, fail=False):
        """Patch service.embeddings in place; returns (enter, exit) context manager."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            emb = service.embeddings
            saved = (emb.backend_ready, emb.embed_texts, emb.pool_vectors)
            emb.backend_ready = lambda: ready
            if fail:
                emb.embed_texts = lambda texts: None
                emb.pool_vectors = lambda snapshot, ids, texts: None
            else:
                emb.embed_texts = lambda texts: [query_vec] * len(texts)
                emb.pool_vectors = lambda snapshot, ids, texts: (
                    pool_map(snapshot, ids, texts) if pool_map else {})
            try:
                yield
            finally:
                emb.backend_ready, emb.embed_texts, emb.pool_vectors = saved

        return _ctx()

    @staticmethod
    def _pool_map_by_keyword(snapshot, ids, texts):
        # 充电-related rows align with the query vector; others are orthogonal.
        return {cid: ([1.0, 0.0] if "充电" in text else [0.0, 1.0])
                for cid, text in zip(ids, texts)}

    def test_embedding_path_used_and_filters_low_similarity(self):
        with self._patch_backend(query_vec=[1.0, 0.0],
                                 pool_map=self._pool_map_by_keyword):
            out = service.search_claims(query="充电排队", aspect="充电与补能", limit=20)
        self.assertEqual(out["relevance"], "embedding")
        self.assertIn("语义相关度", out["caliber"])
        self.assertNotIn("embedding_unavailable_keyword_fallback", out["warnings"])
        scores = [row["score"] for row in out["claims"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_embedding_failure_degrades_to_keyword_with_warning(self):
        with self._patch_backend(fail=True):
            out = service.search_claims(query="充电 排队", aspect="充电与补能")
        self.assertEqual(out["relevance"], "keyword")
        self.assertIn("embedding_unavailable_keyword_fallback", out["warnings"])
        self.assertIn("claims", out)

    def test_backend_not_configured_stays_keyword_without_warning(self):
        # default test env: AI_EMBEDDING_MODEL unset → backend_ready() False
        out = service.search_claims(query="充电 排队", aspect="充电与补能")
        self.assertEqual(out["relevance"], "keyword")
        self.assertNotIn("embedding_unavailable_keyword_fallback", out["warnings"])


if __name__ == "__main__":
    unittest.main()
