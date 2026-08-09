import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from scripts.get_upcoming import update_event_dates


class GetUpcomingTestCase(unittest.TestCase):
    def test_update_event_dates_replaces_dates_without_changing_event_id(self):
        link = SimpleNamespace(
            event_id="old-id",
            event_start_date=datetime(2026, 1, 1),
            event_end_date=datetime(2026, 1, 2),
        )
        start_date = datetime(2026, 2, 3)
        end_date = datetime(2026, 2, 5)

        update_event_dates(link, start_date, end_date)

        self.assertEqual(link.event_id, "old-id")
        self.assertEqual(link.event_start_date, start_date)
        self.assertEqual(link.event_end_date, end_date)


if __name__ == "__main__":
    unittest.main()
