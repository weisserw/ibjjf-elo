import importlib
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from io import BytesIO

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "admin")))

from extensions import db  # noqa: E402
from models import Athlete  # noqa: E402
from normalize import normalize  # noqa: E402


class AdminAthleteEditTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.admin_module = importlib.import_module("admin.app")
        cls.admin_module.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=(
                f"sqlite:///{os.path.join(cls.temp_dir, 'test.db')}"
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        cls.app_context = cls.admin_module.app.app_context()
        cls.app_context.push()
        db.drop_all()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.app_context.pop()
        shutil.rmtree(cls.temp_dir)

    def setUp(self):
        Athlete.query.delete()
        db.session.commit()

        self.athlete = Athlete(
            name="Original Name",
            normalized_name="original name",
            slug=f"original-name-{uuid.uuid4().hex[:8]}",
        )
        db.session.add(self.athlete)
        db.session.commit()
        self.athlete_id = self.athlete.id
        self.client = self.admin_module.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def tearDown(self):
        db.session.remove()

    def _reload_athlete(self):
        db.session.expire_all()
        athlete = db.session.get(Athlete, self.athlete_id)
        return athlete.name, athlete.normalized_name

    def test_edit_updates_full_and_normalized_name_together(self):
        full_name = "  José da Silva  "

        response = self.client.post(
            f"/athlete_edit?id={self.athlete_id}",
            data={"name": full_name},
        )

        self.assertEqual(response.status_code, 200)
        name, normalized_name = self._reload_athlete()
        self.assertEqual(name, "José da Silva")
        self.assertEqual(normalized_name, normalize("José da Silva"))

    def test_edit_rolls_back_both_name_fields_when_submission_fails(self):
        response = self.client.post(
            f"/athlete_edit?id={self.athlete_id}",
            data={
                "name": "Updated Name",
                "profile_photo": (BytesIO(b"not-a-jpeg"), "photo.jpg"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        name, normalized_name = self._reload_athlete()
        self.assertEqual(name, "Original Name")
        self.assertEqual(normalized_name, "original name")


if __name__ == "__main__":
    unittest.main()
