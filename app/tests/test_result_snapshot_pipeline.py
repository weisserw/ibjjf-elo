import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts"))
)

from result_snapshot_pipeline import compare_event_rows, occurrence_key


def row(name, *, team="Team A", place=1, division="Adult / Male / BLACK / Light"):
    return {
        "event_name": "World 2026",
        "event_ibjjf_id": "123",
        "division": division,
        "athlete_name": name,
        "team_name": team,
        "place": place,
        "source": "ibjjf",
    }


class ResultSnapshotPipelineTest(unittest.TestCase):
    def test_unique_slot_rename_is_automatic_and_keeps_occurrence_key(self):
        old, new = row("Old Name"), row("New Name")
        change = compare_event_rows([old], [new])[0]
        self.assertEqual(change.change_type, "renamed")
        self.assertTrue(change.automatic)
        self.assertEqual(occurrence_key(old), occurrence_key(new))

    def test_team_only_change_is_not_a_rename(self):
        change = compare_event_rows(
            [row("Same Name", team="Old Team")],
            [row("Same Name", team="New Team")],
        )[0]
        self.assertEqual(change.change_type, "team_changed")

    def test_two_bronze_changes_are_uncertain(self):
        before = [row("Old A", place=3), row("Old B", place=3)]
        after = [row("New A", place=3), row("New B", place=3)]
        changes = compare_event_rows(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "uncertain")
        self.assertFalse(changes[0].automatic)

    def test_add_and_remove_are_reported(self):
        self.assertEqual(compare_event_rows([], [row("New")])[0].change_type, "added")
        self.assertEqual(compare_event_rows([row("Old")], [])[0].change_type, "removed")


if __name__ == "__main__":
    unittest.main()
