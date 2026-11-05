import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion import merging


def decide(incoming_ts=100.0, previous_ts=100.0, same_snapshot=False,
           priorities=(0, 0), incoming=None, previous=None, ignored=()):
    return merging.decide(
        incoming_ts=incoming_ts, previous_ts=previous_ts, same_snapshot=same_snapshot,
        priorities=lambda: priorities,
        incoming={"title": "新标题"} if incoming is None else incoming,
        previous={"title": "旧标题"} if previous is None else previous,
        ignored=ignored)


class MergeDecisionTests(unittest.TestCase):
    def test_older_snapshot_keeps_previous_without_reading_priorities(self):
        calls = []

        def priorities():
            calls.append(True)
            return (0, 0)

        verdict = merging.decide(incoming_ts=90.0, previous_ts=100.0, same_snapshot=False,
                                 priorities=priorities, incoming={"title": "新"},
                                 previous={"title": "旧"})
        self.assertEqual(verdict, merging.OLDER_SKIPPED)
        self.assertEqual(calls, [])

    def test_missing_incoming_time_never_overwrites_a_timed_version(self):
        self.assertEqual(decide(incoming_ts=None, previous_ts=100.0), merging.OLDER_SKIPPED)

    def test_newer_snapshot_wins(self):
        self.assertEqual(decide(incoming_ts=110.0, previous_ts=100.0), merging.APPLY)

    def test_same_snapshot_is_not_a_conflict(self):
        self.assertEqual(decide(same_snapshot=True, priorities=(0, 9)), merging.APPLY)

    def test_lower_priority_source_loses_tie(self):
        self.assertEqual(decide(priorities=(1, 2)), merging.OLDER_SKIPPED)

    def test_higher_priority_source_wins_tie(self):
        self.assertEqual(decide(priorities=(2, 1)), merging.APPLY)

    def test_equal_priority_with_divergent_fields_conflicts(self):
        self.assertEqual(decide(priorities=(0, 0)), merging.CONFLICT)

    def test_equal_priority_with_identical_fields_applies(self):
        same = {"title": "同一标题"}
        self.assertEqual(decide(incoming=same, previous=dict(same)), merging.APPLY)

    def test_ignored_field_does_not_trigger_conflict(self):
        verdict = decide(incoming={"title": "同一标题", "field_availability_json": "a"},
                         previous={"title": "同一标题", "field_availability_json": "b"},
                         ignored=("field_availability_json",))
        self.assertEqual(verdict, merging.APPLY)

    def test_empty_value_on_either_side_is_not_a_conflict(self):
        verdict = decide(incoming={"title": ""}, previous={"title": "旧标题"})
        self.assertEqual(verdict, merging.APPLY)


class DiffersTests(unittest.TestCase):
    def test_missing_previous_field_is_not_a_difference(self):
        self.assertFalse(merging.differs({"title": "x", "extra": "y"}, {"title": "x"}))

    def test_any_divergent_field_is_a_difference(self):
        self.assertTrue(merging.differs({"title": "x"}, {"title": "y"}))

    def test_sqlite_row_is_matched_by_column_name(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT '旧标题' AS title").fetchone()
        self.assertTrue(merging.differs({"title": "新标题"}, row))
        self.assertFalse(merging.differs({"title": "旧标题"}, row))


if __name__ == "__main__":
    unittest.main()
