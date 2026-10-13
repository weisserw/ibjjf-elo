import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from team_name_mapping import (
    load_canonical_team_names,
    resolve_dupe_team_name,
    same_canonical_team,
)


class TeamNameMappingTestCase(unittest.TestCase):
    def test_run_lookup_uses_two_queries_and_shared_mapping_precedence(self):
        session = Mock()
        rules = Mock()
        rules.all.return_value = [
            ("Alliance*", "Broad"),
            ("Alliance HQ*", "Alliance"),
            ("Alliance HQ Special", "Special"),
            ("Other", "Alliance"),
        ]
        session.query.side_effect = [
            rules,
            [
                ("a", "Alliance HQ East"),
                ("b", "Other"),
                ("c", "Alliance HQ Special"),
                ("d", "Unmapped"),
                ("e", "Alliance South"),
                ("f", "Unmapped"),
                ("g", None),
            ],
        ]
        names = load_canonical_team_names(session)
        self.assertEqual(
            names,
            {
                "a": "Alliance",
                "b": "Alliance",
                "c": "Special",
                "d": "Unmapped",
                "e": "Broad",
                "f": "Unmapped",
                "g": None,
            },
        )
        for _ in range(1000):
            self.assertTrue(same_canonical_team("a", "b", names))
            self.assertTrue(same_canonical_team("d", "f", names))
            self.assertFalse(same_canonical_team("a", "c", names))
            self.assertFalse(same_canonical_team("missing", "unknown", names))
            self.assertFalse(same_canonical_team(None, None, names))
        self.assertEqual(session.query.call_count, 2)

    def test_exact_mapping_takes_precedence_over_glob(self):
        exact_mappings = {
            "Atos HQ": "Atos",
        }
        glob_mappings = [
            ("Atos*", "Atos Jiu Jitsu"),
        ]

        resolved = resolve_dupe_team_name("Atos HQ", exact_mappings, glob_mappings)

        self.assertEqual(resolved, "Atos")

    def test_glob_mapping_applies_when_no_exact(self):
        exact_mappings = {}
        glob_mappings = [
            ("Atos*", "Atos Jiu Jitsu"),
        ]

        resolved = resolve_dupe_team_name(
            "Atos Costa Mesa", exact_mappings, glob_mappings
        )

        self.assertEqual(resolved, "Atos Jiu Jitsu")


if __name__ == "__main__":
    unittest.main()
