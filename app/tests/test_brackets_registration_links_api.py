import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module
from extensions import db
from models import RegistrationLink


class BracketsRegistrationLinksApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.temp_dir, "test.db")
        app_module.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{cls.db_path}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        with app_module.app.app_context():
            db.drop_all()
            db.create_all()
            cls._seed_data()

    @classmethod
    def tearDownClass(cls):
        with app_module.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(cls.temp_dir)

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
        self.client = app_module.app.test_client()

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


if __name__ == "__main__":
    unittest.main()
