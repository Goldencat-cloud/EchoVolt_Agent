"""auto-033 tests: evidence appendix generation and five-dimension review checklist."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report_publisher
from research import service


class EvidenceDetailsTests(unittest.TestCase):
    """service.evidence_details resolves claim metadata over the curated pool."""

    def test_resolves_real_claim_with_metadata(self):
        recalled = service.search_claims(query="充电 排队", aspect="充电与补能")
        self.assertTrue(recalled["claims"], "curated pool should not be empty")
        target = recalled["claims"][0]["claim_id"]
        out = service.evidence_details([target])
        self.assertEqual(out["n_requested"], 1)
        self.assertEqual(out["n_found"], 1)
        row = out["details"][0]
        self.assertTrue(row["found"])
        self.assertEqual(row["claim_id"], target)
        for field in ("url", "date", "aspect", "sentiment", "source_set"):
            self.assertIn(field, row)
        self.assertLessEqual(len(row["quote"]), 160)

    def test_unknown_id_reported_not_dropped(self):
        out = service.evidence_details(["f" * 20])
        self.assertEqual(out["n_found"], 0)
        self.assertFalse(out["details"][0]["found"])

    def test_deduplicates_and_sorts(self):
        out = service.evidence_details(["b" * 20, "a" * 20, "b" * 20])
        self.assertEqual(out["n_requested"], 2)
        ids = [row["claim_id"] for row in out["details"]]
        self.assertEqual(ids, sorted(ids))

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):
            service.evidence_details([])


class EvidenceAppendixTests(unittest.TestCase):
    """save_submission writes evidence.md/evidence.json without touching report.md."""

    def test_save_submission_generates_appendix(self):
        fake_details = [{"claim_id": "a" * 20, "found": True, "url": "https://example.com/t/1",
                         "date": "2026-01-02", "title": "帖子标题", "aspect": "充电与补能",
                         "sentiment": "负面", "ownership": "当前拥有", "experience": "明确亲历",
                         "journey": None, "source_set": "core", "quote": "充电排队两小时"}]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher.service, "evidence_details",
                                   return_value={"details": fake_details, "n_requested": 1,
                                                 "n_found": 1, "data_version": "v", "snapshot_hash": "h"}):
                report_publisher.save_submission("a1b2c3d4e5f6", "# 报告\n正文",
                                                 [], {"data_version": "v"}, {"a" * 20})
            report_md = (Path(tmp) / "a1b2c3d4e5f6" / "report.md").read_text(encoding="utf-8")
            self.assertIn("充电排队两小时",
                          (Path(tmp) / "a1b2c3d4e5f6" / "evidence.md").read_text(encoding="utf-8"))
            self.assertIn("a" * 20,
                          (Path(tmp) / "a1b2c3d4e5f6" / "evidence.md").read_text(encoding="utf-8"))
            evidence_json = json.loads(
                (Path(tmp) / "a1b2c3d4e5f6" / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence_json["evidence"][0]["claim_id"], "a" * 20)
            self.assertNotIn("证据附录", report_md)  # appendix stays out of the report body

    def test_appendix_failure_recorded_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher.service, "evidence_details",
                                   side_effect=RuntimeError("frozen data missing")):
                report_publisher.save_submission("a1b2c3d4e5f6", "# 报告\n正文",
                                                 [], {"data_version": "v"}, {"a" * 20})
            evidence_md = (Path(tmp) / "a1b2c3d4e5f6" / "evidence.md").read_text(encoding="utf-8")
            self.assertIn("附录生成失败", evidence_md)
            self.assertNotIn("RuntimeError", evidence_md)  # 异常类型不暴露给人读附录
            evidence_json = json.loads(
                (Path(tmp) / "a1b2c3d4e5f6" / "evidence.json").read_text(encoding="utf-8"))
            self.assertIn("RuntimeError", evidence_json["error"])  # 完整异常留在机器可读文件

    def test_long_title_truncated_with_ellipsis(self):
        long_title = "标" * 80
        fake_details = [{"claim_id": "a" * 20, "found": True, "url": "https://example.com/t/1",
                         "date": "2026-01-02", "title": long_title, "aspect": "充电与补能",
                         "sentiment": "负面", "ownership": "当前拥有", "experience": "明确亲历",
                         "journey": None, "source_set": "core", "quote": "引文"}]
        with mock.patch.object(report_publisher.service, "evidence_details",
                               return_value={"details": fake_details, "n_requested": 1,
                                             "n_found": 1, "data_version": "v", "snapshot_hash": "h"}):
            appendix_md, _details, _error = report_publisher._evidence_appendix({"a" * 20})
        self.assertIn("标题：" + "标" * 60 + "…", appendix_md)


class ReviewChecklistTests(unittest.TestCase):
    """Five-dimension checklist: shape validation and recorded review metadata."""

    def _prepare_report(self, tmp: Path) -> None:
        directory = tmp / "a1b2c3d4e5f6"
        directory.mkdir(parents=True)
        (directory / "report.md").write_text("# 报告\n", encoding="utf-8")
        (directory / "provenance.json").write_text(
            json.dumps({"verified_steps": [], "evidence_claim_ids": []}), encoding="utf-8")
        (directory / "meta.json").write_text(json.dumps(
            {"report_id": "a1b2c3d4e5f6", "status": "pending_review",
             "data_version": "v", "snapshot_hash": "h", "title": "t", "key_findings": []}),
            encoding="utf-8")

    def test_valid_checklist_recorded(self):
        checklist = {"可读性": "通过", "逻辑性": "关注：归因强度"}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report_publisher, "REPORTS_DIR", Path(tmp)), \
                 mock.patch.object(report_publisher.service, "snapshot_version", return_value="v"), \
                 mock.patch.object(report_publisher.service, "snapshot_hash", return_value="h"):
                self._prepare_report(Path(tmp))
                meta = report_publisher.review_and_publish(
                    "a1b2c3d4e5f6", reviewer="human-owner", reviewed_commit="a" * 7,
                    verdict="rejected", note="小样本结论需降级", checklist=checklist)
            self.assertEqual(meta["review"]["checklist"], checklist)
            self.assertEqual(meta["review"]["verdict"], "rejected")

    def test_invalid_dimension_rejected(self):
        with self.assertRaises(ValueError):
            report_publisher._validate_checklist({"用户体验": "通过"})

    def test_empty_value_rejected(self):
        with self.assertRaises(ValueError):
            report_publisher._validate_checklist({"可读性": "  "})

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            report_publisher._validate_checklist(["可读性"])

    def test_none_keeps_legacy_behavior(self):
        self.assertEqual(report_publisher._validate_checklist(None), {})


if __name__ == "__main__":
    unittest.main()
