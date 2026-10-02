import contextlib
import io
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
)

from constants import ADULT, BLACK, FEATHER, MALE
from extensions import db
from models import Athlete, Division, Event, Medal, ResultMedal, Team
from test_db import TestDbMixin


class DefaultGoldRecoveryTest(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        with self.app_module.app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add(
                Division(
                    gi=True,
                    belt=BLACK,
                    age=ADULT,
                    gender=MALE,
                    weight=FEATHER,
                )
            )
            db.session.commit()

    def athlete(self, name, personal_name=None):
        import medal_import_lib as lib

        athlete = Athlete(
            id=uuid.uuid4(),
            name=name,
            normalized_name=lib.normalize(name),
            slug=str(uuid.uuid4()),
            personal_name=personal_name,
            normalized_personal_name=(
                lib.normalize(personal_name) if personal_name else None
            ),
        )
        db.session.add(athlete)
        db.session.flush()
        return athlete.id

    def result(self, name, event="Recovery Open 2026", place=1, active=True):
        row = ResultMedal(
            id=uuid.uuid4(),
            athlete_name=name,
            event_name=event,
            event_ibjjf_id=event,
            division="BLACK / Adult / Male / Feather",
            team_name="Recovery Team",
            place=place,
            active=active,
            source="ibjjf",
            scraped_at=datetime(2026, 10, 1),
        )
        db.session.add(row)
        db.session.commit()
        return row

    def run_import(self, *extra):
        import match_historical_medals as importer

        with tempfile.TemporaryDirectory() as directory:
            argv = [
                "match_historical_medals.py",
                "--default-golds-only",
                "--report-csv",
                os.path.join(directory, "review.csv"),
                "--resume-file",
                os.path.join(directory, "resume"),
                *extra,
            ]
            output = io.StringIO()
            with (
                mock.patch.object(importer, "app", self.app_module.app),
                mock.patch.object(sys, "argv", argv),
                mock.patch(
                    "rapidfuzz.process.extract",
                    side_effect=AssertionError("fuzzy matching"),
                ),
                mock.patch.object(
                    importer.lib,
                    "resolve_identity",
                    create=True,
                    side_effect=AssertionError("alias matching"),
                ),
                contextlib.redirect_stdout(output),
            ):
                importer.main()
            return output.getvalue()

    def test_exact_solo_gold_dry_run_import_and_rerun(self):
        with self.app_module.app.app_context():
            athlete_id = self.athlete("Exact Winner")
            self.result("Exact Winner")
            # Retired name observations must not make the active gold non-solo.
            self.result("Old Winner Name", active=False)
        output = self.run_import("--dry-run")
        self.assertIn("Medals imported:           1", output)
        with self.app_module.app.app_context():
            self.assertEqual(db.session.query(Medal).count(), 0)
            self.assertEqual(db.session.query(Event).count(), 0)
            self.assertEqual(db.session.query(Team).count(), 0)
        self.run_import()
        self.run_import()
        with self.app_module.app.app_context():
            medal = db.session.query(Medal).one()
            self.assertEqual(medal.athlete_id, athlete_id)
            self.assertEqual(medal.place, 1)
            self.assertTrue(medal.default_gold)
            self.assertEqual(medal.imported_via, "default_gold_exact")

    def test_excludes_non_solo_non_gold_and_inactive_results(self):
        with self.app_module.app.app_context():
            self.athlete("Exact Winner")
            self.result("Exact Winner", event="Contested 2026")
            self.result("Other Athlete", event="Contested 2026", place=2)
            self.result("Exact Winner", event="Silver Only 2026", place=2)
            self.result("Exact Winner", event="Retired 2026", active=False)
            self.result("Exact Winner", event="Two Golds 2026")
            self.result("Other Athlete", event="Two Golds 2026")
        self.run_import()
        with self.app_module.app.app_context():
            self.assertEqual(db.session.query(Medal).count(), 0)

    def test_no_alias_normalization_fuzzy_or_ambiguous_name_matches(self):
        with self.app_module.app.app_context():
            self.athlete("Exact Winner", personal_name="Personal Alias")
            self.athlete("Duplicate Name")
            duplicate_id = self.athlete("Duplicate Name")
            for index, name in enumerate(
                [
                    "exact winner",
                    "Éxact Winner",
                    "Exact  Winner",
                    "Personal Alias",
                    "Exact Winners",
                    "E. Winner",
                    "Duplicate Name",
                    "Unknown Winner",
                ]
            ):
                self.result(name, event=f"Mismatch {index} 2026")
        self.run_import()
        self.run_import("--athlete-id", str(duplicate_id))
        with self.app_module.app.app_context():
            self.assertEqual(db.session.query(Medal).count(), 0)

    def test_event_scope_and_existing_medal_are_preserved(self):
        with self.app_module.app.app_context():
            self.athlete("Exact Winner")
            self.result("Exact Winner", event="Chosen 2026")
            self.result("Exact Winner", event="Other 2026")
        self.run_import("--event-ibjjf-id", "Chosen 2026")
        with self.app_module.app.app_context():
            medal = db.session.query(Medal).one()
            self.assertEqual(medal.event.ibjjf_id, "Chosen 2026")
            # Recovery must not overwrite an existing non-default medal.
            medal.default_gold = False
            medal.place = 2
            db.session.commit()
        self.run_import("--event-name", "Chosen")
        with self.app_module.app.app_context():
            medal = db.session.query(Medal).one()
            self.assertEqual(medal.place, 2)
            self.assertFalse(medal.default_gold)

    def seed_replacement(self):
        with self.app_module.app.app_context():
            self.athlete("First Winner")
            self.result("First Winner", event="First Open 2026")
            self.athlete("Second Winner")
            self.result("Second Winner", event="Second Open 2026")
        self.run_import()
        with self.app_module.app.app_context():
            existing = db.session.query(Medal).first()
            for name, place, default_gold in [
                ("False Solo Winner", 1, True),
                ("Earned Gold Winner", 1, False),
                ("Other Medal Winner", 2, True),
            ]:
                db.session.add(
                    Medal(
                        athlete_id=self.athlete(name),
                        event_id=existing.event_id,
                        division_id=existing.division_id,
                        team_id=existing.team_id,
                        happened_at=existing.happened_at,
                        place=place,
                        default_gold=default_gold,
                    )
                )
            db.session.commit()
        return self.medal_snapshot()

    def medal_snapshot(self):
        with self.app_module.app.app_context():
            return {
                medal.id: (medal.athlete.name, medal.place, medal.default_gold)
                for medal in db.session.query(Medal).all()
            }

    def test_replacement_preview_counts_existing_golds_and_preserves_every_row(self):
        before = self.seed_replacement()
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = os.path.join(directory, "checkpoint")
            with open(checkpoint, "w") as handle:
                handle.write("unchanged")
            output = self.run_import(
                "--replace-default-golds", "--dry-run", "--resume-file", checkpoint
            )
            with open(checkpoint) as handle:
                self.assertEqual(handle.read(), "unchanged")
        self.assertIn("Would delete existing default golds: 3", output)
        self.assertIn("Medals imported:           2", output)
        self.assertEqual(self.medal_snapshot(), before)

    def test_replacement_commits_all_golds_and_preserves_other_medals(self):
        before = self.seed_replacement()
        self.run_import("--replace-default-golds")
        after = self.medal_snapshot()
        self.assertEqual(len(after), 4)
        for medal_id, values in before.items():
            if values[1:] == (1, True):
                self.assertNotIn(medal_id, after)
            else:
                self.assertEqual(after[medal_id], values)
        self.assertEqual(
            {values[0] for values in after.values() if values[1:] == (1, True)},
            {"First Winner", "Second Winner"},
        )

    def test_replacement_failure_after_multiple_athletes_restores_originals(self):
        import match_historical_medals as importer

        before = self.seed_replacement()
        insert = importer.lib.insert_medal
        calls = []

        def fail_second_insert(*args, **kwargs):
            medal = insert(*args, **kwargs)
            calls.append(medal.id)
            if len(calls) == 2:
                raise RuntimeError("injected import failure")
            return medal

        with mock.patch.object(
            importer.lib, "insert_medal", side_effect=fail_second_insert
        ):
            with self.assertRaisesRegex(RuntimeError, "injected import failure"):
                self.run_import("--replace-default-golds", "--report-csv", "")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.medal_snapshot(), before)

    def test_replacement_commit_failure_restores_originals(self):
        before = self.seed_replacement()
        with mock.patch.object(
            db.session, "commit", side_effect=RuntimeError("commit failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                self.run_import("--replace-default-golds")
        self.assertEqual(self.medal_snapshot(), before)

    def test_replacement_rejects_partial_import_or_resume(self):
        import match_historical_medals as importer

        for option in [
            ["--event-name", "Chosen"],
            ["--event-ibjjf-id", "123"],
            ["--athlete-id", str(uuid.uuid4())],
            ["--limit", "0"],
            ["--resume"],
        ]:
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.run_import("--replace-default-golds", *option)
                self.assertEqual(error.exception.code, 2)
        with mock.patch.object(sys, "argv", ["importer", "--replace-default-golds"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                SystemExit
            ):
                importer.parse_args()
