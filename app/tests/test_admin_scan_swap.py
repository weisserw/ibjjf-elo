import importlib
import os
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "app"))


class AdminScanSwapTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = importlib.import_module("admin.app")

    def setUp(self):
        self.archive = SimpleNamespace(id=uuid.uuid4())
        self.scan = SimpleNamespace(id=uuid.uuid4())
        self.event = SimpleNamespace(id=uuid.uuid4(), match_id=uuid.uuid4())
        self.participants = [
            SimpleNamespace(scoreboard_position="top"),
            SimpleNamespace(scoreboard_position="bottom"),
        ]

    def swap(self, event_exists=True, event_id=None):
        with patch.object(
            self.admin, "LivestreamFrameArchive"
        ) as archives, patch.object(
            self.admin, "LivestreamFrameTextScan"
        ) as scans, patch.object(
            self.admin, "LivestreamFrameTextEvent"
        ) as events, patch.object(
            self.admin, "MatchParticipant"
        ) as participants, patch.object(
            self.admin, "db"
        ) as database, patch.object(
            self.admin, "link_completed_text_scan"
        ) as relink:
            archives.query.get.return_value = self.archive
            scans.query.filter_by.return_value.one_or_none.return_value = self.scan
            events.query.filter_by.return_value.one_or_none.return_value = (
                self.event if event_exists else None
            )
            participants.query.filter_by.return_value.all.return_value = (
                self.participants
            )
            with self.admin.app.test_request_context(
                method="POST",
                data={
                    "action": "swap_match",
                    "event_id": event_id or str(self.event.id),
                },
            ):
                try:
                    response = self.admin.livestream_frame_text_scan_detail(
                        str(self.archive.id)
                    )
                except Exception:
                    database.session.commit.assert_not_called()
                    raise
            events.query.filter_by.assert_called_once_with(
                id=self.event.id, scan_id=self.scan.id, archive_id=self.archive.id
            )
            database.session.commit.assert_called_once_with()
            relink.assert_not_called()
            return response

    def test_swap_updates_both_positions_and_can_be_reversed(self):
        response = self.swap()
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"#event-{self.event.id}", response.location)
        self.assertEqual(
            [p.scoreboard_position for p in self.participants], ["bottom", "top"]
        )
        self.swap()
        self.assertEqual(
            [p.scoreboard_position for p in self.participants], ["top", "bottom"]
        )

    def test_rejects_event_outside_scan(self):
        from werkzeug.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            self.swap(event_exists=False)

    def test_rejects_unlinked_event(self):
        from werkzeug.exceptions import BadRequest

        self.event.match_id = None
        with self.assertRaises(BadRequest):
            self.swap()

    def test_rejects_missing_orientation_and_invalid_event_id(self):
        from werkzeug.exceptions import BadRequest

        self.participants[0].scoreboard_position = None
        with self.assertRaises(BadRequest):
            self.swap()
        with self.assertRaises(BadRequest):
            self.swap(event_id="invalid")
