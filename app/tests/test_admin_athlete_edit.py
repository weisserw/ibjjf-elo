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
from models import Athlete, ResultRenameObservation, ResultSnapshot  # noqa: E402
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
        ResultRenameObservation.query.delete()
        ResultSnapshot.query.delete()
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

    def _rename_observation(self, old_name, new_name, athlete=None):
        snapshot = ResultSnapshot(status="complete", stats={})
        db.session.add(snapshot)
        db.session.flush()
        observation = ResultRenameObservation(
            snapshot_id=snapshot.id,
            athlete_id=athlete.id if athlete else None,
            slot_key=uuid.uuid4().hex,
            old_name=old_name,
            new_name=new_name,
            change_type="renamed",
            status="pending",
            evidence="unique_result_slot",
        )
        db.session.add(observation)
        db.session.commit()
        return observation

    def test_result_name_change_applies_all_normalized_fields(self):
        observation = self._rename_observation(
            "Original Name", "José Newname", self.athlete
        )

        response = self.client.post(
            "/result_name_changes/apply",
            data={"observation_id": str(observation.id)},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        athlete = db.session.get(Athlete, self.athlete_id)
        observation = db.session.get(ResultRenameObservation, observation.id)
        self.assertEqual(athlete.name, "José Newname")
        self.assertEqual(athlete.normalized_name, normalize("José Newname"))
        self.assertEqual(athlete.normalized_initial_surname, "j newname")
        self.assertEqual(observation.status, "applied")
        self.assertIsNotNone(observation.applied_at)

    def test_result_name_change_records_matching_manual_edit(self):
        self.athlete.name = "New Name"
        self.athlete.normalized_name = normalize("New Name")
        db.session.commit()
        observation = self._rename_observation("Old Name", "New Name")

        response = self.client.post(
            "/result_name_changes/apply",
            data={"observation_id": str(observation.id)},
            follow_redirects=True,
        )

        self.assertIn(b"already-applied", response.data)
        db.session.expire_all()
        observation = db.session.get(ResultRenameObservation, observation.id)
        self.assertEqual(observation.status, "applied")
        self.assertEqual(observation.athlete_id, self.athlete_id)

    def test_result_name_change_does_not_overwrite_divergent_manual_edit(self):
        self.athlete.name = "Manually Chosen Name"
        self.athlete.normalized_name = normalize(self.athlete.name)
        db.session.commit()
        observation = self._rename_observation(
            "Original Name", "Observed Name", self.athlete
        )

        response = self.client.post(
            "/result_name_changes/apply",
            data={"observation_id": str(observation.id)},
            follow_redirects=True,
        )

        self.assertIn(b"manually renamed", response.data)
        db.session.expire_all()
        self.assertEqual(
            db.session.get(Athlete, self.athlete_id).name, "Manually Chosen Name"
        )
        self.assertEqual(
            db.session.get(ResultRenameObservation, observation.id).status, "pending"
        )

    def test_result_name_collision_is_not_bulk_selectable(self):
        collision = Athlete(
            name="New Name",
            normalized_name=normalize("New Name"),
            slug=f"new-name-{uuid.uuid4().hex[:8]}",
        )
        db.session.add(collision)
        db.session.commit()
        observation = self._rename_observation(
            "Original Name", "New Name", self.athlete
        )

        response = self.client.get("/result_name_changes")

        self.assertIn(b"Another athlete already has the new name", response.data)
        self.assertNotIn(
            f'class="rename-ready" type="checkbox" name="observation_id" value="{observation.id}"'.encode(),
            response.data,
        )

    def test_result_name_change_accepts_manual_athlete_resolution(self):
        duplicate = Athlete(
            name="Original Name",
            normalized_name=normalize("Original Name"),
            slug=f"duplicate-{uuid.uuid4().hex[:8]}",
        )
        db.session.add(duplicate)
        db.session.commit()
        observation = self._rename_observation("Original Name", "Resolved Name")

        response = self.client.post(
            "/result_name_changes/apply",
            data={
                "observation_id": str(observation.id),
                f"athlete_id_{observation.id}": str(self.athlete_id),
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        self.assertEqual(db.session.get(Athlete, self.athlete_id).name, "Resolved Name")
        self.assertEqual(db.session.get(Athlete, duplicate.id).name, "Original Name")
        self.assertEqual(
            db.session.get(ResultRenameObservation, observation.id).athlete_id,
            self.athlete_id,
        )

    def test_result_name_report_hides_existing_minor_abbreviations(self):
        observation = self._rename_observation(
            "Eduardo Cancela Cruz", "E. Cruz", self.athlete
        )

        response = self.client.get("/result_name_changes")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(observation.id).encode(), response.data)
        self.assertIn(b"Pending (0)", response.data)

    def test_result_name_report_hides_one_minor_change_in_crowded_slot(self):
        observation = self._rename_observation(
            "Bruno Luccas Nefe Carvalho; João Gabriel da Silva",
            "Bruno Luccas Nefe Carvalho; J. Silva",
        )
        observation.change_type = "uncertain"
        observation.evidence = "crowded_result_slot"
        db.session.commit()

        response = self.client.get("/result_name_changes")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(observation.id).encode(), response.data)
        self.assertIn(b"Pending (0)", response.data)


if __name__ == "__main__":
    unittest.main()
