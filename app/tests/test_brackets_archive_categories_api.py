import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
from constants import ADULT, BLACK, BLUE, FEMALE, JUVENILE, LIGHT, MALE
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team


class BracketsArchiveCategoriesApiTestCase(unittest.TestCase):
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
            name="Test Event",
            normalized_name="test event",
            slug="test-event",
            ibjjf_id="E1",
            medals_only=False,
        )
        division_blue = Division(
            gi=True,
            gender=FEMALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT,
        )
        division_black = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        division_juvenile = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add_all(
            [team, event, division_blue, division_black, division_juvenile]
        )
        db.session.flush()

        athlete1 = Athlete(
            name="Blue Athlete", normalized_name="blue athlete", slug="blue-athlete"
        )
        athlete2 = Athlete(
            name="Black Athlete", normalized_name="black athlete", slug="black-athlete"
        )
        athlete3 = Athlete(
            name="Juvenile Athlete",
            normalized_name="juvenile athlete",
            slug="juvenile-athlete",
        )
        db.session.add_all([athlete1, athlete2, athlete3])
        db.session.flush()

        match1 = Match(
            event_id=event.id,
            division_id=division_blue.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        match2 = Match(
            event_id=event.id,
            division_id=division_black.id,
            happened_at=datetime(2024, 1, 2, 10, 0, 0),
            rated=True,
        )
        match3 = Match(
            event_id=event.id,
            division_id=division_juvenile.id,
            happened_at=datetime(2024, 1, 3, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([match1, match2, match3])
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=match1.id,
                athlete_id=athlete1.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1200.0,
                end_rating=1210.0,
                start_match_count=1,
                end_match_count=2,
            ),
            MatchParticipant(
                match_id=match2.id,
                athlete_id=athlete2.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1300.0,
                end_rating=1310.0,
                start_match_count=1,
                end_match_count=2,
            ),
            MatchParticipant(
                match_id=match3.id,
                athlete_id=athlete3.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1100.0,
                end_rating=1110.0,
                start_match_count=1,
                end_match_count=2,
            ),
        ]
        db.session.add_all(participants)
        db.session.commit()

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_archive_categories_basic(self):
        response = self.client.get(
            "/api/brackets/archive/categories",
            query_string={"event_name": "Test Event"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 3)
        categories = data["categories"]
        self.assertEqual(len(categories), 2)
        self.assertEqual(categories[0]["belt"], BLUE)
        self.assertEqual(categories[1]["belt"], BLACK)

    def test_archive_categories_missing_param(self):
        response = self.client.get("/api/brackets/archive/categories")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
