import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
)

from extensions import db
from models import Athlete, Division, Event, Match, Medal, Team
from test_db import TestDbMixin

import merge_events as merge_module


class EventMergeTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        with self.app_module.app.app_context():
            db.session.query(Medal).delete()
            db.session.query(Match).delete()
            db.session.query(Athlete).delete()
            db.session.query(Team).delete()
            db.session.query(Division).delete()
            db.session.query(Event).delete()
            db.session.commit()

    def event(self, name, **values):
        event = Event(
            id=uuid.uuid4(),
            name=name,
            normalized_name=name.lower(),
            slug=name.lower().replace(" ", "-"),
            **values,
        )
        db.session.add(event)
        db.session.flush()
        return event

    def test_merge_moves_matches_and_medals_and_deletes_duplicate(self):
        with self.app_module.app.app_context():
            keep = self.event("Archive Event", ibjjf_id="2662", medals_only=False)
            merge = self.event("Historical Event", medals_only=True)
            division = Division(
                id=uuid.uuid4(),
                gi=True,
                gender="Male",
                age="Adult",
                belt="Black",
                weight="Light",
            )
            athlete = Athlete(
                id=uuid.uuid4(),
                name="Athlete",
                normalized_name="athlete",
                slug="athlete-one",
            )
            team = Team(id=uuid.uuid4(), name="Team", normalized_name="team")
            db.session.add_all([division, athlete, team])
            db.session.flush()
            medal = Medal(
                happened_at=datetime(2024, 1, 1),
                event_id=merge.id,
                division_id=division.id,
                athlete_id=athlete.id,
                team_id=team.id,
                place=1,
                default_gold=False,
            )
            match = Match(
                happened_at=datetime(2024, 1, 1),
                event_id=merge.id,
                division_id=division.id,
                rated=True,
            )
            db.session.add_all([medal, match])
            db.session.flush()

            merge_module.merge_events(keep, merge)
            db.session.flush()

            self.assertEqual(medal.event_id, keep.id)
            db.session.expire(match)
            self.assertEqual(match.event_id, keep.id)
            self.assertIsNone(db.session.get(Event, merge.id))
            self.assertFalse(keep.medals_only)

    def test_merge_keeps_better_place_for_overlapping_medal(self):
        with self.app_module.app.app_context():
            keep = self.event("Keep", medals_only=False)
            merge = self.event("Merge", medals_only=True)
            division = Division(
                id=uuid.uuid4(),
                gi=True,
                gender="Female",
                age="Adult",
                belt="Black",
                weight="Open Class",
            )
            athlete = Athlete(
                id=uuid.uuid4(),
                name="Athlete",
                normalized_name="athlete",
                slug="athlete-two",
            )
            team = Team(id=uuid.uuid4(), name="Team", normalized_name="team")
            db.session.add_all([division, athlete, team])
            db.session.flush()
            keep_medal = Medal(
                happened_at=datetime(2024, 1, 2),
                event_id=keep.id,
                division_id=division.id,
                athlete_id=athlete.id,
                team_id=team.id,
                place=2,
                default_gold=False,
            )
            merge_medal = Medal(
                happened_at=datetime(2024, 1, 1),
                event_id=merge.id,
                division_id=division.id,
                athlete_id=athlete.id,
                team_id=team.id,
                place=1,
                default_gold=True,
            )
            db.session.add_all([keep_medal, merge_medal])
            db.session.flush()

            merge_module.merge_events(keep, merge)
            db.session.flush()

            medals = db.session.query(Medal).filter_by(event_id=keep.id).all()
            self.assertEqual(len(medals), 1)
            self.assertEqual(medals[0].place, 1)
            self.assertTrue(medals[0].default_gold)

    def test_merge_rejects_different_ibjjf_ids(self):
        with self.app_module.app.app_context():
            keep = self.event("Keep", ibjjf_id="1")
            merge = self.event("Merge", ibjjf_id="2")
            with self.assertRaisesRegex(ValueError, "different non-empty IBJJF IDs"):
                merge_module.merge_events(keep, merge)

    def test_merge_can_copy_ibjjf_id_from_duplicate(self):
        with self.app_module.app.app_context():
            keep = self.event("Keep", medals_only=True)
            merge = self.event("Merge", ibjjf_id="2662", medals_only=False)

            merge_module.merge_events(keep, merge)
            db.session.flush()

            self.assertEqual(keep.ibjjf_id, "2662")
            self.assertFalse(keep.medals_only)
            self.assertIsNone(db.session.get(Event, merge.id))


if __name__ == "__main__":
    unittest.main()
