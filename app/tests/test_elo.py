import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, MASTER_1
from elo import DEFAULT_RATINGS, RATING_VERY_IMMATURE_COUNT, compute_start_rating


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


if __name__ == "__main__":
    unittest.main()
