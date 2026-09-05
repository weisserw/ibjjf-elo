import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from livestreams import (
    get_livestream_link,
    get_search_name,
    is_quarterfinal_or_above,
    per_mat_livestream_links,
)


class LivestreamsTestCase(unittest.TestCase):
    def test_per_mat_links_prefer_youtube_and_apply_flo_to_each_event_day(self):
        links = per_mat_livestream_links(
            {
                "tournament_days": {"1": date(2026, 9, 4)},
                "tournament_end_days": {"1": date(2026, 9, 5)},
                "live_streams": {("1", 2, 1): [("https://youtube.test/mat-1",)]},
                "flo_mat_links": {
                    ("1", 1): "https://flo.test/mat-1",
                    ("1", 2): "https://flo.test/mat-2",
                },
            },
            ["1"],
        )

        self.assertEqual(links["1"]["2026-09-04"]["1"]["type"], "flo")
        self.assertEqual(links["1"]["2026-09-05"]["1"]["type"], "youtube")
        self.assertEqual(links["1"]["2026-09-05"]["2"]["type"], "flo")

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
            "diego oliveira",
        )

    def test_search_name_uses_full_name_when_special_names_are_disabled(self):
        self.assertEqual(
            get_search_name(
                "Diego Batista Lima",
                {"Diego Batista Lima": "Diego Pato"},
                'Diego Oliveira "Pato"',
                False,
            ),
            "diego lima",
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
                None,
                None,
            ),
            "https://www.flograppling.com/events/test-event/videos?openInBrowser=1&search=diego%20oliveira%20vs%20ana%20rodriguez",
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
                None,
                None,
            ),
            "https://www.flograppling.com/events/test-event/videos?openInBrowser=1&search=diego%20lima%20vs%20ana%20pereira",
        )

    def test_livestream_link_returns_none_sentinel_before_computing(self):
        livestream_links = {
            "tournament_days": {"E1": datetime(2026, 1, 1).date()},
            "live_streams": {
                ("E1", 1, 1): [
                    (
                        "https://www.youtube.com/watch?v=video123",
                        9,
                        0,
                        0,
                        17,
                        0,
                        1.0,
                        False,
                    )
                ]
            },
            "flo_event_tags": {},
        }

        self.assertEqual(
            get_livestream_link(
                livestream_links,
                "E1",
                "Winner",
                "Loser",
                datetime(2026, 1, 1, 10, 0),
                "Mat 1",
                "BLACK",
                "Adult",
                8,
                1,
                "Winner",
                "Loser",
                "None",
                3600,
            ),
            "None",
        )

    def test_livestream_link_prefers_youtube_livestream_with_stored_offset(self):
        livestream_links = {
            "tournament_days": {"E1": datetime(2026, 1, 1).date()},
            "live_streams": {
                ("E1", 1, 1): [
                    (
                        "https://www.youtube.com/watch?v=video123",
                        9,
                        0,
                        0,
                        17,
                        0,
                        1.0,
                        False,
                    )
                ]
            },
            "flo_event_tags": {},
        }

        self.assertEqual(
            get_livestream_link(
                livestream_links,
                "E1",
                "Winner",
                "Loser",
                datetime(2026, 1, 1, 10, 0),
                "Mat 1",
                "BLACK",
                "Adult",
                8,
                1,
                "Winner",
                "Loser",
                "https://www.youtube.com/watch?v=per-match",
                3600,
            ),
            "https://www.youtube.com/watch?v=video123&t=3600s",
        )

    def test_livestream_link_prefers_per_match_without_stored_offset(self):
        livestream_links = {
            "tournament_days": {"E1": datetime(2026, 1, 1).date()},
            "live_streams": {
                ("E1", 1, 1): [
                    (
                        "https://www.youtube.com/watch?v=video123",
                        9,
                        0,
                        0,
                        17,
                        0,
                        1.0,
                        False,
                    )
                ]
            },
            "flo_event_tags": {},
        }

        self.assertEqual(
            get_livestream_link(
                livestream_links,
                "E1",
                "Winner",
                "Loser",
                datetime(2026, 1, 1, 10, 0),
                "Mat 1",
                "BLACK",
                "Adult",
                8,
                1,
                "Winner",
                "Loser",
                "https://www.youtube.com/watch?v=per-match",
                None,
            ),
            "https://www.youtube.com/watch?v=per-match",
        )


if __name__ == "__main__":
    unittest.main()
