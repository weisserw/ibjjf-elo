import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team
from routes.brackets import attach_live_match_scores
from test_db import TestDbMixin


class BracketsLiveMatchScoresTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        cls.team = Team(name="Test Team", normalized_name="test team")
        cls.event = Event(
            name="Live Test Event",
            normalized_name="live test event",
            slug="live-test-event",
            ibjjf_id="LIVE1",
            medals_only=False,
        )
        cls.division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add_all([cls.team, cls.event, cls.division])
        db.session.flush()
        cls.division_id = cls.division.id

        cls.red_athlete = Athlete(
            name="Stored Red",
            normalized_name="stored red",
            slug="stored-red",
            ibjjf_id="athlete-red",
        )
        cls.blue_athlete = Athlete(
            name="Stored Blue",
            normalized_name="stored blue",
            slug="stored-blue",
            ibjjf_id="athlete-blue",
        )
        db.session.add_all([cls.red_athlete, cls.blue_athlete])
        db.session.flush()

        cls.match = Match(
            event_id=cls.event.id,
            division_id=cls.division.id,
            happened_at=datetime(2026, 1, 1, 10, 0, 0),
            rated=True,
            match_number=7,
            video_link="https://www.youtube.com/watch?v=stored",
            video_start_offset_seconds=123,
            final_match_time_seconds=241,
            final_top_points=12,
            final_top_advantages=1,
            final_top_penalties=0,
            final_bottom_points=2,
            final_bottom_advantages=0,
            final_bottom_penalties=1,
        )
        db.session.add(cls.match)
        db.session.flush()

        db.session.add_all(
            [
                MatchParticipant(
                    match_id=cls.match.id,
                    athlete_id=cls.red_athlete.id,
                    team_id=cls.team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1500,
                    end_rating=1510,
                    start_match_count=10,
                    end_match_count=11,
                    scoreboard_position="top",
                ),
                MatchParticipant(
                    match_id=cls.match.id,
                    athlete_id=cls.blue_athlete.id,
                    team_id=cls.team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450,
                    end_rating=1440,
                    start_match_count=9,
                    end_match_count=10,
                    scoreboard_position="bottom",
                ),
            ]
        )
        db.session.commit()

    def test_attach_live_match_scores_maps_scoreboard_positions_by_athlete_id(self):
        parsed_matches = [
            {
                "match_num": 7,
                "red_id": "athlete-blue",
                "blue_id": "athlete-red",
            }
        ]

        with self.app_module.app.app_context():
            division = db.session.get(Division, self.division_id)
            attach_live_match_scores("LIVE1", division, parsed_matches)

        match = parsed_matches[0]
        self.assertEqual(match["video_link"], "https://www.youtube.com/watch?v=stored")
        self.assertEqual(match["video_start_offset_seconds"], 123)
        self.assertEqual(match["finalMatchTimeSeconds"], 241)
        self.assertEqual(match["finalTopPoints"], 12)
        self.assertEqual(match["finalTopAdvantages"], 1)
        self.assertEqual(match["finalTopPenalties"], 0)
        self.assertEqual(match["finalBottomPoints"], 2)
        self.assertEqual(match["finalBottomAdvantages"], 0)
        self.assertEqual(match["finalBottomPenalties"], 1)
        self.assertEqual(match["redScoreboardPosition"], "bottom")
        self.assertEqual(match["blueScoreboardPosition"], "top")

    def test_attach_live_match_scores_leaves_unmatched_live_matches_unchanged(self):
        parsed_matches = [
            {
                "match_num": 99,
                "red_id": "athlete-blue",
                "blue_id": "athlete-red",
            }
        ]

        with self.app_module.app.app_context():
            division = db.session.get(Division, self.division_id)
            attach_live_match_scores("LIVE1", division, parsed_matches)

        self.assertNotIn("finalTopPoints", parsed_matches[0])
        self.assertNotIn("redScoreboardPosition", parsed_matches[0])


if __name__ == "__main__":
    unittest.main()
