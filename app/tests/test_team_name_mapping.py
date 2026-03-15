import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from team_name_mapping import resolve_dupe_team_name


class TeamNameMappingTestCase(unittest.TestCase):
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
