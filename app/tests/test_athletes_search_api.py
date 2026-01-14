import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
from constants import ADULT, BLUE, FEMALE, LIGHT, MALE, TEEN_1
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team


class AthletesSearchApiTestCase(unittest.TestCase):
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
            name="Search Open",
            normalized_name="search open",
            slug="search-open",
            ibjjf_id="E1",
            medals_only=False,
        )
        division_adult_male = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT,
        )
        division_teen_male = Division(
            gi=True,
            gender=MALE,
            age=TEEN_1,
            belt=BLUE,
            weight=LIGHT,
        )
        division_adult_female = Division(
            gi=True,
            gender=FEMALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add_all(
            [
                team,
                event,
                division_adult_male,
                division_teen_male,
                division_adult_female,
            ]
        )
        db.session.flush()

        adult = Athlete(
            name="Adult Test",
            normalized_name="adult test",
            slug="adult-test",
        )
        teen = Athlete(
            name="Teen Test",
            normalized_name="teen test",
            slug="teen-test",
        )
        female = Athlete(
            name="Female Test",
            normalized_name="female test",
            slug="female-test",
        )
        db.session.add_all([adult, teen, female])
        db.session.flush()

        adult_match = Match(
            event_id=event.id,
            division_id=division_adult_male.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        teen_match = Match(
            event_id=event.id,
            division_id=division_teen_male.id,
            happened_at=datetime(2024, 2, 1, 10, 0, 0),
            rated=True,
        )
        female_match = Match(
            event_id=event.id,
            division_id=division_adult_female.id,
            happened_at=datetime(2024, 1, 15, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([adult_match, teen_match, female_match])
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=adult_match.id,
                athlete_id=adult.id,
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
                match_id=teen_match.id,
                athlete_id=teen.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1100.0,
                end_rating=1110.0,
                start_match_count=1,
                end_match_count=2,
            ),
            MatchParticipant(
                match_id=female_match.id,
                athlete_id=female.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1300.0,
                end_rating=1310.0,
                start_match_count=1,
                end_match_count=2,
            ),
        ]
        db.session.add_all(participants)
        db.session.commit()

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_search_excludes_recent_teen(self):
        response = self.client.get("/api/athletes", query_string={"search": "test"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        names = [row["name"] for row in data]
        self.assertCountEqual(names, ["Adult Test", "Female Test"])

    def test_search_allows_teen(self):
        response = self.client.get(
            "/api/athletes",
            query_string={"search": "test", "allow_teen": "true"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        names = [row["name"] for row in data]
        self.assertCountEqual(names, ["Adult Test", "Female Test", "Teen Test"])

    def test_search_gender_filter(self):
        response = self.client.get(
            "/api/athletes",
            query_string={"search": "test", "gender": FEMALE},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        names = [row["name"] for row in data]
        self.assertEqual(names, ["Female Test"])


if __name__ == "__main__":
    unittest.main()
