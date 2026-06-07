import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import BLUE, JUVENILE, JUVENILE_1, JUVENILE_2, LIGHT, MALE
from current import generate_current_ratings
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    Division,
    Event,
    Match,
    MatchParticipant,
    Team,
)
from test_db import TestDbMixin


class CurrentRatingsJuvenileTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        team = Team(name="Juvenile Team", normalized_name="juvenile team")
        event = Event(
            name="Juvenile Ratings Open",
            normalized_name="juvenile ratings open",
            slug="juvenile-ratings-open",
            ibjjf_id="juvenile-ratings",
        )
        division_1 = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE_1,
            belt=BLUE,
            weight=LIGHT,
        )
        division_2 = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE_2,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add_all([team, event, division_1, division_2])
        db.session.flush()

        athletes = [
            Athlete(
                name=f"Juvenile Rating Athlete {index}",
                normalized_name=f"juvenile rating athlete {index}",
                slug=f"juvenile-rating-athlete-{index}",
            )
            for index in range(1, 5)
        ]
        db.session.add_all(athletes)
        db.session.flush()

        happened_at = datetime.now() - timedelta(days=1)
        match_1 = Match(
            event_id=event.id,
            division_id=division_1.id,
            happened_at=happened_at,
            rated=True,
        )
        match_2 = Match(
            event_id=event.id,
            division_id=division_2.id,
            happened_at=happened_at + timedelta(minutes=1),
            rated=True,
        )
        db.session.add_all([match_1, match_2])
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=match_1.id,
                athlete_id=athletes[0].id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1400.0,
                end_rating=1420.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=match_1.id,
                athlete_id=athletes[1].id,
                team_id=team.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1400.0,
                end_rating=1380.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=match_2.id,
                athlete_id=athletes[2].id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1400.0,
                end_rating=1430.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=match_2.id,
                athlete_id=athletes[3].id,
                team_id=team.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1400.0,
                end_rating=1370.0,
                start_match_count=5,
                end_match_count=6,
            ),
        ]
        db.session.add_all(participants)
        db.session.commit()

        generate_current_ratings(db, gi=True, nogi=False, rank_previous_date=None)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_current_ratings_collapse_juvenile_variants(self):
        with self.app_module.app.app_context():
            rows = db.session.query(AthleteRating).all()
        self.assertGreater(len(rows), 0)
        self.assertEqual({row.age for row in rows}, {JUVENILE})

    @mock.patch("routes.top.get_s3_client", return_value=None)
    def test_top_returns_combined_juvenile_pool(self, _mock_s3):
        response = self.client.get(
            "/api/top",
            query_string={
                "gender": MALE,
                "age": JUVENILE,
                "belt": BLUE,
                "gi": "true",
                "weight": LIGHT,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 4)


if __name__ == "__main__":
    unittest.main()
