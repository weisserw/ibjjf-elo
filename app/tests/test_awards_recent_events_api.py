import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import Athlete, Division, Event, Match, MatchParticipant, Team
from test_db import TestDbMixin


class AwardsRecentEventsApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        team = Team(name="Team", normalized_name="team")
        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        athlete1 = Athlete(name="A1", normalized_name="a1", slug="a1")
        athlete2 = Athlete(name="A2", normalized_name="a2", slug="a2")
        db.session.add_all([team, division, athlete1, athlete2])
        db.session.flush()

        older_event = Event(
            name="Older Event",
            normalized_name="older event",
            slug="older-event",
            ibjjf_id="RE1",
            medals_only=False,
        )
        middle_event = Event(
            name="Middle Event",
            normalized_name="middle event",
            slug="middle-event",
            ibjjf_id="RE2",
            medals_only=False,
        )
        newest_event = Event(
            name="Newest Event",
            normalized_name="newest event",
            slug="newest-event",
            ibjjf_id="RE3",
            medals_only=False,
        )
        unrated_newer_event = Event(
            name="Unrated Newer Event",
            normalized_name="unrated newer event",
            slug="unrated-newer-event",
            ibjjf_id="RE4",
            medals_only=False,
        )
        db.session.add_all(
            [older_event, middle_event, newest_event, unrated_newer_event]
        )
        db.session.flush()

        matches = [
            Match(
                event_id=older_event.id,
                division_id=division.id,
                happened_at=datetime(2024, 1, 1, 10, 0, 0),
                rated=True,
            ),
            Match(
                event_id=middle_event.id,
                division_id=division.id,
                happened_at=datetime(2024, 2, 1, 10, 0, 0),
                rated=True,
            ),
            Match(
                event_id=newest_event.id,
                division_id=division.id,
                happened_at=datetime(2024, 3, 1, 10, 0, 0),
                rated=True,
            ),
            Match(
                event_id=unrated_newer_event.id,
                division_id=division.id,
                happened_at=datetime(2024, 4, 1, 10, 0, 0),
                rated=False,
            ),
        ]
        db.session.add_all(matches)
        db.session.flush()

        participants = []
        for match in matches:
            participants.extend(
                [
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athlete1.id,
                        team_id=team.id,
                        seed=1,
                        red=True,
                        winner=True,
                        start_rating=1500.0,
                        end_rating=1510.0,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athlete2.id,
                        team_id=team.id,
                        seed=2,
                        red=False,
                        winner=False,
                        start_rating=1400.0,
                        end_rating=1390.0,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                ]
            )
        db.session.add_all(participants)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_recent_events_order_and_limit(self):
        response = self.client.get(
            "/api/awards/events/recent", query_string={"limit": 2}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data, ["Newest Event", "Middle Event"])

    def test_recent_events_invalid_limit(self):
        response = self.client.get(
            "/api/awards/events/recent", query_string={"limit": "x"}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
