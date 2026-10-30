import os
import sys
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, BROWN, PURPLE, BLUE, WHITE, MASTER_1, MASTER_8
from elo import (
    DEFAULT_RATINGS,
    CLOSEOUT_NOTE,
    compute_ratings,
    RATING_VERY_IMMATURE_COUNT,
    compute_start_rating,
    division_default_rating,
    elite_tier,
    rating_maturity,
    rating_top_percent,
)
from ratings import normalize_target_athlete_id, normalize_target_athlete_ids


class CloseoutRatingTestCase(unittest.TestCase):
    def compute(self, **overrides):
        args = dict(
            db=Mock(),
            event_id="event",
            match_id="match",
            division=SimpleNamespace(age=ADULT, to_json=lambda: {}),
            happened_at=datetime(2026, 1, 1),
            rate_winner_only=False,
            red_athlete_id="red",
            red_winner=True,
            red_note=None,
            red_team_id="a",
            blue_athlete_id="blue",
            blue_winner=False,
            blue_note=None,
            blue_team_id="b",
            suspensions={},
            is_final=True,
            canonical_team_names={"a": "Alliance", "b": "Alliance", "c": "Atos"},
        )
        args.update(overrides)
        with (
            patch("elo.get_last_matches", return_value=(None, None)),
            patch("elo.get_match_count", return_value=10),
            patch("elo.compute_start_rating", return_value=(2000, "Existing note")),
            patch("elo.open_handicaps", return_value=(False, 0, 0, None, None)),
        ):
            return compute_ratings(**args)

    def test_closeouts_preserve_ratings_counts_and_existing_notes(self):
        for options in (
            {},
            {"blue_team_id": "a"},
            {"rate_winner_only": True},
            {"red_winner": False, "blue_winner": True},
        ):
            with self.subTest(options=options):
                result = self.compute(**options)
                self.assertFalse(result[0])
                self.assertEqual(result[1:5], (2000, 2000, 2000, 2000))
                self.assertEqual(result[7:9], (f"Existing note, {CLOSEOUT_NOTE}",) * 2)
                self.assertEqual(result[9:13], (10, 10, 10, 10))

    def test_nonfinal_different_and_unknown_teams_remain_rated(self):
        for options in (
            {"is_final": False},
            {"blue_team_id": "c"},
            {"red_team_id": None, "blue_team_id": None},
            {"red_team_id": "missing", "blue_team_id": "unknown"},
        ):
            with self.subTest(options=options):
                result = self.compute(**options)
                self.assertTrue(result[0])
                self.assertGreater(result[2], result[1])
                self.assertLess(result[4], result[3])
                self.assertEqual(result[9:13], (10, 11, 10, 11))

    def test_existing_unrated_reason_keeps_precedence(self):
        result = self.compute(blue_winner=True)
        self.assertFalse(result[0])
        self.assertIn("Unrated: winner not recorded", result[7])
        self.assertNotIn(CLOSEOUT_NOTE, result[7])


class TargetAthleteIdTestCase(unittest.TestCase):
    def test_compact_and_hyphenated_uuid_normalize_identically(self):
        athlete_id = uuid.uuid4()
        self.assertEqual(athlete_id, normalize_target_athlete_id(athlete_id.hex))
        self.assertEqual(athlete_id, normalize_target_athlete_id(str(athlete_id)))
        self.assertIsNone(normalize_target_athlete_id(None))

    def test_target_athlete_sets_are_normalized(self):
        first = uuid.uuid4()
        second = uuid.uuid4()
        self.assertEqual(
            {first, second},
            normalize_target_athlete_ids(None, [first.hex, str(second)]),
        )

    def test_single_and_multiple_targets_are_mutually_exclusive(self):
        athlete_id = uuid.uuid4()
        with self.assertRaisesRegex(ValueError, "cannot both be provided"):
            normalize_target_athlete_ids(athlete_id, [athlete_id])


class ComputeStartRatingTestCase(unittest.TestCase):
    def setUp(self):
        self.division = SimpleNamespace(belt=BLACK, age=MASTER_1)
        previous_division = SimpleNamespace(belt=BLACK, age=ADULT)
        match = SimpleNamespace(division=previous_division)
        self.previous_rating = 1950
        self.last_match = SimpleNamespace(
            match=match,
            end_rating=self.previous_rating,
        )

    def test_new_age_division_resets_fully_provisional_rating(self):
        rating, note = compute_start_rating(
            self.division,
            self.last_match,
            has_same_or_higher_age_match=False,
            match_count=RATING_VERY_IMMATURE_COUNT,
        )

        self.assertEqual(rating, DEFAULT_RATINGS[BLACK][MASTER_1])
        self.assertEqual(note, f"Adjusted rating for new age division {MASTER_1}")

    def test_new_age_division_preserves_nonprovisional_rating(self):
        rating, note = compute_start_rating(
            self.division,
            self.last_match,
            has_same_or_higher_age_match=False,
            match_count=RATING_VERY_IMMATURE_COUNT + 1,
        )

        self.assertEqual(rating, self.previous_rating)
        self.assertIsNone(note)


class RatingResearchSemanticsTestCase(unittest.TestCase):
    def test_master_8_defaults_follow_belt_spacing(self):
        for belt, expected in [
            (BLACK, 1650),
            (BROWN, 1450),
            (PURPLE, 1250),
            (BLUE, 1050),
            (WHITE, 850),
        ]:
            with self.subTest(belt=belt):
                self.assertEqual(expected, division_default_rating(belt, MASTER_8))

    def test_rating_maturity_boundaries(self):
        self.assertEqual("provisional", rating_maturity(4))
        self.assertEqual("semi_provisional", rating_maturity(5))
        self.assertEqual("semi_provisional", rating_maturity(6))
        self.assertEqual("established", rating_maturity(7))

    def test_division_default_rating_uses_configured_table(self):
        self.assertEqual(2000, division_default_rating(BLACK, ADULT))
        self.assertIsNone(division_default_rating("UNKNOWN", ADULT))

    def test_top_percent_and_elite_tier_boundaries(self):
        self.assertEqual(3.4, rating_top_percent(0.034))
        self.assertEqual("tier1", elite_tier(0.02))
        self.assertEqual("tier2", elite_tier(0.05))
        self.assertEqual("tier3", elite_tier(0.10))
        self.assertIsNone(elite_tier(0.101))


if __name__ == "__main__":
    unittest.main()
