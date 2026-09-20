import os
import sys
import unittest
import uuid
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
)

from extensions import db
from models import Athlete, AthleteMediaCoverage
from test_db import TestDbMixin

import merge_athletes as merge_module


class AthleteMergeTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        with self.app_module.app.app_context():
            db.session.query(AthleteMediaCoverage).delete()
            db.session.query(Athlete).delete()
            db.session.commit()

    def athlete(self, name, **values):
        athlete = Athlete(
            id=uuid.uuid4(),
            name=name,
            normalized_name=name.lower(),
            slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
            **values,
        )
        db.session.add(athlete)
        db.session.flush()
        return athlete

    def test_merge_moves_media_and_preserves_profile_fields(self):
        with self.app_module.app.app_context():
            keep = self.athlete("New Name", ibjjf_id="123")
            merge = self.athlete("Old Name", country="BR", personal_name="Nickname")
            coverage = AthleteMediaCoverage(
                athlete_id=merge.id,
                covered_at=date(2025, 1, 1),
                coverage_type="feature",
                url="https://example.com/profile",
                title="Profile",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(coverage)
            merge_module.merge_athletes(keep, merge)
            db.session.commit()

            self.assertIsNone(db.session.get(Athlete, merge.id))
            self.assertEqual(keep.country, "BR")
            self.assertEqual(keep.personal_name, "Nickname")
            self.assertEqual(coverage.athlete_id, keep.id)

    def test_merge_rejects_different_ibjjf_ids(self):
        with self.app_module.app.app_context():
            keep = self.athlete("New Name", ibjjf_id="123")
            merge = self.athlete("Old Name", ibjjf_id="456")
            with self.assertRaisesRegex(ValueError, "different non-empty IBJJF IDs"):
                merge_module.merge_athletes(keep, merge)

    def test_merge_rejects_photo_loss(self):
        with self.app_module.app.app_context():
            keep = self.athlete("New Name")
            merge = self.athlete("Old Name", profile_image_saved_at=datetime.utcnow())
            with self.assertRaisesRegex(ValueError, "only profile photo"):
                merge_module.merge_athletes(keep, merge)


if __name__ == "__main__":
    unittest.main()
