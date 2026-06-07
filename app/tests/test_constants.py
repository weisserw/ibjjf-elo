import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import (
    ADULT,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    canonical_rating_age,
    same_or_higher_progression_ages,
    translate_age_keep_juvenile,
)


class ConstantsTestCase(unittest.TestCase):
    def test_translate_age_keep_juvenile_preserves_variants(self):
        self.assertEqual(translate_age_keep_juvenile("Juvenile 1"), JUVENILE_1)
        self.assertEqual(translate_age_keep_juvenile("Juvenile 2"), JUVENILE_2)
        self.assertEqual(translate_age_keep_juvenile("Juvenil 1"), JUVENILE_1)
        self.assertEqual(translate_age_keep_juvenile("Juvenil 2"), JUVENILE_2)

    def test_canonical_rating_age_collapses_juvenile_variants(self):
        self.assertEqual(canonical_rating_age(JUVENILE), JUVENILE)
        self.assertEqual(canonical_rating_age(JUVENILE_1), JUVENILE)
        self.assertEqual(canonical_rating_age(JUVENILE_2), JUVENILE)
        self.assertEqual(canonical_rating_age(ADULT), ADULT)

    def test_same_or_higher_progression_ages_keeps_juvenile_variants_together(self):
        ages = same_or_higher_progression_ages(JUVENILE_1)
        self.assertIn(JUVENILE, ages)
        self.assertIn(JUVENILE_1, ages)
        self.assertIn(JUVENILE_2, ages)
        self.assertIn(ADULT, ages)


if __name__ == "__main__":
    unittest.main()
