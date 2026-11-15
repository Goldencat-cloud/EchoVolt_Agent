"""Static contract tests: tool envelope, version fields and error codes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import service

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tool-contract.json"


class ToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_envelope_keys_match_contract(self):
        stats = service.query_stats(**self.contract["sample_inputs"]["query_stats"])
        claims = service.query_claims(**self.contract["sample_inputs"]["query_claims"])
        self.assertEqual(set(stats), set(self.contract["envelope_keys"]))
        self.assertEqual(set(claims), set(self.contract["envelope_keys"]))

    def test_version_fields_present_and_nonempty(self):
        stats = service.query_stats()
        for field in self.contract["version_fields"]:
            self.assertIsInstance(stats[field], str)
            self.assertTrue(stats[field])

    def test_error_codes_match_contract(self):
        for case in self.contract["error_codes"]:
            func = getattr(service, case["tool"])
            with self.assertRaises(ValueError) as ctx:
                func(**case["input"])
            self.assertEqual(str(ctx.exception), case["error"])

    def test_expected_warnings_present(self):
        stats = service.query_stats(**self.contract["sample_inputs"]["query_stats"])
        claims = service.query_claims(**self.contract["sample_inputs"]["query_claims"])
        for warning in self.contract["expected_warnings"]["query_stats"]:
            self.assertIn(warning, stats["warnings"])
        for warning in self.contract["expected_warnings"]["query_claims"]:
            self.assertIn(warning, claims["warnings"])


if __name__ == "__main__":
    unittest.main()
