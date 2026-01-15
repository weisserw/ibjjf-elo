import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from models import Athlete, AthleteRating
from test_db import TestDbMixin


class TopApiTestCase(TestDbMixin, unittest.TestCase):

    @classmethod
    def _seed_data(cls):
        athlete = Athlete(
            name="Test Athlete",
            normalized_name="test athlete",
            slug="test-athlete",
            instagram_profile=None,
            country="US",
            country_note=None,
            country_note_pt=None,
            personal_name=None,
            normalized_personal_name=None,
            profile_image_saved_at=None,
            nickname_translation=None,
            bjjheroes_link=None,
        )
        db.session.add(athlete)
        db.session.flush()
        rating = AthleteRating(
            athlete_id=athlete.id,
            gender="male",
            age="adult",
            belt="black",
            gi=True,
            weight="",
            rating=1500.0,
            match_happened_at=datetime.utcnow(),
            rank=1,
            percentile=99.0,
            match_count=10,
            previous_rating=1400.0,
            previous_rank=2,
            previous_match_count=8,
            previous_percentile=98.0,
        )
        db.session.add(rating)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    @mock.patch("routes.top.get_s3_client", return_value=None)
    def test_top_basic(self, _mock_s3):
        response = self.client.get("/api/top?gender=male&age=adult&belt=black&gi=true")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("rows", data)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["name"], "Test Athlete")
        self.assertEqual(data["rows"][0]["rank"], 1)

    def test_top_missing_params(self):
        response = self.client.get("/api/top")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
