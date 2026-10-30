import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import (
    ADULT,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    MEDIUM_HEAVY,
    MASTER_8,
    age_order,
    age_order_adult_first,
    age_order_all,
    rated_ages,
    canonical_rating_age,
    same_or_higher_progression_ages,
    translate_age_keep_juvenile,
    translate_age,
    translate_weight,
)


class ConstantsTestCase(unittest.TestCase):
    def test_master_8_is_supported_in_age_translation_and_ordering(self):
        self.assertEqual(translate_age("Master 8"), MASTER_8)
        self.assertEqual(translate_age_keep_juvenile("Master 8"), MASTER_8)
        for ages in (age_order, age_order_adult_first, age_order_all, rated_ages):
            self.assertIn(MASTER_8, ages)
        self.assertIn(MASTER_8, same_or_higher_progression_ages(ADULT))

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

    def test_translate_weight_accepts_spaced_portuguese_medium_heavy(self):
        self.assertEqual(translate_weight("Meio Pesado"), MEDIUM_HEAVY)


if __name__ == "__main__":
    unittest.main()
