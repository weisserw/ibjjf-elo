import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from extensions import db
from constants import JUVENILE_1
from models import Athlete, Division, Event, Match, Medal, Team
from match_division_sizes import refresh_match_division_sizes
from test_db import TestDbMixin

import load_csv


CSV_FIELDNAMES = [
    "Tournament ID",
    "Tournament Name",
    "Partial Tournament",
    "Gi",
    "Date",
    "Age",
    "Belt",
    "Weight",
    "Gender",
    "Red Winner",
    "Blue Winner",
    "Red Medal",
    "Blue Medal",
    "Red ID",
    "Red Name",
    "Red Team",
    "Red Seed",
    "Red Note",
    "Blue ID",
    "Blue Name",
    "Blue Team",
    "Blue Seed",
    "Blue Note",
    "Match Number",
    "Match Location",
    "Fight Number",
]


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

    def _write_csv_rows(self, rows):
        with tempfile.NamedTemporaryFile(
            "w", newline="", suffix=".csv", delete=False
        ) as handle:
            import csv

            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
            return handle.name

    def _base_match_csv_row(self, **overrides):
        row = {
            "Tournament ID": "division-size-event-1",
            "Tournament Name": "Division Size Open",
            "Partial Tournament": "false",
            "Gi": "true",
            "Date": "2026-01-01T10:00:00",
            "Age": "Adult",
            "Belt": "BLACK",
            "Weight": "Light",
            "Gender": "Male",
            "Red Winner": "true",
            "Blue Winner": "false",
            "Red Medal": "",
            "Blue Medal": "",
            "Red ID": "red-1",
            "Red Name": "Red Athlete",
            "Red Team": "Red Team",
            "Red Seed": "1",
            "Red Note": "",
            "Blue ID": "blue-1",
            "Blue Name": "Blue Athlete",
            "Blue Team": "Blue Team",
            "Blue Seed": "2",
            "Blue Note": "",
            "Match Number": "1",
            "Match Location": "Mat 1",
            "Fight Number": "1",
        }
        row.update(overrides)
        return row

    def _process_csv_rows(self, rows):
        path = self._write_csv_rows(rows)
        try:
            load_csv.app = self.app_module.app
            load_csv.process_file(path, no_scores=True)
        finally:
            os.unlink(path)

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

    def test_refresh_match_division_sizes_updates_numbered_rows(self):
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
        other_division = Division(
            gi=True,
            gender="Male",
            age="Adult",
            belt="BLACK",
            weight="Medium",
        )
        db.session.add_all([event, division, other_division])
        db.session.flush()

        match_1 = Match(
            happened_at=datetime(2026, 1, 1, 10, 0),
            event_id=event.id,
            division_id=division.id,
            rated=True,
            match_number=1,
        )
        match_3 = Match(
            happened_at=datetime(2026, 1, 1, 10, 10),
            event_id=event.id,
            division_id=division.id,
            rated=True,
            match_number=3,
        )
        unnumbered_match = Match(
            happened_at=datetime(2026, 1, 1, 10, 20),
            event_id=event.id,
            division_id=division.id,
            rated=True,
            match_number=None,
            division_size=99,
        )
        other_division_match = Match(
            happened_at=datetime(2026, 1, 1, 10, 30),
            event_id=event.id,
            division_id=other_division.id,
            rated=True,
            match_number=2,
        )
        db.session.add_all([match_1, match_3, unnumbered_match, other_division_match])
        db.session.flush()

        refresh_match_division_sizes(db.session, [event.id])
        db.session.expire_all()

        self.assertEqual(db.session.get(Match, match_1.id).division_size, 3)
        self.assertEqual(db.session.get(Match, match_3.id).division_size, 3)
        self.assertIsNone(db.session.get(Match, unnumbered_match.id).division_size)
        self.assertEqual(
            db.session.get(Match, other_division_match.id).division_size, 2
        )

        match_5 = Match(
            happened_at=datetime(2026, 1, 1, 10, 40),
            event_id=event.id,
            division_id=division.id,
            rated=True,
            match_number=5,
        )
        db.session.add(match_5)
        db.session.flush()

        refresh_match_division_sizes(db.session, [event.id])
        db.session.expire_all()

        self.assertEqual(db.session.get(Match, match_1.id).division_size, 5)
        self.assertEqual(db.session.get(Match, match_3.id).division_size, 5)
        self.assertEqual(db.session.get(Match, match_5.id).division_size, 5)
        self.assertIsNone(db.session.get(Match, unnumbered_match.id).division_size)

    def test_process_file_sets_division_size_from_max_match_number(self):
        rows = [
            self._base_match_csv_row(
                Date="2026-01-01T10:00:00",
                **{
                    "Red ID": "red-1",
                    "Blue ID": "blue-1",
                    "Match Number": "1",
                },
            ),
            self._base_match_csv_row(
                Date="2026-01-01T10:10:00",
                **{
                    "Red ID": "red-2",
                    "Blue ID": "blue-2",
                    "Match Number": "",
                },
            ),
            self._base_match_csv_row(
                Date="2026-01-01T10:20:00",
                **{
                    "Red ID": "red-3",
                    "Blue ID": "blue-3",
                    "Match Number": "3",
                },
            ),
        ]

        self._process_csv_rows(rows)

        matches = db.session.query(Match).all()
        division_sizes_by_match_number = {
            match.match_number: match.division_size for match in matches
        }
        self.assertEqual(division_sizes_by_match_number[1], 3)
        self.assertEqual(division_sizes_by_match_number[3], 3)
        self.assertIsNone(division_sizes_by_match_number[None])

    def test_process_file_partial_import_refreshes_existing_division_size(self):
        event = Event(
            ibjjf_id="partial-event-1",
            name="Partial Event",
            normalized_name="partial event",
            slug="partial-event",
        )
        division = Division(
            gi=True,
            gender="Male",
            age="Adult",
            belt="BLACK",
            weight="Light",
        )
        existing_match = Match(
            happened_at=datetime(2026, 1, 1, 10, 0),
            event_id=None,
            division_id=None,
            rated=True,
            match_number=2,
            division_size=2,
        )
        db.session.add_all([event, division])
        db.session.flush()
        existing_match.event_id = event.id
        existing_match.division_id = division.id
        db.session.add(existing_match)
        db.session.commit()

        self._process_csv_rows(
            [
                self._base_match_csv_row(
                    **{
                        "Tournament ID": "partial-event-1",
                        "Tournament Name": "Partial Event",
                        "Partial Tournament": "true",
                        "Date": "2026-01-01T10:30:00",
                        "Red ID": "red-new",
                        "Blue ID": "blue-new",
                        "Match Number": "5",
                    }
                )
            ]
        )

        matches = db.session.query(Match).order_by(Match.match_number).all()
        self.assertEqual([match.match_number for match in matches], [2, 5])
        self.assertEqual([match.division_size for match in matches], [5, 5])

    def test_process_file_preserves_juvenile_variant_age(self):
        row = {
            "Tournament ID": "juvenile-event-1",
            "Tournament Name": "Juvenile Split Open",
            "Partial Tournament": "false",
            "Gi": "true",
            "Date": "2026-01-01T10:00:00",
            "Age": "Juvenile 1",
            "Belt": "BLUE",
            "Weight": "Light",
            "Gender": "Male",
            "Red Winner": "true",
            "Blue Winner": "false",
            "Red Medal": "",
            "Blue Medal": "",
            "Red ID": "red-1",
            "Red Name": "Red Juvenile",
            "Red Team": "Red Team",
            "Red Seed": "1",
            "Red Note": "",
            "Blue ID": "blue-1",
            "Blue Name": "Blue Juvenile",
            "Blue Team": "Blue Team",
            "Blue Seed": "2",
            "Blue Note": "",
            "Match Number": "1",
            "Match Location": "Mat 1",
            "Fight Number": "1",
        }

        self._process_csv_rows([row])

        division = db.session.query(Division).one()
        self.assertEqual(division.age, JUVENILE_1)


if __name__ == "__main__":
    unittest.main()
