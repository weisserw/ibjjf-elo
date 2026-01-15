import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team
from test_db import TestDbMixin


class AthleteRatingsApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        team = Team(name="Test Team", normalized_name="test team")
        athlete = Athlete(
            name="Ratings Athlete",
            normalized_name="ratings athlete",
            slug="ratings-athlete",
        )
        event = Event(
            name="Ratings Open",
            normalized_name="ratings open",
            slug="ratings-open",
            ibjjf_id="E1",
            medals_only=False,
        )
        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add_all([team, athlete, event, division])
        db.session.flush()

        match = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        db.session.add(match)
        db.session.flush()

        participant = MatchParticipant(
            match_id=match.id,
            athlete_id=athlete.id,
            team_id=team.id,
            seed=1,
            red=True,
            winner=True,
            start_rating=1400.0,
            end_rating=1450.0,
            start_match_count=5,
            end_match_count=6,
        )
        db.session.add(participant)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_ratings_basic(self):
        response = self.client.get(
            "/api/athletes/ratings",
            query_string={"name": "Ratings Athlete", "gi": "true"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["slug"], "ratings-athlete")
        self.assertEqual(data["rating"], 1450.0)
        self.assertEqual(data["belt"], BLACK)
        self.assertEqual(data["weight"], LIGHT)

    def test_ratings_missing_params(self):
        response = self.client.get("/api/athletes/ratings")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
