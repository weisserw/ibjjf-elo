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
    MASTER_1,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
)
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


class MatchesApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        team1 = Team(name="Test Team", normalized_name="test team")
        team2 = Team(name="Another Squad", normalized_name="another squad")
        team3 = Team(name="Juvenile Team", normalized_name="juvenile team")
        db.session.add_all([team1, team2, team3])

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
        division_juvenile = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE,
            belt=BLUE,
            weight=LIGHT,
        )
        division_juvenile_1 = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE_1,
            belt=BLUE,
            weight=LIGHT,
        )
        division_juvenile_2 = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE_2,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add_all(
            [
                event1,
                event2,
                division1,
                division2,
                division_juvenile,
                division_juvenile_1,
                division_juvenile_2,
            ]
        )
        db.session.flush()

        athlete1 = Athlete(
            name="Test Athlete",
            normalized_name="test athlete",
            slug="test-athlete",
            country="us",
        )
        athlete2 = Athlete(
            name="Other Fighter",
            normalized_name="other fighter",
            slug="other-fighter",
            country="us",
        )
        athlete3 = Athlete(
            name="Guest Competitor",
            normalized_name="guest competitor",
            slug="guest-competitor",
            country="br",
        )
        athlete4 = Athlete(
            name="Another Opponent",
            normalized_name="another opponent",
            slug="another-opponent",
            country="br",
        )
        juvenile_athletes = [
            Athlete(
                name=f"Juvenile Athlete {index}",
                normalized_name=f"juvenile athlete {index}",
                slug=f"juvenile-athlete-{index}",
                country="us",
            )
            for index in range(1, 7)
        ]
        db.session.add_all([athlete1, athlete2, athlete3, athlete4, *juvenile_athletes])
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
        # Two DQ-type matches, one per DQ type
        match_dq_technical = Match(
            event_id=event1.id,
            division_id=division1.id,
            happened_at=datetime(2024, 2, 1, 12, 0, 0),
            rated=True,
            match_location="Mat 3",
            video_link=None,
        )
        match_dq_disciplinary = Match(
            event_id=event1.id,
            division_id=division1.id,
            happened_at=datetime(2024, 2, 2, 12, 0, 0),
            rated=True,
            match_location="Mat 4",
            video_link=None,
        )
        juvenile_matches = [
            Match(
                event_id=event1.id,
                division_id=division.id,
                happened_at=datetime(2024, 3, index, 12, 0, 0),
                rated=True,
                match_location=f"Mat {index + 4}",
                video_link=None,
            )
            for index, division in enumerate(
                [division_juvenile, division_juvenile_1, division_juvenile_2],
                start=1,
            )
        ]
        db.session.add_all(
            [
                match1,
                match2,
                match_dq_technical,
                match_dq_disciplinary,
                *juvenile_matches,
            ]
        )
        db.session.flush()

        participants = [
            MatchParticipant(
                match_id=match1.id,
                athlete_id=athlete1.id,
                team_id=team1.id,
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
                team_id=team1.id,
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
                team_id=team2.id,
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
                team_id=team2.id,
                seed=2,
                red=False,
                winner=False,
                note="Disqualified by technical desc.",
                start_rating=1290.0,
                end_rating=1280.0,
                start_match_count=4,
                end_match_count=5,
            ),
            # DQ-type match: technical
            MatchParticipant(
                match_id=match_dq_technical.id,
                athlete_id=athlete1.id,
                team_id=team1.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1500.0,
                end_rating=1505.0,
                start_match_count=11,
                end_match_count=12,
            ),
            MatchParticipant(
                match_id=match_dq_technical.id,
                athlete_id=athlete2.id,
                team_id=team1.id,
                seed=2,
                red=False,
                winner=False,
                note="Disqualified by technical desc.",
                start_rating=1440.0,
                end_rating=1435.0,
                start_match_count=10,
                end_match_count=11,
            ),
            # DQ-type match: disciplinary
            MatchParticipant(
                match_id=match_dq_disciplinary.id,
                athlete_id=athlete1.id,
                team_id=team1.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1505.0,
                end_rating=1510.0,
                start_match_count=12,
                end_match_count=13,
            ),
            MatchParticipant(
                match_id=match_dq_disciplinary.id,
                athlete_id=athlete2.id,
                team_id=team1.id,
                seed=2,
                red=False,
                winner=False,
                note="Disqualified by disciplinary desc.",
                start_rating=1435.0,
                end_rating=1430.0,
                start_match_count=11,
                end_match_count=12,
            ),
        ]
        for index, match in enumerate(juvenile_matches):
            red_athlete = juvenile_athletes[index * 2]
            blue_athlete = juvenile_athletes[index * 2 + 1]
            participants.extend(
                [
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=red_athlete.id,
                        team_id=team3.id,
                        seed=1,
                        red=True,
                        winner=True,
                        start_rating=1200.0,
                        end_rating=1210.0,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=blue_athlete.id,
                        team_id=team3.id,
                        seed=2,
                        red=False,
                        winner=False,
                        start_rating=1200.0,
                        end_rating=1190.0,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                ]
            )
        db.session.add_all(participants)

        ratings = [
            AthleteRating(
                athlete_id=athlete1.id,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                gi=True,
                weight=LIGHT,
                rating=1500.0,
                match_happened_at=datetime(2024, 1, 1, 12, 0, 0),
                rank=1,
                percentile=0.104,
                match_count=5,
            ),
            AthleteRating(
                athlete_id=athlete3.id,
                gender=FEMALE,
                age=MASTER_1,
                belt=BLUE,
                gi=True,
                weight=LIGHT_FEATHER,
                rating=1300.0,
                match_happened_at=datetime(2024, 1, 2, 12, 0, 0),
                rank=1,
                percentile=0.01,
                match_count=5,
            ),
            AthleteRating(
                athlete_id=athlete4.id,
                gender=FEMALE,
                age=ADULT,
                belt=BLUE,
                gi=True,
                weight=LIGHT_FEATHER,
                rating=1290.0,
                match_happened_at=datetime(2024, 1, 2, 12, 0, 0),
                rank=2,
                percentile=0.105,
                match_count=5,
            ),
        ]
        db.session.add_all(ratings)
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
        # athlete1 ("Test Athlete") participates in match1 + 2 DQ-type matches = 3 total
        self.assertEqual(len(data["rows"]), 3)
        winners = {row["winner"] for row in data["rows"]}
        self.assertIn("Test Athlete", winners)

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
    def test_matches_filter_by_team_name_partial(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "team_name": "test",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        # team1 ("Test Team") is in match1 + 2 DQ-type matches = 3 total
        self.assertEqual(len(data["rows"]), 3)
        winners = {row["winner"] for row in data["rows"]}
        self.assertIn("Test Athlete", winners)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_team_name_exact(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "team_name": '"Another Squad"',
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["winner"], "Guest Competitor")

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_team_name_or_athlete_name(
        self, mock_livestreams, _mock_s3
    ):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "athlete_name": "Does Not Exist",
                "team_name": '"Another Squad"',
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["winner"], "Guest Competitor")

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_country(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "country": "br",
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

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_filter_by_elite_only(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches",
            query_string={
                "gi": "true",
                "elite_only": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        # athlete1 (elite, percentile=0.104) is in match1 + 2 DQ-type matches = 3 total
        self.assertEqual(len(data["rows"]), 3)
        winners = {row["winner"] for row in data["rows"]}
        self.assertIn("Test Athlete", winners)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_dq_type_technical(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true&dq_type_technical=true")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 2)
        notes = {row["notes"] for row in data["rows"]}
        self.assertIn("Disqualified by technical desc.", notes)
        self.assertNotIn("Disqualified by disciplinary desc.", notes)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_dq_type_disciplinary(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true&dq_type_disciplinary=true")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 1)
        notes = {row["notes"] for row in data["rows"]}
        self.assertIn("Disqualified by disciplinary desc.", notes)
        self.assertNotIn("Disqualified by technical desc.", notes)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_dq_type_both(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get(
            "/api/matches?gi=true&dq_type_technical=true&dq_type_disciplinary=true"
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 3)
        notes = {row["notes"] for row in data["rows"]}
        self.assertIn("Disqualified by technical desc.", notes)
        self.assertIn("Disqualified by disciplinary desc.", notes)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_dq_type_invalid(self, mock_livestreams, _mock_s3):
        # dq_type_technical/disciplinary are booleans; an unrecognised value is treated as falsy
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true&dq_type_technical=false")
        self.assertEqual(response.status_code, 200)

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_matches_juvenile_filter_includes_all_juvenile_variants(
        self, mock_livestreams, _mock_s3
    ):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true&age_juvenile=true")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 3)
        ages = {row["age"] for row in data["rows"]}
        self.assertEqual(ages, {JUVENILE, JUVENILE_1, JUVENILE_2})

    @mock.patch("routes.matches.get_s3_client", return_value=None)
    @mock.patch("routes.matches.load_livestream_links")
    def test_dq_type_omitted(self, mock_livestreams, _mock_s3):
        mock_livestreams.return_value = self._patch_livestreams()
        response = self.client.get("/api/matches?gi=true")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        all_notes = set()
        for row in data["rows"]:
            if row.get("notes"):
                all_notes.add(row["notes"])
        self.assertIn("Disqualified by technical desc.", all_notes)
        self.assertIn("Disqualified by disciplinary desc.", all_notes)

    def test_matches_requires_gi(self):
        response = self.client.get("/api/matches")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
