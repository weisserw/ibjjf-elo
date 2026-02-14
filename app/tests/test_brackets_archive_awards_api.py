import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, HEAVY, LIGHT, MALE, OPEN_CLASS
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team
from test_db import TestDbMixin


class BracketsArchiveAwardsApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        event = Event(
            name="Awards Event",
            normalized_name="awards event",
            slug="awards-event",
            ibjjf_id="AE1",
            medals_only=False,
        )
        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        alpha = Team(name="Alpha", normalized_name="alpha")
        beta = Team(name="Beta", normalized_name="beta")
        gamma = Team(name="Gamma", normalized_name="gamma")
        db.session.add_all([event, division, alpha, beta, gamma])
        db.session.flush()

        athlete_a = Athlete(name="Athlete A", normalized_name="athlete a", slug="a")
        athlete_b = Athlete(name="Athlete B", normalized_name="athlete b", slug="b")
        athlete_c = Athlete(name="Athlete C", normalized_name="athlete c", slug="c")
        athlete_d = Athlete(name="Athlete D", normalized_name="athlete d", slug="d")
        athlete_e = Athlete(name="Athlete E", normalized_name="athlete e", slug="e")
        athlete_f = Athlete(name="Athlete F", normalized_name="athlete f", slug="f")
        athlete_g = Athlete(name="Athlete G", normalized_name="athlete g", slug="g")
        athlete_h = Athlete(name="Athlete H", normalized_name="athlete h", slug="h")
        db.session.add_all(
            [
                athlete_a,
                athlete_b,
                athlete_c,
                athlete_d,
                athlete_e,
                athlete_f,
                athlete_g,
                athlete_h,
            ]
        )
        db.session.flush()

        m1 = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        m2 = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 11, 0, 0),
            rated=True,
        )
        m3 = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 12, 0, 0),
            rated=True,
        )
        m4 = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 13, 0, 0),
            rated=True,
        )
        m5 = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=datetime(2024, 1, 1, 14, 0, 0),
            rated=False,
        )
        rated_matches = [m1, m2, m3, m4]
        base_time = datetime(2024, 1, 1, 10, 0, 0)
        for idx in range(5, 17):
            rated_matches.append(
                Match(
                    event_id=event.id,
                    division_id=division.id,
                    happened_at=base_time + timedelta(hours=idx),
                    rated=True,
                )
            )
        db.session.add_all(rated_matches + [m5])
        db.session.flush()

        participants = [
            # m1: Alpha beats Beta
            MatchParticipant(
                match_id=m1.id,
                athlete_id=athlete_a.id,
                team_id=alpha.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1500.0,
                end_rating=1510.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=m1.id,
                athlete_id=athlete_b.id,
                team_id=beta.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1400.0,
                end_rating=1390.0,
                start_match_count=5,
                end_match_count=6,
            ),
            # m2: Beta beats Gamma
            MatchParticipant(
                match_id=m2.id,
                athlete_id=athlete_c.id,
                team_id=beta.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1450.0,
                end_rating=1460.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=m2.id,
                athlete_id=athlete_d.id,
                team_id=gamma.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1300.0,
                end_rating=1290.0,
                start_match_count=5,
                end_match_count=6,
            ),
            # m3: Gamma beats Alpha
            MatchParticipant(
                match_id=m3.id,
                athlete_id=athlete_e.id,
                team_id=alpha.id,
                seed=1,
                red=True,
                winner=False,
                start_rating=1520.0,
                end_rating=1510.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=m3.id,
                athlete_id=athlete_f.id,
                team_id=gamma.id,
                seed=2,
                red=False,
                winner=True,
                start_rating=1320.0,
                end_rating=1330.0,
                start_match_count=5,
                end_match_count=6,
            ),
            # m4: invalid (both winners), should be ignored
            MatchParticipant(
                match_id=m4.id,
                athlete_id=athlete_g.id,
                team_id=alpha.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=1400.0,
                end_rating=1410.0,
                start_match_count=5,
                end_match_count=6,
            ),
            MatchParticipant(
                match_id=m4.id,
                athlete_id=athlete_h.id,
                team_id=beta.id,
                seed=2,
                red=False,
                winner=True,
                start_rating=1350.0,
                end_rating=1360.0,
                start_match_count=5,
                end_match_count=6,
            ),
            # m5: unrated valid result, should be ignored
            MatchParticipant(
                match_id=m5.id,
                athlete_id=athlete_g.id,
                team_id=alpha.id,
                seed=1,
                red=True,
                winner=True,
                start_rating=3500.0,
                end_rating=3510.0,
                start_match_count=6,
                end_match_count=7,
            ),
            MatchParticipant(
                match_id=m5.id,
                athlete_id=athlete_h.id,
                team_id=beta.id,
                seed=2,
                red=False,
                winner=False,
                start_rating=1000.0,
                end_rating=990.0,
                start_match_count=6,
                end_match_count=7,
            ),
        ]

        # Add 12 more rated matches to reach 5 wins for each team.
        # Pattern per cycle: Alpha beats Beta, Beta beats Gamma, Gamma beats Alpha.
        # This preserves the same ordering and score math as the original fixture.
        cycle_specs = [
            (alpha, beta, athlete_a, athlete_b, 1500.0, 1400.0),
            (beta, gamma, athlete_c, athlete_d, 1450.0, 1300.0),
            (gamma, alpha, athlete_f, athlete_e, 1320.0, 1520.0),
        ]
        for match, spec in zip(rated_matches[4:], cycle_specs * 4):
            (
                winner_team,
                loser_team,
                winner_athlete,
                loser_athlete,
                winner_rating,
                loser_rating,
            ) = spec
            participants.append(
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=winner_athlete.id,
                    team_id=winner_team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=winner_rating,
                    end_rating=winner_rating + 10.0,
                    start_match_count=5,
                    end_match_count=6,
                )
            )
            participants.append(
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=loser_athlete.id,
                    team_id=loser_team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=loser_rating,
                    end_rating=loser_rating - 10.0,
                    start_match_count=5,
                    end_match_count=6,
                )
            )
        db.session.add_all(participants)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_archive_awards_basic(self):
        response = self.client.get(
            "/api/awards/teams",
            query_string={"event_name": '"Awards Event"'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["min_wins_required"], 5)
        self.assertEqual(len(data["teams"]), 3)

        self.assertEqual(data["teams"][0]["team_name"], "Gamma")
        self.assertEqual(data["teams"][0]["place"], 1)
        self.assertEqual(data["teams"][0]["wins"], 5)
        self.assertAlmostEqual(data["teams"][0]["win_ratio"], 50.0)
        self.assertAlmostEqual(data["teams"][0]["avg_defeated_rating"], 1520.0)
        self.assertAlmostEqual(data["teams"][0]["adjusted_ratio"], 760.0)

        self.assertEqual(data["teams"][1]["team_name"], "Alpha")
        self.assertEqual(data["teams"][1]["place"], 2)
        self.assertEqual(data["teams"][1]["wins"], 5)
        self.assertAlmostEqual(data["teams"][1]["adjusted_ratio"], 700.0)

        self.assertEqual(data["teams"][2]["team_name"], "Beta")
        self.assertEqual(data["teams"][2]["place"], 3)
        self.assertEqual(data["teams"][2]["wins"], 5)
        self.assertAlmostEqual(data["teams"][2]["adjusted_ratio"], 650.0)

    def test_archive_awards_missing_param(self):
        response = self.client.get("/api/awards/teams")
        self.assertEqual(response.status_code, 400)

    def test_archive_awards_open_class_rating_adjustment(self):
        with self.app_module.app.app_context():
            open_event = Event(
                name="Open Adjust Event",
                normalized_name="open adjust event",
                slug="open-adjust-event",
                ibjjf_id="AE2",
                medals_only=False,
            )
            open_division = Division(
                gi=True,
                gender=MALE,
                age=ADULT,
                belt=BLACK,
                weight=OPEN_CLASS,
            )
            alpha = db.session.query(Team).filter_by(normalized_name="alpha").first()
            beta = db.session.query(Team).filter_by(normalized_name="beta").first()
            winner = Athlete(
                name="Open Winner", normalized_name="open winner", slug="open-winner"
            )
            loser = Athlete(
                name="Open Loser", normalized_name="open loser", slug="open-loser"
            )
            db.session.add_all([open_event, open_division, winner, loser])
            db.session.flush()

            open_matches = [
                Match(
                    event_id=open_event.id,
                    division_id=open_division.id,
                    happened_at=datetime(2024, 1, 2, 10, 0, 0) + timedelta(hours=idx),
                    rated=True,
                )
                for idx in range(5)
            ]
            db.session.add_all(open_matches)
            db.session.flush()

            open_participants = []
            for open_match in open_matches:
                open_participants.extend(
                    [
                        MatchParticipant(
                            match_id=open_match.id,
                            athlete_id=winner.id,
                            team_id=alpha.id,
                            seed=1,
                            red=True,
                            winner=True,
                            start_rating=1200.0,
                            end_rating=1210.0,
                            weight_for_open=LIGHT,
                            start_match_count=1,
                            end_match_count=2,
                        ),
                        MatchParticipant(
                            match_id=open_match.id,
                            athlete_id=loser.id,
                            team_id=beta.id,
                            seed=2,
                            red=False,
                            winner=False,
                            start_rating=1000.0,
                            end_rating=990.0,
                            weight_for_open=HEAVY,
                            start_match_count=1,
                            end_match_count=2,
                        ),
                    ]
                )
            db.session.add_all(open_participants)
            db.session.commit()

        response = self.client.get(
            "/api/awards/teams",
            query_string={"event_name": '"Open Adjust Event"'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(data["min_wins_required"], 5)
        self.assertEqual(len(data["teams"]), 1)
        self.assertEqual(data["teams"][0]["team_name"], "Alpha")
        # BLACK_WEIGHT_HANDICAPS[3] = 132.21 (Light vs Heavy)
        self.assertAlmostEqual(data["teams"][0]["avg_defeated_rating"], 1132.21)
        self.assertAlmostEqual(data["teams"][0]["adjusted_ratio"], 1132.21)


if __name__ == "__main__":
    unittest.main()
