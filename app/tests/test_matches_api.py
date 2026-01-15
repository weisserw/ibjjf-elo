import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import (
    ADULT,
    BLACK,
    BLUE,
    FEMALE,
    LIGHT,
    LIGHT_FEATHER,
    MALE,
)
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team
from test_db import TestDbMixin


class MatchesApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        team = Team(name="Test Team", normalized_name="test team")
        db.session.add(team)

        event1 = Event(
            name="Test Open",
            normalized_name="test open",
            slug="test-open",
            ibjjf_id="E1",
        )
        event2 = Event(
            name="Second Open",
            normalized_name="second open",
            slug="second-open",
            ibjjf_id="E2",
        )
        division1 = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        division2 = Division(
            gi=True,
            gender=FEMALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT_FEATHER,
        )
        db.session.add_all([event1, event2, division1, division2])
        db.session.flush()

        athlete1 = Athlete(
            name="Test Athlete",
            normalized_name="test athlete",
            slug="test-athlete",
        )
        athlete2 = Athlete(
            name="Other Fighter",
            normalized_name="other fighter",
            slug="other-fighter",
        )
        athlete3 = Athlete(
            name="Guest Competitor",
            normalized_name="guest competitor",
            slug="guest-competitor",
        )
        athlete4 = Athlete(
            name="Another Opponent",
            normalized_name="another opponent",
            slug="another-opponent",
        )
        db.session.add_all([athlete1, athlete2, athlete3, athlete4])
        db.session.flush()

        match1 = Match(
            event_id=event1.id,
            division_id=division1.id,
            happened_at=datetime(2024, 1, 1, 12, 0, 0),
            rated=True,
            match_location="Mat 1",
            video_link=None,
        )
        match2 = Match(
            event_id=event2.id,
            division_id=division2.id,
            happened_at=datetime(2024, 1, 2, 12, 0, 0),
            rated=True,
            match_location="Mat 2",
            video_link=None,
        )
        db.session.add_all([match1, match2])
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=match1.id,
                athlete_id=athlete1.id,
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
                match_id=match1.id,
                athlete_id=athlete2.id,
                team_id=team.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1450.0,
                end_rating=1440.0,
                start_match_count=9,
                end_match_count=10,
            ),
            MatchParticipant(
                match_id=match2.id,
                athlete_id=athlete3.id,
                team_id=team.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1300.0,
                end_rating=1310.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=match2.id,
                athlete_id=athlete4.id,
                team_id=team.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1290.0,
                end_rating=1280.0,
                start_match_count=4,
                end_match_count=5,
            ),
        ]
        db.session.add_all(participants)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def _patch_livestreams(self):
        return {
            "tournament_days": {},
            "live_streams": {},
            "flo_event_tags": {},
        }

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_athlete_name(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true&athlete_name=Test%20Athlete")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["winner"], "Test Athlete")

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_event_and_gender(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "event_name": '"Second Open"',
                "gender_female": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["winner"], "Guest Competitor")

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_rating_and_date(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "rating_start": "1500",
                "date_start": "2024-01-01",
                "date_end": "2024-01-01T23:59:59",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["winner"], "Test Athlete")

    def test_matches_requires_gi(self):
        response = self.client.get("/api/matches")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
