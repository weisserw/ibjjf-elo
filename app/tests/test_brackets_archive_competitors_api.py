import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Medal, Team


class BracketsArchiveCompetitorsApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.temp_dir, "test.db")
        app_module.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{cls.db_path}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        with app_module.app.app_context():
            db.drop_all()
            db.create_all()
            cls._seed_data()

    @classmethod
    def tearDownClass(cls):
        with app_module.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(cls.temp_dir)

    @classmethod
    def _seed_data(cls):
        team = Team(name="Test Team", normalized_name="test team")
        event = Event(
            name="Test Event (Results)",
            normalized_name="test event results",
            slug="test-event-results",
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
        db.session.add_all([team, event, division])
        db.session.flush()

        athlete_red = Athlete(
            name="Red Fighter",
            normalized_name="red fighter",
            slug="red-fighter",
        )
        athlete_blue = Athlete(
            name="Blue Fighter",
            normalized_name="blue fighter",
            slug="blue-fighter",
        )
        db.session.add_all([athlete_red, athlete_blue])
        db.session.flush()

        match = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
            match_location="Mat 1",
            video_link=None,
        )
        db.session.add(match)
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=match.id,
                athlete_id=athlete_red.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1500.0,
                end_rating=1510.0,
                start_match_count=10,
                end_match_count=11,
            ),
            MatchParticipant(
                match_id=match.id,
                athlete_id=athlete_blue.id,
                team_id=team.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1450.0,
                end_rating=1440.0,
                start_match_count=9,
                end_match_count=10,
            ),
        ]
        db.session.add_all(participants)

        medal = Medal(
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            event_id=event.id,
            division_id=division.id,
            athlete_id=athlete_red.id,
            team_id=team.id,
            place=1,
            default_gold=False,
        )
        db.session.add(medal)
        db.session.commit()

    def setUp(self):
        self.client = app_module.app.test_client()

    @mock.patch(
        "routes.brackets.get_livestream_link", return_value="https://example.com"
    )
    @mock.patch(
        "routes.brackets.load_livestream_links",
        return_value={"tournament_days": {}, "live_streams": {}, "flo_event_tags": {}},
    )
    @mock.patch("routes.brackets.get_s3_client", return_value=None)
    def test_archive_competitors_basic(self, _mock_s3, _mock_streams, _mock_link):
        response = self.client.get(
            "/api/brackets/archive/competitors",
            query_string={
                "event_name": "Test Event (Results)",
                "age": ADULT,
                "belt": BLACK,
                "weight": LIGHT,
                "gender": MALE,
                "gi": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["competitors"]), 2)
        self.assertEqual(len(data["matches"]), 1)
        self.assertIsNone(data["competitors"][0]["seed"])
        medals = {c["name"]: c["medal"] for c in data["competitors"]}
        self.assertEqual(medals["Red Fighter"], "1")

    def test_archive_competitors_missing_param(self):
        response = self.client.get("/api/brackets/archive/competitors")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
