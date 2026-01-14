import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    AthleteRatingAverage,
    Division,
    Event,
    Match,
    MatchParticipant,
    Medal,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Suspension,
    Team,
)


class AthleteProfileApiTestCase(unittest.TestCase):
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
        db.session.add(team)

        athlete = Athlete(
            name="Test Athlete",
            normalized_name="test athlete",
            slug="test-athlete",
            country="US",
        )
        db.session.add(athlete)

        event = Event(
            name="Test Open",
            normalized_name="test open",
            slug="test-open",
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
        db.session.add_all([event, division])
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
            start_rating=1500.0,
            end_rating=1510.0,
            start_match_count=5,
            end_match_count=6,
        )
        db.session.add(participant)

        rating_avg = AthleteRatingAverage(
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            gi=True,
            weight=LIGHT,
            avg_rating=1400.0,
        )
        rating = AthleteRating(
            athlete_id=athlete.id,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            gi=True,
            weight=LIGHT,
            rating=1550.0,
            match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rank=1,
            percentile=99.0,
            match_count=5,
            previous_rating=1500.0,
            previous_rank=2,
            previous_match_count=4,
            previous_percentile=98.0,
        )
        db.session.add_all([rating_avg, rating])

        medal = Medal(
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            event_id=event.id,
            division_id=division.id,
            athlete_id=athlete.id,
            team_id=team.id,
            place=1,
            default_gold=False,
        )
        db.session.add(medal)

        registration = RegistrationLink(
            name="Test Open",
            event_id="E1",
            normalized_name="test open",
            updated_at=datetime(2024, 1, 1, 10, 0, 0),
            link="https://example.com",
            hidden=False,
            event_start_date=datetime.now() - timedelta(days=1),
            event_end_date=datetime.now() + timedelta(days=10),
        )
        db.session.add(registration)
        db.session.flush()

        registration_competitor = RegistrationLinkCompetitor(
            registration_link_id=registration.id,
            athlete_name=athlete.name,
            team_name=team.name,
            division_id=division.id,
        )
        db.session.add(registration_competitor)

        suspension = Suspension(
            athlete_name=athlete.name,
            start_date=datetime(2024, 1, 10, 0, 0, 0),
            end_date=datetime(2024, 2, 10, 0, 0, 0),
            reason="Test reason",
            suspending_org="Test Org",
        )
        db.session.add(suspension)

        db.session.commit()

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_get_athlete_profile(self):
        response = self.client.get(
            "/api/athlete/test-athlete", query_string={"gi": "true"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["athlete"]["name"], "Test Athlete")
        self.assertEqual(data["athlete"]["belt"], BLACK)
        self.assertEqual(len(data["ranks"]), 1)
        self.assertEqual(len(data["registrations"]), 1)
        self.assertEqual(len(data["medals"]), 1)
        self.assertEqual(len(data["suspensions"]), 1)

    def test_get_athlete_profile_not_found(self):
        response = self.client.get("/api/athlete/missing-athlete")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
