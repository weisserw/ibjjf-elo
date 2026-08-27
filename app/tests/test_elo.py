import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, MASTER_1
from elo import (
    DEFAULT_RATINGS,
    RATING_VERY_IMMATURE_COUNT,
    compute_start_rating,
    division_default_rating,
    elite_tier,
    rating_maturity,
    rating_top_percent,
)


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
