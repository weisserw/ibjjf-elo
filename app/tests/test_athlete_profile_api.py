import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import (
    Athlete,
    AthleteMediaCoverage,
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
from test_db import TestDbMixin


class AthleteProfileApiTestCase(TestDbMixin, unittest.TestCase):

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
        other_athlete = Athlete(
            name="Other Athlete",
            normalized_name="other athlete",
            slug="other-athlete",
        )
        no_media_athlete = Athlete(
            name="No Media Athlete",
            normalized_name="no media athlete",
            slug="no-media-athlete",
        )
        db.session.add_all([athlete, other_athlete, no_media_athlete])

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

        db.session.add_all(
            [
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 5, 1),
                    coverage_type="feature",
                    url="https://example.com/feature",
                    title="Feature Story",
                    created_at=datetime(2024, 5, 1, 10, 0, 0),
                    updated_at=datetime(2024, 5, 1, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 1),
                    coverage_type="news",
                    url="https://example.com/news",
                    title="News Story",
                    created_at=datetime(2024, 6, 1, 10, 0, 0),
                    updated_at=datetime(2024, 6, 1, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 1),
                    coverage_type="video",
                    url="https://example.com/video",
                    title="Video Story",
                    created_at=datetime(2024, 6, 1, 11, 0, 0),
                    updated_at=datetime(2024, 6, 1, 11, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 2),
                    coverage_type="podcast",
                    url="https://example.com/podcast",
                    title="Podcast Story",
                    portuguese=True,
                    created_at=datetime(2024, 6, 2, 10, 0, 0),
                    updated_at=datetime(2024, 6, 2, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 3),
                    coverage_type="highlight",
                    url="https://example.com/highlight",
                    title="Highlight Story",
                    created_at=datetime(2024, 6, 3, 10, 0, 0),
                    updated_at=datetime(2024, 6, 3, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 4),
                    coverage_type="technique",
                    url="https://example.com/technique",
                    title="Technique Story",
                    created_at=datetime(2024, 6, 4, 10, 0, 0),
                    updated_at=datetime(2024, 6, 4, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 5),
                    coverage_type="interview",
                    url="https://example.com/interview",
                    title="Interview Story",
                    created_at=datetime(2024, 6, 5, 10, 0, 0),
                    updated_at=datetime(2024, 6, 5, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=athlete.id,
                    covered_at=date(2024, 6, 6),
                    coverage_type="breakdown",
                    url="https://example.com/breakdown",
                    title="Breakdown Story",
                    created_at=datetime(2024, 6, 6, 10, 0, 0),
                    updated_at=datetime(2024, 6, 6, 10, 0, 0),
                ),
                AthleteMediaCoverage(
                    athlete_id=other_athlete.id,
                    covered_at=date(2024, 7, 1),
                    coverage_type="news",
                    url="https://example.com/other",
                    title="Other Athlete Story",
                    created_at=datetime(2024, 7, 1, 10, 0, 0),
                    updated_at=datetime(2024, 7, 1, 10, 0, 0),
                ),
            ]
        )

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
        self.client = self.app_module.app.test_client()

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
        self.assertEqual(
            [
                (
                    row["date"],
                    row["type"],
                    row["title"],
                    row["url"],
                    row["portuguese"],
                )
                for row in data["mediaCoverage"]
            ],
            [
                (
                    "2024-06-06",
                    "breakdown",
                    "Breakdown Story",
                    "https://example.com/breakdown",
                    False,
                ),
                (
                    "2024-06-05",
                    "interview",
                    "Interview Story",
                    "https://example.com/interview",
                    False,
                ),
                (
                    "2024-06-04",
                    "technique",
                    "Technique Story",
                    "https://example.com/technique",
                    False,
                ),
                (
                    "2024-06-03",
                    "highlight",
                    "Highlight Story",
                    "https://example.com/highlight",
                    False,
                ),
                (
                    "2024-06-02",
                    "podcast",
                    "Podcast Story",
                    "https://example.com/podcast",
                    True,
                ),
                (
                    "2024-06-01",
                    "video",
                    "Video Story",
                    "https://example.com/video",
                    False,
                ),
                (
                    "2024-06-01",
                    "news",
                    "News Story",
                    "https://example.com/news",
                    False,
                ),
                (
                    "2024-05-01",
                    "feature",
                    "Feature Story",
                    "https://example.com/feature",
                    False,
                ),
            ],
        )
        self.assertNotIn(
            "Other Athlete Story",
            [row["title"] for row in data["mediaCoverage"]],
        )

    def test_get_athlete_profile_without_media_coverage(self):
        response = self.client.get("/api/athlete/no-media-athlete")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["mediaCoverage"], [])

    def test_get_athlete_profile_not_found(self):
        response = self.client.get("/api/athlete/missing-athlete")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
