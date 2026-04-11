import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BROWN, JUVENILE, LIGHT, MALE, WHITE
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
from routes.brackets import get_ratings
from test_db import TestDbMixin


def _registration_row(name, age, belt):
    return {
        "name": name,
        "team": "Test Team",
        "id": None,
        "ibjjf_id": None,
        "seed": 0,
        "rating": None,
        "match_count": None,
        "rank": None,
        "percentile": None,
        "percentile_age": None,
        "note": None,
        "last_weight": None,
        "slug": None,
        "instagram_profile": None,
        "personal_name": None,
        "profile_image_url": None,
        "country": None,
        "country_note": None,
        "country_note_pt": None,
        "age": age,
        "belt": belt,
        "weight": LIGHT,
        "gender": MALE,
        "gi": True,
    }


class BracketsGetRatingsTestCase(TestDbMixin, unittest.TestCase):
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
        adult_white_division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=WHITE,
            weight=LIGHT,
        )
        adult_brown_division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BROWN,
            weight=LIGHT,
        )
        db.session.add_all([team, event, adult_white_division, adult_brown_division])
        db.session.flush()

        belt_match_name = "Alex SameName"
        cls.belt_white_athlete = Athlete(
            name=belt_match_name,
            normalized_name="alex samename",
            slug="alex-samename-white",
        )
        cls.belt_brown_athlete = Athlete(
            name=belt_match_name,
            normalized_name="alex samename",
            slug="alex-samename-brown",
        )

        age_match_name = "Jamie SameName"
        cls.juvenile_athlete = Athlete(
            name=age_match_name,
            normalized_name="jamie samename",
            slug="jamie-samename-juvenile",
        )
        cls.adult_history_athlete = Athlete(
            name=age_match_name,
            normalized_name="jamie samename",
            slug="jamie-samename-adult",
        )
        match_only_name = "Casey SameName"
        cls.match_only_white_athlete = Athlete(
            name=match_only_name,
            normalized_name="casey samename",
            slug="casey-samename-white",
        )
        cls.match_only_brown_athlete = Athlete(
            name=match_only_name,
            normalized_name="casey samename",
            slug="casey-samename-brown",
        )

        db.session.add_all(
            [
                cls.belt_white_athlete,
                cls.belt_brown_athlete,
                cls.juvenile_athlete,
                cls.adult_history_athlete,
                cls.match_only_white_athlete,
                cls.match_only_brown_athlete,
            ]
        )
        db.session.flush()
        cls.belt_white_athlete_id = cls.belt_white_athlete.id
        cls.belt_white_athlete_slug = cls.belt_white_athlete.slug
        cls.juvenile_athlete_id = cls.juvenile_athlete.id
        cls.juvenile_athlete_slug = cls.juvenile_athlete.slug
        cls.match_only_white_athlete_id = cls.match_only_white_athlete.id
        cls.match_only_white_athlete_slug = cls.match_only_white_athlete.slug

        db.session.add_all(
            [
                AthleteRating(
                    athlete_id=cls.belt_white_athlete.id,
                    gender=MALE,
                    age=ADULT,
                    belt=WHITE,
                    gi=True,
                    weight=LIGHT,
                    rating=1000.0,
                    match_happened_at=datetime(2025, 1, 1),
                    rank=1,
                    percentile=0.01,
                    match_count=10,
                ),
                AthleteRating(
                    athlete_id=cls.belt_brown_athlete.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BROWN,
                    gi=True,
                    weight=LIGHT,
                    rating=1200.0,
                    match_happened_at=datetime(2025, 1, 1),
                    rank=1,
                    percentile=0.01,
                    match_count=10,
                ),
            ]
        )

        adult_history_match = Match(
            event_id=event.id,
            division_id=adult_white_division.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
            match_location="Mat 1",
            video_link=None,
        )
        db.session.add(adult_history_match)
        db.session.flush()

        db.session.add(
            MatchParticipant(
                match_id=adult_history_match.id,
                athlete_id=cls.adult_history_athlete.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1000.0,
                end_rating=1010.0,
                start_match_count=1,
                end_match_count=2,
            )
        )
        brown_history_match = Match(
            event_id=event.id,
            division_id=adult_brown_division.id,
            happened_at=datetime(2024, 1, 2, 10, 0, 0),
            rated=True,
            match_location="Mat 2",
            video_link=None,
        )
        db.session.add(brown_history_match)
        db.session.flush()
        db.session.add(
            MatchParticipant(
                match_id=brown_history_match.id,
                athlete_id=cls.match_only_brown_athlete.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1000.0,
                end_rating=1010.0,
                start_match_count=1,
                end_match_count=2,
            )
        )

        db.session.commit()

    def test_get_ratings_excludes_higher_belt_same_name_match(self):
        rows = [_registration_row("Alex SameName", ADULT, WHITE)]

        with self.app_module.app.app_context():
            get_ratings(
                rows,
                event_id=None,
                gi=True,
                rating_date=datetime(2026, 1, 1),
                use_live_ratings=False,
                s3_client=None,
            )

        self.assertEqual(rows[0]["id"], self.belt_white_athlete_id)
        self.assertEqual(rows[0]["slug"], self.belt_white_athlete_slug)

    def test_get_ratings_excludes_adult_history_for_juvenile_same_name_match(self):
        rows = [_registration_row("Jamie SameName", JUVENILE, WHITE)]

        with self.app_module.app.app_context():
            get_ratings(
                rows,
                event_id=None,
                gi=True,
                rating_date=datetime(2026, 1, 1),
                use_live_ratings=False,
                s3_client=None,
            )

        self.assertEqual(rows[0]["id"], self.juvenile_athlete_id)
        self.assertEqual(rows[0]["slug"], self.juvenile_athlete_slug)

    def test_get_ratings_excludes_higher_belt_from_match_history_same_name_match(self):
        rows = [_registration_row("Casey SameName", ADULT, WHITE)]

        with self.app_module.app.app_context():
            get_ratings(
                rows,
                event_id=None,
                gi=True,
                rating_date=datetime(2026, 1, 1),
                use_live_ratings=False,
                s3_client=None,
            )

        self.assertEqual(rows[0]["id"], self.match_only_white_athlete_id)
        self.assertEqual(rows[0]["slug"], self.match_only_white_athlete_slug)


if __name__ == "__main__":
    unittest.main()
