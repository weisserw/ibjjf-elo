import os
import sys
import unittest
import uuid
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from extensions import db
from models import Athlete, ResultMedal
from test_db import TestDbMixin

import get_medals


NEW_FORMAT_HTML = """
<html>
  <body>
    <h4 class="subtitle">BLACK / Adult / Male / Feather</h4>
    <div class="list">
      <div class="athlete-item">
        <div class="position-athlete">1</div>
        <div class="name"><p>Athlete One <span>Team One</span></p></div>
      </div>
    </div>
  </body>
</html>
"""


class ResultMedalScraperTestCase(unittest.TestCase):
    def test_build_result_links_can_target_one_exact_championship(self):
        with mock.patch("get_medals.fetch", return_value="<html></html>"):
            links = get_medals.build_result_links(
                source="ibjjf",
                year="2023",
                championship_id="2354",
                session=mock.Mock(),
                log=lambda _msg: None,
            )

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["tournament"], "Nacional Open Portugal")
        self.assertEqual(get_medals.extract_championship_id(links[0]["url"]), "2354")

    def test_iter_result_medal_rows_uses_link_metadata_and_stable_id(self):
        links = [
            {
                "tournament": "Test Championship",
                "year": "2026",
                "url": "https://www.ibjjfdb.com/ChampionshipResults/123/PublicResults?lang=en-US",
                "source": "ibjjf",
            }
        ]
        stats = {}

        with mock.patch("get_medals.fetch", return_value=NEW_FORMAT_HTML):
            rows = list(
                get_medals.iter_result_medal_rows(
                    links,
                    session=mock.Mock(),
                    scraped_at="2026-05-27T12:00:00",
                    stats=stats,
                    delay_seconds=0,
                    log=lambda _msg: None,
                )
            )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event_name"], "Test Championship 2026")
        self.assertEqual(row["event_ibjjf_id"], "123")
        self.assertEqual(row["division"], "BLACK / Adult / Male / Feather")
        self.assertEqual(row["athlete_name"], "Athlete One")
        self.assertEqual(row["team_name"], "Team One")
        self.assertEqual(row["place"], "1")
        self.assertEqual(stats["total_rows"], 1)
        self.assertEqual(str(get_medals.deterministic_id(row)), row["id"])


class ResultMedalUpdateTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def test_insert_new_rows_is_insert_only_and_idempotent(self):
        import update_result_medals

        row_id = uuid.uuid4()
        row = {
            "id": str(row_id),
            "event_name": "Test Championship 2026",
            "event_ibjjf_id": "123",
            "division": "black / adult / male / feather",
            "athlete_name": "Athlete One",
            "team_name": "Team One",
            "place": "1",
            "source": "ibjjf",
            "event_url": "https://example.com/results",
            "scraped_at": "2026-05-27T12:00:00",
        }

        with self.app_module.app.app_context():
            inserted, existing = update_result_medals.insert_new_rows(db.session, [row])
            self.assertEqual((inserted, existing), (1, 0))

            inserted, existing = update_result_medals.insert_new_rows(
                db.session, [dict(row, scraped_at="2026-05-28T12:00:00")]
            )
            self.assertEqual((inserted, existing), (0, 1))

            medal = db.session.get(ResultMedal, row_id)
            self.assertIsNotNone(medal)
            self.assertEqual(medal.scraped_at, datetime(2026, 5, 27, 12, 0, 0))

    def test_historical_match_scope_filters_exact_event_id(self):
        import match_historical_medals

        shared = {
            "event_name": "Nacional Open Portugal 2023",
            "division": "BLACK / Adult / Male / Feather",
            "athlete_name": "Scoped Athlete",
            "team_name": "Scoped Team",
            "place": 1,
            "source": "ibjjf",
            "scraped_at": datetime(2026, 9, 2, 12, 0, 0),
        }
        with self.app_module.app.app_context():
            db.session.add_all(
                [
                    ResultMedal(id=uuid.uuid4(), event_ibjjf_id="2354", **shared),
                    ResultMedal(id=uuid.uuid4(), event_ibjjf_id="other", **shared),
                ]
            )
            db.session.flush()

            rows = match_historical_medals.scope_result_medals_query(
                db.session.query(ResultMedal),
                event_name="Nacional Open Portugal 2023",
                event_ibjjf_id="2354",
            ).all()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].event_ibjjf_id, "2354")

    def test_historical_match_athlete_scan_is_not_identity_mapped(self):
        import match_historical_medals

        athlete_id = uuid.uuid4()
        with self.app_module.app.app_context():
            db.session.add(
                Athlete(
                    id=athlete_id,
                    name="Lightweight Query Athlete",
                    normalized_name="lightweight query athlete",
                    slug=f"lightweight-query-athlete-{athlete_id}",
                )
            )
            db.session.commit()
            db.session.expunge_all()

            rows = (
                match_historical_medals.build_athlete_rows_query(db.session)
                .filter(Athlete.id == athlete_id)
                .all()
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, athlete_id)
            self.assertFalse(
                any(
                    isinstance(obj, Athlete) for obj in db.session.identity_map.values()
                )
            )
