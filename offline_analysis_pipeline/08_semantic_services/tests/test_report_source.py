"""Tests for the displayed-report knowledge source used by citation Q&A."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report_source


class ReportSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sections = report_source.load_sections()

    def test_sections_extracted_with_ids_and_titles(self):
        self.assertTrue(self.sections, "no sections extracted from the displayed report")
        ids = [s["id"] for s in self.sections]
        self.assertIn("F1", ids)
        self.assertIn("s-method", ids)
        for section in self.sections:
            self.assertTrue(section["id"])
            self.assertTrue(section["text"].strip())

    def test_context_contains_anchor_headers(self):
        context = report_source.build_context(self.sections)
        self.assertIn("【F1】", context)
        self.assertIn("【s-method】", context)

    def test_citation_parsing_validates_anchors(self):
        answer = "舒适性负面声量最高 [F1]，口径见 [s-method]，另有 [ZZZ] 未知引用。"
        result = report_source.parse_citations(answer, self.sections)
        self.assertIn("F1", result["valid"])
        self.assertIn("s-method", result["valid"])
        self.assertEqual(result["unknown"], ["ZZZ"])
        titles = {s["id"]: s["title"] for s in result["sections"]}
        self.assertTrue(titles["F1"])

    def test_citation_parsing_handles_empty_answer(self):
        result = report_source.parse_citations("", self.sections)
        self.assertEqual(result["cited"], [])


if __name__ == "__main__":
    unittest.main()
