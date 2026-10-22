import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask
from extensions import db
from livestream_copy import STREAM_FIELDS, copy_sources, copy_streams
from models import LiveStream, RegistrationLink


class LivestreamCopyTestCase(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        db.init_app(app)
        self.context = app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def stream(self, event="source", day=2, mat=1):
        stream = LiveStream(
            event_id=event,
            day_number=day,
            mat_number=mat,
            platform="youtube",
            start_hour=9,
            start_minute=29,
            start_seconds=15,
            end_hour=23,
            end_minute=0,
            drift_factor=1.001,
            hide_all=True,
            link=f"https://www.youtube.com/watch?v=mat{mat}",
        )
        db.session.add(stream)
        db.session.flush()
        return stream

    def test_copy_preserves_settings_and_existing_streams_and_skips_duplicates(self):
        source = self.stream()
        self.stream(mat=2)
        self.stream(day=1, mat=3)
        existing = self.stream(event="target", day=1, mat=4)
        self.assertEqual(copy_streams(db.session, "source", 2, "target"), 2)
        db.session.commit()
        copied = LiveStream.query.filter_by(event_id="target", mat_number=1).one()
        self.assertNotEqual(copied.id, source.id)
        for field in STREAM_FIELDS:
            self.assertEqual(
                getattr(copied, field),
                1 if field == "day_number" else getattr(source, field),
            )
        self.assertEqual(source.day_number, 2)
        self.assertEqual(existing.mat_number, 4)
        self.assertEqual(copy_streams(db.session, "source", 2, "target"), 0)
        self.assertEqual(LiveStream.query.filter_by(event_id="target").count(), 3)

    def test_day_one_stays_one_and_later_days_decrement(self):
        for day in (1, 3):
            self.stream(day=day)
            self.assertEqual(
                copy_streams(db.session, "source", day, f"target-{day}"), 1
            )
            db.session.flush()
            self.assertEqual(
                LiveStream.query.filter_by(event_id=f"target-{day}").one().day_number,
                max(1, day - 1),
            )

    def test_invalid_source_does_not_copy(self):
        self.stream()
        for event, day, target in [
            ("source", 2, "source"),
            ("source", 0, "target"),
            ("source", None, "target"),
            ("source", 4, "target"),
            ("missing", 2, "target"),
            ("source", 2, None),
        ]:
            with self.assertRaises(ValueError):
                copy_streams(db.session, event, day, target)
        self.assertEqual(LiveStream.query.count(), 1)

    def test_sources_are_recent_limited_and_have_only_available_days(self):
        for number in range(1, 9):
            event = str(number)
            db.session.add(
                RegistrationLink(
                    event_id=event,
                    name=f"Event {number}",
                    normalized_name=f"event {number}",
                    link=f"https://example.com/{number}",
                    updated_at=datetime(2026, 1, 1),
                    event_start_date=datetime(2026, 1, number),
                )
            )
            self.stream(event=event)
            self.stream(event=event, day=1)
        self.stream(event="unknown-date")
        db.session.commit()
        sources = copy_sources(db.session, "8")
        self.assertEqual(
            [row["event_id"] for row in sources], ["7", "6", "5", "4", "3", "2"]
        )
        self.assertEqual(sources[0]["days"], [1, 2])
        self.assertEqual(sources[0]["name"], "Event 7")


if __name__ == "__main__":
    unittest.main()
