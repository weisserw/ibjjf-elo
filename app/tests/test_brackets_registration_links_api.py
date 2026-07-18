import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup

from extensions import db
from constants import JUVENILE, JUVENILE_1
from models import Division, RegistrationLink, RegistrationLinkCompetitor
from routes.brackets import (
    _registration_seeding_start_date,
    import_registration_link,
    parse_registrations,
    save_competitors,
)
from test_db import TestDbMixin


class BracketsRegistrationLinksApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        now = datetime.now()
        visible_local = RegistrationLink(
            name="Local Open 2024",
            normalized_name="local open 2024",
            updated_at=now,
            link="https://example.com/local",
            hidden=False,
            event_start_date=now,
            event_end_date=now + timedelta(days=2),
        )
        visible_world = RegistrationLink(
            name="World IBJJF Championship 2024",
            normalized_name="world ibjjf championship 2024",
            updated_at=now,
            link="https://example.com/world",
            hidden=False,
            event_start_date=now,
            event_end_date=now + timedelta(days=5),
        )
        hidden_link = RegistrationLink(
            name="Hidden Open 2024",
            normalized_name="hidden open 2024",
            updated_at=now,
            link="https://example.com/hidden",
            hidden=True,
            event_start_date=now,
            event_end_date=now + timedelta(days=5),
        )
        expired_link = RegistrationLink(
            name="Expired Open 2023",
            normalized_name="expired open 2023",
            updated_at=now,
            link="https://example.com/expired",
            hidden=False,
            event_start_date=now - timedelta(days=10),
            event_end_date=now - timedelta(days=2),
        )
        db.session.add_all([visible_local, visible_world, hidden_link, expired_link])
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_registration_links_basic(self):
        response = self.client.get("/api/brackets/registrations/links")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        links = data["links"]
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0]["name"].startswith("World IBJJF Championship 2024"))
        self.assertTrue(links[1]["name"].startswith("Local Open 2024"))
        self.assertEqual(links[0]["link"], "https://example.com/world")
        self.assertEqual(links[1]["link"], "https://example.com/local")

    def test_registration_seeding_start_date_normalizes_ibjjf_link(self):
        with self.app_module.app.app_context():
            link = RegistrationLink(
                name="Charlotte Spring International Open IBJJF Jiu-Jitsu Championship 2026",
                normalized_name="charlotte spring international open ibjjf jiujitsu championship 2026",
                updated_at=datetime(2026, 5, 1),
                link="https://www.ibjjfdb.com/ChampionshipResults/3148/PublicRegistrations?lang=en-US",
                hidden=False,
                event_start_date=datetime(2026, 6, 13),
                event_end_date=datetime(2026, 6, 14),
            )
            db.session.add(link)
            db.session.commit()

            start_date = _registration_seeding_start_date(
                "https://www.ibjjfdb.com/ChampionshipResults/3148/PublicRegistrations"
            )

        self.assertEqual(start_date, datetime(2026, 6, 13))

    def test_parse_registrations_reads_legacy_script_model(self):
        soup = BeautifulSoup(
            """
            <html>
              <body>
                <script>
                  const model = [{
                    "FriendlyName": "BLUE / Adult / Male / Light",
                    "RegistrationCategories": [{
                      "AthleteName": "Legacy Athlete",
                      "AcademyTeamName": "Legacy Team"
                    }]
                  }];
                </script>
              </body>
            </html>
            """,
            "html.parser",
        )

        data = parse_registrations(soup)

        self.assertEqual(data[0]["FriendlyName"], "BLUE / Adult / Male / Light")
        self.assertEqual(
            data[0]["RegistrationCategories"][0]["AthleteName"], "Legacy Athlete"
        )
        self.assertEqual(
            data[0]["RegistrationCategories"][0]["AcademyTeamName"], "Legacy Team"
        )

    def test_parse_registrations_reads_html_registration_tables(self):
        soup = BeautifulSoup(
            """
            <div id="registrations-by-category">
              <section class="belt-group" data-belt-group="white">
                <h3 class="belt-group-name">White belt</h3>
                <section class="category-set" data-belt-group="white" data-gender="male">
                  <div class="category-header">
                    <h3 class="category-name">Adult / Male / Feather (154.60lb)</h3>
                    <span class="category-total">TOTAL:<strong>2</strong></span>
                  </div>
                  <table class="registrations-table">
                    <thead>
                      <tr><th>Team</th><th>Athlete</th></tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td class="team">Adonai Martial Arts School</td>
                        <td class="athlete">Example Athlete One</td>
                      </tr>
                      <tr>
                        <td class="team">Nova União</td>
                        <td class="athlete">Example Athlete Two</td>
                      </tr>
                    </tbody>
                  </table>
                </section>
              </section>
              <section class="belt-group" data-belt-group="black">
                <section class="category-set" data-belt-group="black" data-gender="female">
                  <div class="category-header">
                    <h3 class="category-name">Adult / Female / Open Class</h3>
                  </div>
                  <table class="registrations-table">
                    <tbody>
                      <tr>
                        <td class="team">Alliance </td>
                        <td class="athlete"> Example Athlete </td>
                      </tr>
                    </tbody>
                  </table>
                </section>
              </section>
            </div>
            """,
            "html.parser",
        )

        data = parse_registrations(soup)

        self.assertEqual(len(data), 2)
        self.assertEqual(
            data[0]["FriendlyName"], "WHITE / Adult / Male / Feather (154.60lb)"
        )
        self.assertEqual(
            data[0]["RegistrationCategories"],
            [
                {
                    "AthleteName": "Example Athlete One",
                    "AcademyTeamName": "Adonai Martial Arts School",
                },
                {
                    "AthleteName": "Example Athlete Two",
                    "AcademyTeamName": "Nova União",
                },
            ],
        )
        self.assertEqual(data[1]["FriendlyName"], "BLACK / Adult / Female / Open Class")
        self.assertEqual(
            data[1]["RegistrationCategories"][0]["AcademyTeamName"], "Alliance"
        )
        self.assertEqual(
            data[1]["RegistrationCategories"][0]["AthleteName"], "Example Athlete"
        )

    def test_import_registration_link_excludes_open_class_from_total(self):
        url = "https://www.ibjjfdb.com/ChampionshipResults/9998/PublicRegistrations"
        html = """
            <div id="registrations-by-category">
              <section class="belt-group" data-belt-group="black">
                <section class="category-set" data-gender="male">
                  <h3 class="category-name">Adult / Male / Light</h3>
                  <table class="registrations-table"><tbody>
                    <tr><td class="team">Team A</td><td class="athlete">Athlete One</td></tr>
                    <tr><td class="team">Team B</td><td class="athlete">Athlete Two</td></tr>
                  </tbody></table>
                </section>
                <section class="category-set" data-gender="male">
                  <h3 class="category-name">Adult / Male / Open Class</h3>
                  <table class="registrations-table"><tbody>
                    <tr><td class="team">Team A</td><td class="athlete">Athlete One</td></tr>
                    <tr><td class="team">Team B</td><td class="athlete">Athlete Two</td></tr>
                  </tbody></table>
                </section>
              </section>
            </div>
        """

        with self.app_module.app.app_context():
            link = RegistrationLink(
                name="Registration Open 2026",
                normalized_name="registration open 2026",
                updated_at=datetime(2026, 5, 1),
                link=f"{url}?lang=en-US",
                hidden=False,
                event_start_date=datetime(2026, 6, 13),
                event_end_date=datetime(2026, 6, 14),
            )
            db.session.add(link)
            db.session.commit()

            with patch("routes.brackets.get_bracket_page", return_value=html):
                result = import_registration_link(url, background=False)

            persisted = (
                db.session.query(RegistrationLinkCompetitor)
                .filter(RegistrationLinkCompetitor.registration_link_id == link.id)
                .all()
            )

        self.assertEqual(result["total_competitors"], 2)
        self.assertEqual(len(result["categories"]), 2)
        self.assertEqual(len(persisted), 2)

    def test_save_competitors_allows_same_athlete_in_overlapping_juvenile_divisions(
        self,
    ):
        with self.app_module.app.app_context():
            link = RegistrationLink(
                name="Juvenile Registration Open 2026",
                normalized_name="juvenile registration open 2026",
                updated_at=datetime(2026, 5, 1),
                link="https://www.ibjjfdb.com/ChampionshipResults/9999/PublicRegistrations?lang=en-US",
                hidden=False,
                event_start_date=datetime(2026, 6, 13),
                event_end_date=datetime(2026, 6, 14),
            )
            db.session.add(link)
            db.session.commit()

            json_data = [
                {
                    "FriendlyName": "BLUE / Juvenile / Female / Light",
                    "RegistrationCategories": [
                        {
                            "AthleteName": "Overlapping Juvenile",
                            "AcademyTeamName": "Team A",
                        }
                    ],
                },
                {
                    "FriendlyName": "BLUE / Juvenile 1 / Female / Light",
                    "RegistrationCategories": [
                        {
                            "AthleteName": "Overlapping Juvenile",
                            "AcademyTeamName": "Team A",
                        }
                    ],
                },
            ]
            division_set = {
                "BLUE / Juvenile / Female / Light",
                "BLUE / Juvenile 1 / Female / Light",
            }

            save_competitors(link.id, json_data, division_set)

            rows = (
                db.session.query(RegistrationLinkCompetitor, Division.age)
                .join(Division)
                .filter(RegistrationLinkCompetitor.registration_link_id == link.id)
                .all()
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual({age for _, age in rows}, {JUVENILE, JUVENILE_1})
            self.assertEqual(
                {row.athlete_name for row, _ in rows}, {"Overlapping Juvenile"}
            )


if __name__ == "__main__":
    unittest.main()
