import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from extensions import db
from models import Athlete, Division, Event, Match, Medal, Team
from test_db import TestDbMixin

import load_csv


class LoadCsvTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.ctx = self.app_module.app.app_context()
        self.ctx.push()
        db.session.query(Medal).delete()
        db.session.query(Match).delete()
        db.session.query(Athlete).delete()
        db.session.query(Team).delete()
        db.session.query(Division).delete()
        db.session.query(Event).delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def _create_medal_context(self, later_happened_at, earlier_happened_at):
        event = Event(
            ibjjf_id="event-1",
            name="Event",
            normalized_name="event",
            slug="event",
        )
        division = Division(
            gi=True,
            gender="Male",
            age="Adult",
            belt="BLACK",
            weight="Light",
        )
        athlete = Athlete(
            ibjjf_id="athlete-1",
            name="Athlete",
            normalized_name="athlete",
            slug="athlete",
        )
        team = Team(name="Team", normalized_name="team")
        db.session.add_all([event, division, athlete, team])
        db.session.flush()

        later_match = Match(
            happened_at=later_happened_at,
            event_id=event.id,
            division_id=division.id,
            rated=True,
        )
        earlier_match = Match(
            happened_at=earlier_happened_at,
            event_id=event.id,
            division_id=division.id,
            rated=True,
        )
        db.session.add_all([later_match, earlier_match])
        db.session.flush()
        return event, division, athlete, team, later_match, earlier_match

    def test_create_or_update_medal_does_not_insert_duplicate_for_earlier_row(self):
        later_happened_at = datetime(2026, 5, 27, 14, 35)
        earlier_happened_at = datetime(2026, 5, 27, 14, 14)
        event, division, athlete, team, later_match, earlier_match = (
            self._create_medal_context(later_happened_at, earlier_happened_at)
        )

        load_csv.create_or_update_medal(
            db.session, 1, event, division, later_match, athlete, team
        )
        load_csv.create_or_update_medal(
            db.session, 1, event, division, earlier_match, athlete, team
        )

        medals = db.session.query(Medal).all()
        self.assertEqual(len(medals), 1)
        self.assertEqual(medals[0].happened_at, later_happened_at)

    def test_create_or_update_medal_does_not_insert_duplicate_for_same_time_row(self):
        happened_at = datetime(2026, 5, 27, 14, 14)
        event, division, athlete, team, match, duplicate_match = (
            self._create_medal_context(happened_at, happened_at)
        )

        load_csv.create_or_update_medal(
            db.session, 1, event, division, match, athlete, team
        )
        load_csv.create_or_update_medal(
            db.session, 1, event, division, duplicate_match, athlete, team
        )

        medals = db.session.query(Medal).all()
        self.assertEqual(len(medals), 1)
        self.assertEqual(medals[0].happened_at, happened_at)

    def test_create_or_update_medal_updates_timestamp_for_later_row(self):
        later_happened_at = datetime(2026, 5, 27, 14, 35)
        earlier_happened_at = datetime(2026, 5, 27, 14, 14)
        event, division, athlete, team, later_match, earlier_match = (
            self._create_medal_context(later_happened_at, earlier_happened_at)
        )

        load_csv.create_or_update_medal(
            db.session, 1, event, division, earlier_match, athlete, team
        )
        load_csv.create_or_update_medal(
            db.session, 1, event, division, later_match, athlete, team
        )

        medals = db.session.query(Medal).all()
        self.assertEqual(len(medals), 1)
        self.assertEqual(medals[0].happened_at, later_happened_at)


if __name__ == "__main__":
    unittest.main()
