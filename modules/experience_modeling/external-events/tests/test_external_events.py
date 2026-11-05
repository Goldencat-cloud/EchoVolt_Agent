import copy
import json
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))

class ExternalEventSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event = load("external-event-record.schema.json")
        cls.output = load("extraction-output.schema.json")
        cls.fixtures = load("examples.json")["examples"]
        cls.ev = Draft202012Validator(cls.event, format_checker=FormatChecker())
        cls.ov = Draft202012Validator(cls.output, format_checker=FormatChecker())
        cls.record = cls.fixtures[0]["output"]["external_events"][0]

    def assertInvalid(self, instance, validator=None):
        self.assertTrue(list((validator or self.ev).iter_errors(instance)))

    def test_schema_definitions_valid(self):
        for schema in (self.event, self.output):
            Draft202012Validator.check_schema(schema)



    def test_external_embedded_definition_matches_standalone(self):
        expected = {k: v for k, v in self.event.items() if k not in ("$schema", "$id")}
        self.assertEqual(expected, self.output["$defs"]["external_event_record"])

    def test_all_synthetic_outputs_and_events_valid(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                self.ov.validate(fixture["output"])
                for event in fixture["output"]["external_events"]:
                    self.ev.validate(event)

    def test_fixture_quotes_are_actual_contiguous_input(self):
        for fixture in self.fixtures:
            source = fixture["input"]
            for record in fixture["output"]["external_events"]:
                self.assertEqual(record["evidence"]["source_id"], source["source_id"])
                self.assertIn(record["evidence"]["quote"], source["text"])


    def test_event_only_does_not_require_user_journey_or_sentiment(self):
        out = self.fixtures[1]["output"]
        event = out["external_events"][0]
        for key in ("user_id", "journey_stage", "evaluation"):
            self.assertNotIn(key, event)
        self.ev.validate(event)

    def test_personal_conditional_example_has_no_external_event(self):
        out = self.fixtures[3]["output"]
        self.assertEqual(out["external_events"], [])

    def test_required_event_fields_missing_rejected(self):
        for key in self.event["required"]:
            value = copy.deepcopy(self.record)
            del value[key]
            with self.subTest(key=key):
                self.assertInvalid(value)

    def test_unknown_fields_and_inferred_causal_edge_rejected(self):
        for key in ("caused_experience_id", "journey_stage", "authority"):
            value = copy.deepcopy(self.record)
            value[key] = "guessed"
            with self.subTest(key=key):
                self.assertInvalid(value)

    def test_invalid_event_type_and_statement_rejected(self):
        for key in ("event_type", "statement_type"):
            value = copy.deepcopy(self.record)
            value[key] = "invented_label"
            self.assertInvalid(value)

    def test_extractor_cannot_assert_independent_verification(self):
        value = copy.deepcopy(self.record)
        value["verification_status"] = "verified"
        self.assertInvalid(value)

    def test_confidence_bounds_and_boolean_rejected(self):
        for c in (-0.1, 1.1, True, None):
            value = copy.deepcopy(self.record)
            value["extraction_confidence"] = c
            self.assertInvalid(value)

    def test_partial_month_keeps_year_unknown(self):
        event = self.fixtures[4]["output"]["external_events"][0]
        self.assertIsNone(event["event_time"]["value"])
        self.ev.validate(event)

    def test_valid_time_precision_values(self):
        for precision, value in (("year", "2026"), ("month", "2026-05"), ("day", "2026-05-01"),
                                 ("datetime", "2026-05-01T09:00:00+08:00"), ("unknown", None)):
            event = copy.deepcopy(self.record)
            event["event_time"] = {"raw_text": "synthetic date", "value": value, "precision": precision}
            self.ev.validate(event)

    def test_wrong_time_granularity_or_calendar_date_rejected(self):
        for precision, value in (("month", "2026-13"), ("day", "2026-02-30"),
                                 ("day", "2026-05"), ("year", "2026-05-01"),
                                 ("datetime", "2026-05-01T09:00:00"), ("unknown", "2026")):
            event = copy.deepcopy(self.record)
            event["event_time"] = {"raw_text": "synthetic date", "value": value, "precision": precision}
            self.assertInvalid(event)

    def test_empty_evidence_and_empty_ids_rejected(self):
        for key in ("event_id",):
            event = copy.deepcopy(self.record)
            event[key] = ""
            self.assertInvalid(event)
        event = copy.deepcopy(self.record)
        event["evidence"]["quote"] = ""
        self.assertInvalid(event)

    def test_product_ids_unique_nonempty(self):
        event = copy.deepcopy(self.record)
        event["product_ids"] = ["MODEL_TEST"]
        self.ev.validate(event)
        for values in ([""], ["MODEL_TEST", "MODEL_TEST"]):
            event["product_ids"] = values
            self.assertInvalid(event)

    def test_event_collection_must_be_array(self):
        for value in (None, {}, "event"):
            self.assertInvalid({"source_id": "P", "external_events": value}, self.ov)


if __name__ == "__main__":
    unittest.main()
