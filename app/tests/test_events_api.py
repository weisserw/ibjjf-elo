import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import Division, Event, Match
from normalize import normalize
from test_db import TestDbMixin


class EventsApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        division_gi = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        division_nogi = Division(
            gi=False,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        db.session.add_all([division_gi, division_nogi])
        db.session.flush()

        event1 = Event(
            name="Summer Open 2024",
            normalized_name=normalize("Summer Open 2024"),
            slug="summer-open-2024",
            ibjjf_id="E1",
        )
        event2 = Event(
            name="Winter Classic (Results)",
            normalized_name=normalize("Winter Classic (Results)"),
            slug="winter-classic-results",
            ibjjf_id="E2",
        )
        event3 = Event(
            name="Kids Open (idade 04 a 15 anos)",
            normalized_name=normalize("Kids Open (idade 04 a 15 anos)"),
            slug="kids-open-idade",
            ibjjf_id="E3",
        )
        db.session.add_all([event1, event2, event3])
        db.session.flush()

        match1 = Match(
            event_id=event1.id,
            division_id=division_gi.id,
            happened_at=datetime(2024, 1, 1, 10, 0, 0),
            rated=True,
        )
        match2 = Match(
            event_id=event2.id,
            division_id=division_nogi.id,
            happened_at=datetime(2024, 1, 2, 10, 0, 0),
            rated=True,
        )
        match3 = Match(
            event_id=event3.id,
            division_id=division_gi.id,
            happened_at=datetime(2024, 1, 3, 10, 0, 0),
            rated=True,
        )
        db.session.add_all([match1, match2, match3])
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_events_search(self):
        response = self.client.get("/api/events", query_string={"search": "summer"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data, ["Summer Open 2024"])

    def test_events_gi_filter(self):
        response = self.client.get("/api/events", query_string={"gi": "true"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data, ["Kids Open (idade 04 a 15 anos)", "Summer Open 2024"])

        response = self.client.get("/api/events", query_string={"gi": "false"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data, ["Winter Classic (Results)"])

    def test_events_historical_filter(self):
        response = self.client.get("/api/events", query_string={"historical": "false"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(
            data,
            ["Kids Open (idade 04 a 15 anos)", "Summer Open 2024"],
        )


if __name__ == "__main__":
    unittest.main()
