import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, BROWN, LIGHT, MALE, WHITE
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    Division,
    Event,
    Match,
    MatchParticipant,
    Medal,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Team,
    TeamNameMapping,
)
from normalize import normalize
from test_db import TestDbMixin


class TeamsApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        canonical_team = Team(
            name="Alliance Jiu Jitsu",
            normalized_name=normalize("Alliance Jiu Jitsu"),
        )
        mapped_team_star = Team(
            name="Alliance Jiu Jitsu HQ",
            normalized_name=normalize("Alliance Jiu Jitsu HQ"),
        )
        mapped_team_qmark = Team(
            name="Alliance Jiu Jitsu A",
            normalized_name=normalize("Alliance Jiu Jitsu A"),
        )
        unrelated_team = Team(
            name="Unrelated Team",
            normalized_name=normalize("Unrelated Team"),
        )
        db.session.add_all(
            [canonical_team, mapped_team_star, mapped_team_qmark, unrelated_team]
        )
        db.session.flush()

        db.session.add_all(
            [
                TeamNameMapping(
                    name_match="Alliance Jiu Jitsu*",
                    mapped_name=canonical_team.name,
                ),
                TeamNameMapping(
                    name_match="Alliance Jiu Jitsu ?",
                    mapped_name=canonical_team.name,
                ),
            ]
        )

        elite_from_medal = Athlete(
            name="Elite Medal",
            normalized_name=normalize("Elite Medal"),
            slug="elite-medal",
        )
        elite_from_match = Athlete(
            name="Elite Match",
            normalized_name=normalize("Elite Match"),
            slug="elite-match",
        )
        elite_white = Athlete(
            name="Elite White",
            normalized_name=normalize("Elite White"),
            slug="elite-white",
        )
        non_elite = Athlete(
            name="Non Elite",
            normalized_name=normalize("Non Elite"),
            slug="non-elite",
        )
        elite_unrelated_team = Athlete(
            name="Elite Unrelated",
            normalized_name=normalize("Elite Unrelated"),
            slug="elite-unrelated",
        )
        db.session.add_all(
            [
                elite_from_medal,
                elite_from_match,
                elite_white,
                non_elite,
                elite_unrelated_team,
            ]
        )
        db.session.flush()

        db.session.add_all(
            [
                AthleteRating(
                    athlete_id=elite_from_medal.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BLACK,
                    gi=True,
                    weight=LIGHT,
                    rating=1800,
                    match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                    percentile=0.09,
                    match_count=15,
                ),
                AthleteRating(
                    athlete_id=elite_from_match.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BROWN,
                    gi=True,
                    weight=LIGHT,
                    rating=1700,
                    match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                    percentile=0.01,
                    match_count=14,
                ),
                AthleteRating(
                    athlete_id=elite_white.id,
                    gender=MALE,
                    age=ADULT,
                    belt=WHITE,
                    gi=True,
                    weight=LIGHT,
                    rating=1900,
                    match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                    percentile=0.001,
                    match_count=20,
                ),
                AthleteRating(
                    athlete_id=non_elite.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BLACK,
                    gi=True,
                    weight=LIGHT,
                    rating=1600,
                    match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                    percentile=0.25,
                    match_count=20,
                ),
                AthleteRating(
                    athlete_id=elite_unrelated_team.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BLACK,
                    gi=True,
                    weight=LIGHT,
                    rating=1750,
                    match_happened_at=datetime(2024, 1, 1, 10, 0, 0),
                    percentile=0.04,
                    match_count=20,
                ),
            ]
        )

        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        event = Event(
            name="Team Test Event",
            normalized_name=normalize("Team Test Event"),
            slug="team-test-event",
            ibjjf_id="TEAMTEST1",
        )
        db.session.add_all([division, event])
        db.session.flush()

        match = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 2, 10, 0, 0),
            rated=True,
        )
        latest_match = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 4, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([match, latest_match])
        db.session.flush()

        reg_link = RegistrationLink(
            name="Upcoming Event",
            event_id="UP1",
            normalized_name=normalize("Upcoming Event"),
            updated_at=datetime.now(),
            link="https://example.com/upcoming",
            event_start_date=datetime.now() + timedelta(days=3),
            event_end_date=datetime.now() + timedelta(days=7),
        )
        db.session.add(reg_link)
        db.session.flush()

        db.session.add_all(
            [
                Medal(
                    happened_at=datetime(2024, 1, 3, 10, 0, 0),
                    event_id=event.id,
                    division_id=division.id,
                    athlete_id=elite_from_medal.id,
                    team_id=mapped_team_star.id,
                    place=1,
                    default_gold=False,
                ),
                Medal(
                    happened_at=datetime(2024, 1, 3, 10, 0, 0),
                    event_id=event.id,
                    division_id=division.id,
                    athlete_id=elite_white.id,
                    team_id=canonical_team.id,
                    place=1,
                    default_gold=False,
                ),
                Medal(
                    happened_at=datetime(2024, 1, 3, 10, 0, 0),
                    event_id=event.id,
                    division_id=division.id,
                    athlete_id=non_elite.id,
                    team_id=canonical_team.id,
                    place=2,
                    default_gold=False,
                ),
                Medal(
                    happened_at=datetime(2024, 1, 3, 10, 0, 0),
                    event_id=event.id,
                    division_id=division.id,
                    athlete_id=elite_unrelated_team.id,
                    team_id=unrelated_team.id,
                    place=1,
                    default_gold=False,
                ),
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=elite_from_match.id,
                    team_id=mapped_team_qmark.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1700,
                    end_rating=1710,
                    start_match_count=10,
                    end_match_count=11,
                ),
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=elite_unrelated_team.id,
                    team_id=unrelated_team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1750,
                    end_rating=1740,
                    start_match_count=12,
                    end_match_count=13,
                ),
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=elite_from_medal.id,
                    team_id=mapped_team_star.id,
                    seed=3,
                    red=True,
                    winner=True,
                    start_rating=1790,
                    end_rating=1800,
                    start_match_count=14,
                    end_match_count=15,
                ),
                MatchParticipant(
                    match_id=latest_match.id,
                    athlete_id=elite_from_match.id,
                    team_id=unrelated_team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1700,
                    end_rating=1715,
                    start_match_count=14,
                    end_match_count=15,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=reg_link.id,
                    athlete_name=elite_from_match.name,
                    team_name="Alliance Jiu Jitsu B",
                    division_id=division.id,
                ),
            ]
        )

        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_team_elites_lookup_from_slug_and_mappings(self):
        response = self.client.get("/api/teams/alliance-jiu-jitsu")
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data["team_name"], "Alliance Jiu Jitsu")
        self.assertNotIn("team_slug", data)

        names = [row["athlete_name"] for row in data["elite_competitors"]]
        self.assertEqual(names, ["Elite Medal", "Elite Match"])

        percentiles = [row["percentile"] for row in data["elite_competitors"]]
        self.assertEqual(percentiles, [0.09, 0.01])

        current_teams_by_name = {
            row["athlete_name"]: row["current_team"]
            for row in data["elite_competitors"]
        }
        # falls back to latest match team and then maps with TeamNameMapping rules
        self.assertEqual(current_teams_by_name["Elite Medal"], "Alliance Jiu Jitsu")
        # registration team overrides latest match team and is also mapped
        self.assertEqual(current_teams_by_name["Elite Match"], "Alliance Jiu Jitsu")

    def test_team_not_found(self):
        response = self.client.get("/api/teams/does-not-exist")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
