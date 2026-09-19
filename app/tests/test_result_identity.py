import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from models import Athlete, ManualPromotions
from result_identity import abbreviated_name_key, initial_surname_key, resolve_identity
from test_db import TestDbMixin


class KeyTest(unittest.TestCase):
    def test_name_keys(self):
        for full, abbreviation, key in (
            ("João Silva", "J. Silva", "j silva"),
            ("Anne-Marie Smith-Jones", "A. Smith-Jones", "a smithjones"),
        ):
            with self.subTest(full=full):
                self.assertEqual(initial_surname_key(full), key)
                self.assertEqual(abbreviated_name_key(abbreviation), key)
        self.assertIsNone(initial_surname_key(""))
        self.assertIsNone(abbreviated_name_key("John Smith"))
        self.assertIsNone(abbreviated_name_key("E. Jovany Varela"))
        self.assertIsNone(abbreviated_name_key("M. I. David Onuma"))
        self.assertIsNone(abbreviated_name_key("J. da Silva"))
        self.assertIsNone(abbreviated_name_key("C. Gracie Jr."))
        self.assertEqual(abbreviated_name_key("E. Varela"), "e varela")


class ResolverTest(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.context = self.app_module.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.query(ManualPromotions).delete()
        db.session.query(Athlete).delete()
        db.session.commit()
        self.context.pop()

    def _athlete(self, name, slug):
        athlete = Athlete(name=name, normalized_name=name.lower(), slug=slug)
        db.session.add(athlete)
        db.session.commit()
        return athlete

    def test_unique_and_same_initial_collision(self):
        first = self._athlete("John Smith", "john-smith")
        self.assertEqual(first.normalized_initial_surname, "j smith")
        result = resolve_identity(db.session, "J. Smith")
        self.assertEqual((result.status, result.athlete.id), ("matched", first.id))
        self._athlete("Jane Smith", "jane-smith")
        self.assertEqual(resolve_identity(db.session, "J. Smith").status, "ambiguous")

    def test_middle_name_disappears_from_abbreviation(self):
        first = self._athlete("John Michael Silva", "john-silva")
        self.assertEqual(resolve_identity(db.session, "J. Silva").athlete.id, first.id)

    def test_rename_refreshes_index_and_duplicate_full_names_stay_ambiguous(self):
        first = self._athlete("John Smith", "john-smith")
        first.name = "John Brown"
        first.normalized_name = "john brown"
        db.session.commit()
        self.assertEqual(first.normalized_initial_surname, "j brown")
        self.assertEqual(resolve_identity(db.session, "J. Smith").status, "unmatched")
        self._athlete("John Brown", "john-brown-2")
        self.assertEqual(resolve_identity(db.session, "John Brown").status, "ambiguous")
        self.assertEqual(resolve_identity(db.session, "J. Brown").status, "ambiguous")

    def test_history_exclusions_and_team_tie_break(self):
        first = self._athlete("John Smith", "john-smith")
        second = self._athlete("Jane Smith", "jane-smith")
        when = datetime(2025, 1, 1)
        with patch("result_identity._history") as history:
            history.side_effect = lambda _s, athlete_id, _when: (
                ({"Male"}, set(), set(), [(when, "team a")])
                if athlete_id == first.id
                else ({"Female"}, set(), set(), [(when, "team b")])
            )
            self.assertEqual(
                resolve_identity(db.session, "J. Smith", gender="Female").athlete.id,
                second.id,
            )
            self.assertEqual(
                resolve_identity(
                    db.session, "J. Smith", team="Team A", when=when
                ).athlete.id,
                first.id,
            )
            self.assertEqual(
                resolve_identity(db.session, "J. Smith").status, "ambiguous"
            )

    def test_belt_and_age_history_reject(self):
        self._athlete("John Smith", "john-smith")
        with patch(
            "result_identity._history", return_value=(set(), {"Adult"}, {3}, [])
        ):
            self.assertEqual(
                resolve_identity(
                    db.session,
                    "J. Smith",
                    age="Juvenile",
                    belt="BLUE",
                    when=datetime(2025, 1, 1),
                ).status,
                "unmatched",
            )

    def test_manual_promotion_only_rejects_later_lower_belt(self):
        first = self._athlete("John Smith", "john-smith")
        db.session.add(
            ManualPromotions(
                athlete_id=first.id, belt="PURPLE", promoted_at=datetime(2025, 6, 1)
            )
        )
        db.session.commit()
        self.assertEqual(
            resolve_identity(
                db.session, "J. Smith", belt="BLUE", when=datetime(2025, 1, 1)
            ).status,
            "matched",
        )
        self.assertEqual(
            resolve_identity(
                db.session, "J. Smith", belt="BLUE", when=datetime(2026, 1, 1)
            ).status,
            "unmatched",
        )

    def test_crowded_initial_uses_bulk_history_and_stays_ambiguous(self):
        for index in range(9):
            self._athlete(f"Jname{index} Common", f"jname-{index}-common")
        result = resolve_identity(
            db.session,
            "J. Common",
            gender="Male",
            belt="BLUE",
            age="Adult",
            when=datetime(2025, 1, 1),
        )
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(len(result.candidates), 9)


if __name__ == "__main__":
    unittest.main()
