import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLUE, LIGHT, MALE, TEEN_1
from extensions import db
from models import (
    Athlete,
    Division,
    Event,
    Match,
    MatchParticipant,
    Team,
    TeamNameMapping,
)
from normalize import normalize
from test_db import TestDbMixin


class NavbarSearchApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        canonical_team = Team(
            name="Alliance Jiu Jitsu",
            normalized_name=normalize("Alliance Jiu Jitsu"),
        )
        alias_team = Team(
            name="Alliance Jiu Jitsu HQ",
            normalized_name=normalize("Alliance Jiu Jitsu HQ"),
        )
        db.session.add_all([canonical_team, alias_team])
        db.session.flush()

        db.session.add(
            TeamNameMapping(
                name_match="Alliance Jiu Jitsu*",
                mapped_name=canonical_team.name,
            )
        )

        event = Event(
            name="Navbar Search Open",
            normalized_name=normalize("Navbar Search Open"),
            slug="navbar-search-open",
            ibjjf_id="NS1",
        )
        adult_division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLUE,
            weight=LIGHT,
        )
        teen_division = Division(
            gi=True,
            gender=MALE,
            age=TEEN_1,
            belt=BLUE,
            weight=LIGHT,
        )
        db.session.add_all([event, adult_division, teen_division])
        db.session.flush()

        adult_athlete = Athlete(
            name="Alliance Athlete",
            normalized_name=normalize("Alliance Athlete"),
            slug="alliance-athlete",
        )
        second_adult_athlete = Athlete(
            name="Alliance Grappler",
            normalized_name=normalize("Alliance Grappler"),
            slug="alliance-grappler",
        )
        teen_athlete = Athlete(
            name="Alliance Teen",
            normalized_name=normalize("Alliance Teen"),
            slug="alliance-teen",
        )
        db.session.add_all([adult_athlete, second_adult_athlete, teen_athlete])
        db.session.flush()

        adult_match = Match(
            event_id=event.id,
            division_id=adult_division.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        teen_match = Match(
            event_id=event.id,
            division_id=teen_division.id,
            happened_at=datetime(2024, 2, 1, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([adult_match, teen_match])
        db.session.flush()

        db.session.add_all(
            [
                MatchParticipant(
                    match_id=adult_match.id,
                    athlete_id=adult_athlete.id,
                    team_id=canonical_team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1200,
                    end_rating=1210,
                    start_match_count=1,
                    end_match_count=2,
                ),
                MatchParticipant(
                    match_id=teen_match.id,
                    athlete_id=teen_athlete.id,
                    team_id=alias_team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1100,
                    end_rating=1110,
                    start_match_count=1,
                    end_match_count=2,
                ),
                MatchParticipant(
                    match_id=adult_match.id,
                    athlete_id=second_adult_athlete.id,
                    team_id=canonical_team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1190,
                    end_rating=1180,
                    start_match_count=1,
                    end_match_count=2,
                ),
            ]
        )

        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_navbar_search_returns_athletes_and_canonical_teams(self):
        response = self.client.get(
            "/api/navbar-search", query_string={"search": "alliance"}
        )
        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        athlete_entries = [row for row in data if row["type"] == "athlete"]
        team_entries = [row for row in data if row["type"] == "team"]

        self.assertEqual(
            [row["name"] for row in athlete_entries],
            ["Alliance Athlete", "Alliance Grappler"],
        )
        self.assertEqual(len(team_entries), 1)
        self.assertEqual(team_entries[0]["name"], "Alliance Jiu Jitsu")
        self.assertEqual(team_entries[0]["slug"], "alliance-jiu-jitsu")
        self.assertEqual(
            [row["type"] for row in data],
            ["athlete", "athlete", "team"],
        )

    def test_navbar_search_empty_query(self):
        response = self.client.get("/api/navbar-search", query_string={"search": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])


if __name__ == "__main__":
    unittest.main()
