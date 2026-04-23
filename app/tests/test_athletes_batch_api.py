import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, BROWN, LIGHT, MALE
from elo import BLACK_PROMOTION_RATING_BUMP, RATING_VERY_IMMATURE_COUNT
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    Division,
    Event,
    Match,
    MatchParticipant,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Team,
)
from test_db import TestDbMixin


class AthletesBatchApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        gi_event = Event(
            name="Batch Open",
            normalized_name="batch open",
            slug="batch-open",
            ibjjf_id="E1",
            medals_only=False,
        )
        no_gi_event = Event(
            name="Batch No-Gi Open",
            normalized_name="batch no-gi open",
            slug="batch-no-gi-open",
            ibjjf_id="E2",
            medals_only=False,
        )
        registration_only_event = RegistrationLink(
            name="Batch Registration No-Gi Open",
            event_id="REG_ONLY",
            normalized_name="batch registration no-gi open",
            updated_at=datetime(2024, 5, 1, 10, 0, 0),
            link="https://example.com/reg-only",
            hidden=False,
            event_start_date=datetime(2024, 5, 10, 10, 0, 0),
            event_end_date=datetime(2024, 5, 11, 10, 0, 0),
        )
        db.session.add_all([gi_event, no_gi_event, registration_only_event])

        athlete_one = Athlete(
            ibjjf_id="A1",
            name="Athlete One Full Name",
            personal_name="Athlete One",
            normalized_name="athlete one full name",
            normalized_personal_name="athlete one",
            hide_full_name=True,
            slug="athlete-one",
            instagram_profile="athleteone",
            country="US",
        )
        athlete_two = Athlete(
            ibjjf_id="B2",
            name="Athlete Two",
            normalized_name="athlete two",
            hide_full_name=False,
            slug="athlete-two",
            instagram_profile="",
            country="",
        )
        athlete_three = Athlete(
            ibjjf_id="C3",
            name="Athlete Three Full Name",
            personal_name=" ",
            normalized_name="athlete three full name",
            hide_full_name=True,
            slug="athlete-three",
            country="BR",
        )
        athlete_four = Athlete(
            ibjjf_id="D4",
            name="Athlete Four",
            normalized_name="athlete four",
            hide_full_name=False,
            slug="athlete-four",
        )
        db.session.add_all([athlete_one, athlete_two, athlete_three, athlete_four])
        db.session.flush()

        ratings = [
            AthleteRating(
                athlete_id=athlete_one.id,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                gi=True,
                weight=LIGHT,
                rating=1600.0,
                match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                rank=1,
                percentile=99.0,
                match_count=RATING_VERY_IMMATURE_COUNT + 1,
                previous_rating=1590.0,
                previous_rank=2,
                previous_match_count=RATING_VERY_IMMATURE_COUNT,
                previous_percentile=98.0,
            ),
            AthleteRating(
                athlete_id=athlete_one.id,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                gi=False,
                weight=LIGHT,
                rating=1510.0,
                match_happened_at=datetime(2024, 2, 1, 10, 0, 0),
                rank=2,
                percentile=95.0,
                match_count=RATING_VERY_IMMATURE_COUNT,
                previous_rating=1500.0,
                previous_rank=3,
                previous_match_count=RATING_VERY_IMMATURE_COUNT - 1,
                previous_percentile=94.0,
            ),
            AthleteRating(
                athlete_id=athlete_two.id,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                gi=False,
                weight=LIGHT,
                rating=1300.0,
                match_happened_at=datetime(2024, 3, 1, 10, 0, 0),
                rank=10,
                percentile=75.0,
                match_count=1,
                previous_rating=1290.0,
                previous_rank=11,
                previous_match_count=0,
                previous_percentile=70.0,
            ),
            AthleteRating(
                athlete_id=athlete_three.id,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                gi=True,
                weight=LIGHT,
                rating=1411.0,
                match_happened_at=datetime(2024, 4, 1, 10, 0, 0),
                rank=30,
                percentile=40.0,
                match_count=RATING_VERY_IMMATURE_COUNT + 5,
                previous_rating=1408.0,
                previous_rank=31,
                previous_match_count=RATING_VERY_IMMATURE_COUNT + 4,
                previous_percentile=39.0,
            ),
        ]
        db.session.add_all(ratings)

        team = Team(name="Batch Team", normalized_name="batch team")
        gi_brown_division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BROWN,
            weight=LIGHT,
        )
        nogi_brown_division = Division(
            gi=False,
            gender=MALE,
            age=ADULT,
            belt=BROWN,
            weight=LIGHT,
        )
        registration_black_division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add_all(
            [team, gi_brown_division, nogi_brown_division, registration_black_division]
        )
        db.session.flush()

        gi_match = Match(
            event_id=gi_event.id,
            division_id=gi_brown_division.id,
            happened_at=datetime(2024, 6, 1, 10, 0, 0),
            rated=True,
        )
        nogi_match = Match(
            event_id=no_gi_event.id,
            division_id=nogi_brown_division.id,
            happened_at=datetime(2024, 7, 1, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([gi_match, nogi_match])
        db.session.flush()

        gi_participant = MatchParticipant(
            match_id=gi_match.id,
            athlete_id=athlete_four.id,
            team_id=team.id,
            seed=1,
            red=True,
            winner=True,
            start_rating=1500.0,
            end_rating=1520.0,
            start_match_count=1,
            end_match_count=2,
        )
        nogi_participant = MatchParticipant(
            match_id=nogi_match.id,
            athlete_id=athlete_four.id,
            team_id=team.id,
            seed=1,
            red=True,
            winner=True,
            start_rating=1490.0,
            end_rating=1510.0,
            start_match_count=2,
            end_match_count=3,
        )
        db.session.add_all([gi_participant, nogi_participant])

        future_registration = RegistrationLink(
            name="Future Batch Open",
            event_id="FUTURE_EVENT",
            normalized_name="future batch open",
            updated_at=datetime(2024, 8, 1, 10, 0, 0),
            link="https://example.com/future-batch",
            hidden=False,
            event_start_date=datetime(2099, 1, 10, 10, 0, 0),
            event_end_date=datetime(2099, 1, 11, 10, 0, 0),
        )
        db.session.add(future_registration)
        db.session.flush()

        future_registration_competitor = RegistrationLinkCompetitor(
            registration_link_id=future_registration.id,
            athlete_name=athlete_four.name,
            team_name=team.name,
            division_id=registration_black_division.id,
        )
        db.session.add(future_registration_competitor)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_batch_lookup_uses_no_gi_event_name_and_sets_provisional(self):
        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "E2"},
            json=["A1", "MISSING", "B2", "C3"],
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual([row["ibjjf_id"] for row in data], ["A1", "B2"])

        first = data[0]
        self.assertEqual(first["name"], "Athlete One")
        self.assertEqual(first["rating"], 1510.0)
        self.assertEqual(first["provisional"], True)
        self.assertEqual(first["slug"], "athlete-one")
        self.assertEqual(first["instagram_profile"], "athleteone")
        self.assertEqual(first["country"], "US")

        second = data[1]
        self.assertEqual(second["name"], "Athlete Two")
        self.assertEqual(second["rating"], 1300.0)
        self.assertEqual(second["provisional"], True)
        self.assertEqual(second["slug"], "athlete-two")
        self.assertNotIn("instagram_profile", second)
        self.assertNotIn("country", second)

    def test_batch_lookup_uses_registration_link_event_name_when_event_missing(self):
        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "REG_ONLY"},
            json=["A1", "B2", "C3"],
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual([row["ibjjf_id"] for row in data], ["A1", "B2"])
        self.assertEqual(data[0]["rating"], 1510.0)
        self.assertEqual(data[0]["provisional"], True)
        self.assertEqual(data[1]["rating"], 1300.0)
        self.assertEqual(data[1]["provisional"], True)

    def test_batch_lookup_uses_gi_event_name_and_hides_full_name_without_personal_name(
        self,
    ):
        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "E1"},
            json=["A1", "B2", "C3"],
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual([row["ibjjf_id"] for row in data], ["A1", "C3"])

        first = data[0]
        self.assertEqual(first["rating"], 1600.0)
        self.assertEqual(first["provisional"], False)

        third = data[1]
        self.assertEqual(third["rating"], 1411.0)
        self.assertEqual(third["provisional"], False)
        self.assertNotIn("name", third)
        self.assertEqual(third["country"], "BR")

    def test_batch_lookup_without_event_id_returns_gi_and_no_gi_ratings(self):
        response = self.client.post("/api/athletes/batch", json=["A1"])
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ibjjf_id"], "A1")
        self.assertEqual(data[0]["rating"], 1600.0)
        self.assertEqual(data[0]["nogi-rating"], 1510.0)
        self.assertEqual(data[0]["provisional"], False)

    def test_batch_lookup_falls_back_to_latest_match_and_applies_promotion_bump(self):
        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "E1"},
            json=["D4"],
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ibjjf_id"], "D4")
        self.assertEqual(data[0]["rating"], 1520.0 + BLACK_PROMOTION_RATING_BUMP)
        self.assertEqual(data[0]["provisional"], True)

    def test_batch_lookup_without_event_id_uses_fallback_for_gi_and_no_gi(self):
        response = self.client.post("/api/athletes/batch", json=["D4"])
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ibjjf_id"], "D4")
        self.assertEqual(data[0]["rating"], 1520.0 + BLACK_PROMOTION_RATING_BUMP)
        self.assertEqual(data[0]["nogi-rating"], 1510.0 + BLACK_PROMOTION_RATING_BUMP)
        self.assertEqual(data[0]["provisional"], True)

    def test_batch_lookup_requires_json_array_of_strings(self):
        response = self.client.post(
            "/api/athletes/batch",
            json={"ids": ["A1"]},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "E1"},
            json={"ids": ["A1"]},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "E1"},
            json=["A1", 2],
        )
        self.assertEqual(response.status_code, 400)

    def test_batch_lookup_event_not_found(self):
        response = self.client.post(
            "/api/athletes/batch",
            query_string={"event_id": "MISSING"},
            json=["A1"],
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
