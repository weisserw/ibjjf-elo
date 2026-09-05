"""Opt-in real multi-process lease tests against a disposable PostgreSQL database.

WATCHLIST_TEST_POSTGRES_URL must point to a test database. Each run owns and
removes a unique schema; it never creates or deletes application tables.
"""

import multiprocessing
import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask
from sqlalchemy import create_engine, text
from extensions import db
from models import WatchlistSchedule, WatchlistRefreshSlot
from watchlist_refresh import claim, database_now, finish, renew


def test_app(url, schema):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            "connect_args": {"options": "-csearch_path=" + schema}
        },
    )
    db.init_app(app)
    return app


def claimant(url, schema, event, barrier, queue):
    app = test_app(url, schema)
    with app.app_context():
        try:
            barrier.wait(timeout=20)
            lease = claim(event)
            queue.put(
                (event, str(lease[0]) if lease else None, lease[1] if lease else None)
            )
        except Exception as exc:
            queue.put((event, "ERROR:" + type(exc).__name__, None))
        finally:
            db.session.remove()
            db.engine.dispose()


@unittest.skipUnless(
    os.environ.get("WATCHLIST_TEST_POSTGRES_URL"), "requires disposable PostgreSQL"
)
class WatchlistPostgresTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["WATCHLIST_TEST_POSTGRES_URL"]
        self.schema = "watchlist_test_" + uuid.uuid4().hex
        self.engine = create_engine(self.url)
        with self.engine.begin() as conn:
            conn.execute(text('CREATE SCHEMA "' + self.schema + '"'))
        self.app = test_app(self.url, self.schema)
        self.context = self.app.app_context()
        self.context.push()
        db.metadata.create_all(
            db.engine,
            tables=[WatchlistSchedule.__table__, WatchlistRefreshSlot.__table__],
        )

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        with self.engine.begin() as conn:
            conn.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))
        self.engine.dispose()

    def compete(self, events):
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(len(events)), ctx.Queue()
        processes = [
            ctx.Process(
                target=claimant, args=(self.url, self.schema, e, barrier, queue)
            )
            for e in events
        ]
        for process in processes:
            process.start()
        try:
            results = [queue.get(timeout=30) for _ in processes]
            for process in processes:
                process.join(timeout=5)
                self.assertEqual(process.exitcode, 0)
            self.assertFalse(
                any(str(r[1]).startswith("ERROR:") for r in results), results
            )
            return results
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            queue.close()

    def test_simultaneous_processes_claim_one_tournament_once(self):
        results = self.compete(["1"] * 6)
        self.assertEqual(sum(token is not None for _, token, _ in results), 1)
        self.assertEqual(
            db.session.query(WatchlistRefreshSlot)
            .filter(WatchlistRefreshSlot.owner_token.isnot(None))
            .count(),
            1,
        )

    def test_global_capacity_across_processes_and_crash_recovery(self):
        results = self.compete([str(i) for i in range(6)])
        winners = [r for r in results if r[1]]
        self.assertEqual(len(winners), 2)
        event, token, slot = winners[0]
        token = uuid.UUID(token)
        # The claiming processes have exited; leases survive until expiry.
        renew(event, token, slot, 600)
        now = database_now()
        db.session.query(WatchlistSchedule).filter_by(event_id=event).update(
            {"lease_until": now - timedelta(seconds=1)}
        )
        db.session.query(WatchlistRefreshSlot).filter_by(id=slot).update(
            {"lease_until": now - timedelta(seconds=1)}
        )
        db.session.commit()
        replacement = claim(event)
        self.assertIsNotNone(replacement)
        self.assertFalse(finish(event, token, slot, result=([{"old": True}], [], {})))
        self.assertTrue(
            finish(event, *replacement, result=([], [{"state": "complete"}], {}))
        )
        self.assertEqual(db.session.get(WatchlistSchedule, event).snapshot, [])

    def test_migration_round_trip(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        path = (
            Path(__file__).parent.parent
            / "migrations/versions/9d3f5a7b1c20_add_watchlists.py"
        )
        spec = importlib.util.spec_from_file_location("watchlist_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        db.session.remove()
        with db.engine.begin() as conn:
            conn.execute(
                text("DROP TABLE watchlist_refresh_slots, watchlist_schedules")
            )
            conn.execute(text("CREATE TABLE athletes (id uuid PRIMARY KEY, name text)"))
            conn.execute(text("CREATE TABLE registration_links (id uuid PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE registration_link_competitors (id uuid PRIMARY KEY, registration_link_id uuid, athlete_name text)"
                )
            )
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                self.assertEqual(
                    conn.execute(
                        text("SELECT count(*) FROM watchlist_refresh_slots")
                    ).scalar(),
                    2,
                )
                migration.downgrade()
            self.assertIsNone(
                conn.execute(text("SELECT to_regclass('watchlists')")).scalar()
            )


if __name__ == "__main__":
    unittest.main()
