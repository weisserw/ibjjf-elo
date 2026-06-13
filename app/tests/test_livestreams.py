import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from livestreams import get_livestream_link, get_search_name, is_quarterfinal_or_above


class LivestreamsTestCase(unittest.TestCase):
    def test_search_name_prefers_special_mapping_over_personal_name(self):
        self.assertEqual(
            get_search_name(
                "Diego Batista Lima",
                {"Diego Batista Lima": "Diego Pato"},
                'Diego Oliveira "Pato"',
                True,
            ),
            "Diego Pato",
        )

    def test_search_name_uses_personal_name_without_nickname_when_unmapped(self):
        self.assertEqual(
            get_search_name("Diego Batista Lima", {}, 'Diego Oliveira "Pato"', True),
            "Diego Oliveira",
        )

    def test_search_name_uses_full_name_when_special_names_are_disabled(self):
        self.assertEqual(
            get_search_name(
                "Diego Batista Lima",
                {"Diego Batista Lima": "Diego Pato"},
                'Diego Oliveira "Pato"',
                False,
            ),
            "Diego Lima",
        )

    def test_is_quarterfinal_or_above(self):
        self.assertFalse(is_quarterfinal_or_above(None, 10))
        self.assertFalse(is_quarterfinal_or_above(16, None))
        self.assertFalse(is_quarterfinal_or_above(16, 9))
        self.assertTrue(is_quarterfinal_or_above(16, 10))

    def test_livestream_link_uses_personal_names_for_adult_black_quarterfinals(self):
        livestream_links = {
            "tournament_days": {},
            "live_streams": {},
            "flo_event_tags": {"E1": "test-event"},
            "special_search_names": {},
        }

        self.assertEqual(
            get_livestream_link(
                livestream_links,
                "E1",
                "Diego Batista Lima",
                "Ana Maria Silva Rodriguez",
                datetime(2026, 1, 1),
                "Mat 1",
                "BLACK",
                "Adult",
                8,
                2,
                'Diego Oliveira "Pato"',
                "Ana Rodriguez",
            ),
            "https://www.flograppling.com/events/test-event/videos?openInBrowser=1&search=Diego%20Oliveira%20vs%20Ana%20Rodriguez",
        )

    def test_livestream_link_uses_full_names_before_adult_black_quarterfinals(self):
        livestream_links = {
            "tournament_days": {},
            "live_streams": {},
            "flo_event_tags": {"E1": "test-event"},
            "special_search_names": {"Diego Batista Lima": "Diego Pato"},
        }

        self.assertEqual(
            get_livestream_link(
                livestream_links,
                "E1",
                "Diego Batista Lima",
                "Ana Maria Silva Pereira",
                datetime(2026, 1, 1),
                "Mat 1",
                "BLACK",
                "Adult",
                8,
                1,
                'Diego Oliveira "Pato"',
                "Ana Rodriguez",
            ),
            "https://www.flograppling.com/events/test-event/videos?openInBrowser=1&search=Diego%20Lima%20vs%20Ana%20Pereira",
        )


if __name__ == "__main__":
    unittest.main()
