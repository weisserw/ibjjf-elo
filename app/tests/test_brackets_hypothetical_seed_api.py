import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLUE, LIGHT, MALE
from extensions import db
from models import Athlete, Division, RegistrationLink, RegistrationLinkCompetitor
from test_db import TestDbMixin


class BracketsHypotheticalSeedApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add(division)
        db.session.flush()

        link = RegistrationLink(
            name="Test Open",
            normalized_name="test open",
            updated_at=datetime(2026, 1, 1),
            link="internal:test-open",
            event_start_date=datetime(2026, 6, 1),
            event_end_date=datetime(2026, 6, 2),
        )
        db.session.add(link)
        db.session.flush()

        db.session.add_all(
            [
                RegistrationLinkCompetitor(
                    registration_link_id=link.id,
                    athlete_name="Registered One",
                    team_name="Team One",
                    division_id=division.id,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=link.id,
                    athlete_name="Registered Two",
                    team_name="Team Two",
                    division_id=division.id,
                ),
            ]
        )

        cls.hypothetical_athlete = Athlete(
            name="Hypothetical Athlete",
            normalized_name="hypothetical athlete",
            slug="hypothetical-athlete",
        )
        cls.registered_athlete = Athlete(
            name="Registered One",
            normalized_name="registered one",
            slug="registered-one",
        )
        db.session.add_all([cls.hypothetical_athlete, cls.registered_athlete])
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_hypothetical_seed_returns_temporary_row_without_persisting(self):
        response = self.client.get(
            "/api/brackets/registrations/hypothetical_seed",
            query_string={
                "link": "internal:test-open",
                "division": f"{BLUE} / {ADULT} / {MALE} / {LIGHT}",
                "gi": "true",
                "athlete_slug": "hypothetical-athlete",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        names = [row["name"] for row in data["competitors"]]
        self.assertCountEqual(
            names,
            ["Registered One", "Registered Two", "Hypothetical Athlete"],
        )

        hypothetical_rows = [
            row for row in data["competitors"] if row.get("hypothetical")
        ]
        self.assertEqual(len(hypothetical_rows), 1)
        self.assertIsNotNone(hypothetical_rows[0]["est_seed"])

        regular_response = self.client.get(
            "/api/brackets/registrations/competitors",
            query_string={
                "link": "internal:test-open",
                "division": f"{BLUE} / {ADULT} / {MALE} / {LIGHT}",
                "gi": "true",
            },
        )
        regular_names = [
            row["name"] for row in regular_response.get_json()["competitors"]
        ]
        self.assertCountEqual(regular_names, ["Registered One", "Registered Two"])

    def test_hypothetical_seed_rejects_registered_athlete(self):
        response = self.client.get(
            "/api/brackets/registrations/hypothetical_seed",
            query_string={
                "link": "internal:test-open",
                "division": f"{BLUE} / {ADULT} / {MALE} / {LIGHT}",
                "gi": "true",
                "athlete_slug": "registered-one",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "Athlete is already registered")


if __name__ == "__main__":
    unittest.main()
