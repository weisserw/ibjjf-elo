import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, JUVENILE_AGES, LIGHT, MALE, MASTER_1, MASTER_2
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


class AwardsTeamMappingsApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        db.session.add_all(
            [
                Event(
                    name="Mapping Event",
                    normalized_name="mapping event",
                    slug="mapping-event",
                    ibjjf_id="mapping-event",
                    medals_only=False,
                ),
                Division(gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=LIGHT),
            ]
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.client = self.app_module.app.test_client()
        context = self.app_module.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.addCleanup(db.session.rollback)
        self.event = Event.query.one()
        self.division = Division.query.one()
        self.teams = {}
        self.athletes = {}

    def _match(
        self,
        team_name,
        athlete_name,
        won=True,
        opponent_rating=1500,
        opponent_name="Opponent",
        opponent_team="Opponents",
    ):
        match = Match(
            event_id=self.event.id,
            division_id=self.division.id,
            happened_at=datetime(2026, 1, 1),
            rated=True,
        )
        db.session.add(match)
        db.session.flush()
        for index, (name, team, winner, rating) in enumerate(
            [
                (athlete_name, team_name, won, 1500),
                (opponent_name, opponent_team, not won, opponent_rating),
            ]
        ):
            if team not in self.teams:
                self.teams[team] = Team(name=team, normalized_name=normalize(team))
                db.session.add(self.teams[team])
            if name not in self.athletes:
                self.athletes[name] = Athlete(
                    name=name,
                    normalized_name=normalize(name),
                    slug=normalize(name).replace(" ", "-"),
                    country="us" if index == 0 else "br",
                )
                db.session.add(self.athletes[name])
            db.session.flush()
            db.session.add(
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=self.athletes[name].id,
                    team_id=self.teams[team].id,
                    seed=index + 1,
                    red=index == 0,
                    winner=winner,
                    start_rating=rating,
                    end_rating=rating,
                    start_match_count=5,
                    end_match_count=6,
                )
            )
        db.session.flush()

    def _mapping(self, pattern, name):
        row = TeamNameMapping(name_match=pattern, mapped_name=name)
        db.session.add(row)
        db.session.flush()
        return row

    def _awards(self, **kwargs):
        response = self.client.get(
            "/api/awards/teams",
            query_string={
                "event_name": f'"{self.event.name}"',
                **kwargs,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _rename_event(self, name):
        self.event.name = name
        self.event.normalized_name = normalize(name)
        db.session.flush()

    def test_aliases_qualify_together_and_recompute_weighted_statistics(self):
        for index in range(5):
            self._match(
                "Academy East" if index < 2 else "Academy West",
                f"Athlete {index}",
                won=index < 2,
                opponent_rating=1000 if index == 0 else 2000,
                opponent_name=f"Opponent {index}",
            )
        self.assertEqual(
            [t["team_name"] for t in self._awards()["teams"]], ["Opponents"]
        )
        # Exact and more-specific glob rules must beat the broad glob. The
        # canonical name has no Team row and includes SQL-sensitive characters.
        canonical = "Academy's 'United' :team"
        self._mapping("Academy*", "Wrong Team")
        self._mapping("Academy East", canonical)
        self._mapping("Academy [W]est", canonical)
        teams = self._awards()["teams"]
        self.assertEqual([t["team_name"] for t in teams], ["Opponents", canonical])
        merged = teams[1]
        self.assertEqual(merged["wins"], 2)
        self.assertEqual(merged["win_ratio"], 40.0)
        self.assertEqual(merged["avg_defeated_rating"], 1500.0)
        self.assertEqual(merged["adjusted_ratio"], 600.0)

    def test_distinct_athletes_are_not_added_across_aliases(self):
        for index in range(6):
            self._match(
                "Academy East" if index < 3 else "Academy West",
                f"Athlete {index % 4}",
                opponent_name=f"Opponent {index}",
            )
        self._mapping("Academy*", "Academy")
        self.assertEqual(
            [t["team_name"] for t in self._awards()["teams"]], ["Opponents"]
        )

    def test_merging_precedes_top_three_limit(self):
        for group in range(4):
            for index in range(5):
                self._match(
                    f"Academy {group}", f"Athlete {group} {index}", opponent_rating=1000
                )
        for index in range(5):
            self._match("Other", f"Other Athlete {index}", opponent_rating=2000)
        self.assertEqual(len(self._awards()["teams"]), 3)
        self._mapping("Academy*", "Academy")
        teams = self._awards()["teams"]
        self.assertEqual([t["team_name"] for t in teams], ["Other", "Academy"])
        self.assertEqual(teams[1]["wins"], 20)

    def test_country_awards_ignore_team_mappings(self):
        for index in range(5):
            self._match(
                "Academy", f"Athlete {index}", opponent_name=f"Opponent {index}"
            )
        before = self._awards(group_by="country")
        self._mapping("*", "Everyone")
        self.assertEqual(self._awards(group_by="country"), before)
        # Preserve the current scoring policy for matches within a merged team.
        merged = self._awards()["teams"][0]
        self.assertEqual(merged["team_name"], "Everyone")
        self.assertEqual(merged["wins"], 5)
        self.assertEqual(merged["win_ratio"], 50.0)

    def test_mapping_edits_apply_on_next_request(self):
        for index in range(5):
            self._match("Academy", f"Athlete {index}")
        mapping = self._mapping("Academy", "First Name")
        self.assertEqual(self._awards()["teams"][0]["team_name"], "First Name")
        mapping.mapped_name = "New Name"
        db.session.flush()
        self.assertEqual(self._awards()["teams"][0]["team_name"], "New Name")

    def test_empty_event(self):
        self.assertEqual(
            self._awards(), {"teams": [], "min_competing_athletes_required": 5}
        )

    def test_same_country_matches_count_for_eligibility_only(self):
        for index in range(5):
            self._match("Academy", f"Athlete {index}")
        self.athletes["Opponent"].country = " US "
        db.session.flush()
        self.assertEqual(self._awards(group_by="country")["teams"], [])
        self.assertEqual(self._awards()["teams"][0]["wins"], 5)
        # Domestic-only athletes supply the minimum size, while only these
        # two international matches contribute to the score.
        for won in (True, False):
            self._match(
                "Academy",
                "Athlete 0",
                won=won,
                opponent_rating=2000,
                opponent_name="Foreign opponent",
            )
        for event in ("Regional Open", "World IBJJF Championship"):
            self._rename_event(event)
            for country in (" US ", "pr", "gu", "vi"):
                with self.subTest(event=event, country=country):
                    self.athletes["Opponent"].country = country
                    db.session.flush()
                    countries = self._awards(group_by="country")["teams"]
                    self.assertEqual(len(countries), 1)
                    self.assertEqual(countries[0]["team_name"], "us")
                    self.assertEqual(countries[0]["wins"], 1)
                    self.assertEqual(countries[0]["win_ratio"], 50.0)
                    self.assertEqual(countries[0]["avg_defeated_rating"], 2000.0)
                    self.assertEqual(countries[0]["adjusted_ratio"], 1000.0)

    def test_country_awards_still_count_unknown_opponents(self):
        for index in range(5):
            self._match("Academy", f"Athlete {index}", won=index < 3)
        for country in (None, "", "   "):
            with self.subTest(country=country):
                self.athletes["Opponent"].country = country
                db.session.flush()
                countries = self._awards(group_by="country")["teams"]
                self.assertEqual(len(countries), 1)
                self.assertEqual(countries[0]["wins"], 3)
                self.assertEqual(countries[0]["win_ratio"], 60.0)
                self.assertEqual(countries[0]["avg_defeated_rating"], 1500.0)

    def test_major_country_scores_exclude_masters_matches(self):
        self._rename_event("World IBJJF Championship")
        for index in range(5):
            self._match(
                "Academy",
                f"Athlete {index}",
                won=index < 3,
                opponent_name=f"Opponent {index}",
            )
        before = self._awards(group_by="country")
        team_before = self._awards()
        for age in (MASTER_1, MASTER_2):
            self.division = Division(
                gi=True,
                gender=MALE,
                age=age,
                belt=BLACK,
                weight=LIGHT,
            )
            db.session.add(self.division)
            db.session.flush()
            for won in (True, False, True):
                self._match(
                    "Academy",
                    "Athlete 0",
                    won=won,
                    opponent_rating=2400,
                    opponent_name="Opponent 0",
                )
        for name in (
            "CAMPEONATO BRASILEIRO Championship",
            "2026 Pan IBJJF Championship",
            "European iBjJf Championship",
            "world ibjjf Championship",
        ):
            with self.subTest(event=name):
                self._rename_event(name)
                self.assertEqual(self._awards(group_by="country"), before)
        self.assertNotEqual(self._awards(), team_before)
        for name in ("Mapping Event", "World Master Championship", "Pan IBJJFish Open"):
            with self.subTest(event=name):
                self._rename_event(name)
                self.assertNotEqual(self._awards(group_by="country"), before)

    def test_major_country_eligibility_excludes_masters_participation(self):
        self._rename_event("World IBJJF Championship")
        adult_division = self.division
        for index in range(4):
            self._match(
                "Academy", f"Athlete {index}", opponent_name=f"Opponent {index}"
            )
        self.division = Division(
            gi=True,
            gender=MALE,
            age=MASTER_1,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add(self.division)
        db.session.flush()
        self._match("Academy", "Athlete 4", opponent_name="Opponent 4")
        self.assertEqual(self._awards(group_by="country")["teams"], [])
        self.assertEqual(len(self._awards()["teams"]), 2)
        self._rename_event("Regional Open")
        self.assertEqual(len(self._awards(group_by="country")["teams"]), 2)
        self._rename_event("World IBJJF Championship")
        self.division = adult_division
        self._match("Academy", "Athlete 4", opponent_name="Opponent 4")
        self.assertEqual(len(self._awards(group_by="country")["teams"]), 2)

    def test_country_minimum_size_uses_major_age_divisions(self):
        self._rename_event("World IBJJF Championship")
        for index in range(5):
            self._match(
                "Academy", f"Adult {index}", opponent_name=f"Adult opponent {index}"
            )
        self.division = Division(
            gi=True,
            gender=MALE,
            age=MASTER_1,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add(self.division)
        db.session.flush()
        for index in range(500):
            self._match(
                "Academy", f"Master {index}", opponent_name=f"Master opponent {index}"
            )
        country_awards = self._awards(group_by="country")
        self.assertEqual(country_awards["min_competing_athletes_required"], 5)
        self.assertEqual(len(country_awards["teams"]), 2)
        self.assertEqual(self._awards()["min_competing_athletes_required"], 10)
        for age in JUVENILE_AGES:
            with self.subTest(age=age):
                self.division.age = age
                db.session.flush()
                self.assertEqual(
                    self._awards(group_by="country")["min_competing_athletes_required"],
                    8,
                )
        self.division.age = MASTER_1
        db.session.flush()
        self._rename_event("Regional Open")
        self.assertEqual(
            self._awards(group_by="country")["min_competing_athletes_required"], 8
        )
        self.assertEqual(self._awards()["min_competing_athletes_required"], 10)

    def test_juvenile_divisions_count_for_major_country_scoring_and_eligibility(self):
        self._rename_event("World IBJJF Championship")
        for index in range(4):
            self._match("Academy", f"Adult {index}")
        self.division = Division(
            gi=True,
            gender=MALE,
            age=JUVENILE_AGES[0],
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add(self.division)
        db.session.flush()
        self._match("Academy", "Juvenile athlete", opponent_rating=2000)
        self._match("Academy", "Juvenile athlete", won=False)
        for age in JUVENILE_AGES:
            with self.subTest(age=age):
                self.division.age = age
                db.session.flush()
                countries = self._awards(group_by="country")["teams"]
                self.assertEqual(len(countries), 1)
                self.assertEqual(countries[0]["team_name"], "us")
                self.assertEqual(countries[0]["wins"], 5)
                self.assertEqual(countries[0]["win_ratio"], 83.3)
                self.assertEqual(countries[0]["avg_defeated_rating"], 1600.0)


if __name__ == "__main__":
    unittest.main()
