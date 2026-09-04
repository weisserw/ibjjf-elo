import importlib
import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "app"))
sys.path.insert(0, os.path.join(REPO_ROOT, "admin"))

from constants import ADULT, BLUE, LIGHT, MALE  # noqa: E402
from extensions import db  # noqa: E402
from models import (  # noqa: E402
    BackgroundTask,
    BracketAuditCategory,
    BracketAuditRun,
    RegistrationLink,
)
from routes import brackets  # noqa: E402
from test_db import TestDbMixin  # noqa: E402


class RegistrationPredictionServiceTestCase(unittest.TestCase):
    @patch.object(
        brackets, "add_side_swaps", return_value={"swaps": [], "bailout_teams": []}
    )
    @patch.object(brackets, "add_estimated_seeds")
    @patch.object(brackets, "add_seeding_data")
    @patch.object(brackets, "get_ratings")
    @patch.object(brackets, "_registration_seeding_start_date")
    @patch.object(brackets, "_registration_rows_for_division")
    def test_shared_service_uses_one_reference_date_and_medal_cutoff(
        self,
        rows_for_division,
        seeding_start_date,
        get_ratings,
        add_seeding_data,
        add_estimated_seeds,
        add_side_swaps,
    ):
        event_start = datetime(2027, 1, 10)
        audit_time = datetime(2026, 9, 3, 12, 0)
        rows = [{"id": None, "name": "Athlete", "team": "Team"}]
        divdata = {"age": ADULT, "belt": BLUE, "gender": MALE, "weight": LIGHT}
        rows_for_division.return_value = (rows, divdata)
        seeding_start_date.return_value = event_start

        payload, provenance = brackets.build_registration_prediction(
            "internal:test",
            f"{BLUE} / {ADULT} / {MALE} / {LIGHT}",
            True,
            s3_client=None,
            now=audit_time,
        )

        get_ratings.assert_called_once_with(rows, None, True, audit_time, False, None)
        add_seeding_data.assert_called_once_with(
            rows, divdata, True, now=audit_time, medal_cutoff=event_start
        )
        add_estimated_seeds.assert_called_once_with(rows, divdata)
        add_side_swaps.assert_called_once_with(rows)
        self.assertIs(payload["competitors"], rows)
        self.assertEqual(provenance["seeding_reference_date"], audit_time)
        self.assertEqual(provenance["medal_cutoff"], event_start)


class BracketAuditPersistenceAndWorkerTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.context = self.app_module.app.app_context()
        self.context.push()
        BracketAuditCategory.query.delete()
        BracketAuditRun.query.delete()
        BackgroundTask.query.delete()
        RegistrationLink.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def make_run(self):
        link = RegistrationLink(
            name="Test Open",
            event_id="123",
            normalized_name="test open",
            updated_at=datetime(2026, 9, 1),
            link="internal:test-open",
            event_start_date=datetime(2026, 9, 10),
            event_end_date=datetime(2026, 9, 11),
        )
        task = BackgroundTask(task_type="bracket_audit", status="queued")
        db.session.add_all([link, task])
        db.session.flush()
        run = BracketAuditRun(
            background_task_id=task.id,
            registration_link_id=link.id,
            tournament_id="123",
            tournament_name="Test Open",
            gi=True,
            status="pending",
        )
        db.session.add(run)
        db.session.commit()
        return run, link, task

    def test_category_url_is_unique_within_run_and_report_round_trips(self):
        run, _, _ = self.make_run()
        category = BracketAuditCategory(
            run_id=run.id,
            category_url="https://www.bjjcompsystem.com/tournaments/123/categories/1",
            status="pending",
        )
        category.report = {"layout": {"slots": [[1, None]]}}
        db.session.add(category)
        db.session.commit()
        self.assertEqual(category.report["layout"]["slots"], [[1, None]])

        db.session.add(
            BracketAuditCategory(
                run_id=run.id,
                category_url=category.category_url,
                status="pending",
            )
        )
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_discovery_keeps_only_adult_and_master_weight_divisions(self):
        worker = importlib.import_module("bracket_audit_worker")
        run, _, _ = self.make_run()
        divisions = [
            ("Adult", "Light"),
            ("Master 7", "Light"),
            ("Juvenile 1", "Light"),
            ("Master 8", "Light"),
            ("Adult", "Open Class"),
            ("Adult", "Open Class Light"),
            ("Adult", "Open Class Heavy"),
        ]
        discovered = [
            {
                "link": f"/tournaments/123/categories/{index}",
                "age": age,
                "belt": BLUE,
                "weight": weight,
            }
            for index, (age, weight) in enumerate(divisions, start=1)
        ]

        with patch.object(
            worker, "get_bracket_page", return_value="<html></html>"
        ), patch.object(worker, "parse_categories", side_effect=[discovered, []]):
            worker.discover_categories(run)

        categories = BracketAuditCategory.query.filter_by(run_id=run.id).all()
        status_by_id = {
            category.external_category_id: category.status for category in categories
        }
        self.assertEqual(status_by_id["1"], "pending")
        self.assertEqual(status_by_id["2"], "pending")
        for category_id in ("3", "4", "5", "6", "7"):
            self.assertEqual(status_by_id[category_id], "skipped")
        self.assertEqual(run.discovered_category_count, 7)
        self.assertEqual(run.total_category_count, 2)

    def test_category_with_fewer_than_four_athletes_is_skipped_before_analysis(self):
        worker = importlib.import_module("bracket_audit_worker")
        run, link, _ = self.make_run()
        category = BracketAuditCategory(
            run=run,
            category_url="https://example.test/categories/three-athletes",
            status="pending",
        )
        db.session.add(category)
        db.session.commit()

        with patch.object(
            worker, "get_bracket_page", return_value="<html></html>"
        ), patch.object(
            worker, "parse_bracket_competitors", return_value=[{}, {}, {}]
        ), patch.object(
            worker, "parse_official_ranking"
        ) as parse_ranking, patch.object(
            worker, "build_registration_prediction"
        ) as build_prediction:
            worker.process_category(run, category, link)

        self.assertEqual(category.status, "skipped")
        self.assertEqual(category.official_competitor_count, 3)
        self.assertEqual(category.report, {})
        parse_ranking.assert_not_called()
        build_prediction.assert_not_called()
        worker._update_run_counts(run)
        self.assertEqual(run.total_category_count, 0)
        self.assertEqual(run.processed_category_count, 0)

    def test_worker_continues_after_category_error_and_sleeps_between_pages(self):
        worker = importlib.import_module("bracket_audit_worker")
        run, _, _ = self.make_run()

        def discover(run_row):
            for number in (1, 2):
                db.session.add(
                    BracketAuditCategory(
                        run=run_row,
                        category_url=f"https://example.test/categories/{number}",
                        gender=MALE,
                        age=ADULT,
                        belt=BLUE,
                        weight=LIGHT,
                        status="pending",
                    )
                )
            run_row.discovered_category_count = 2
            run_row.total_category_count = 2
            db.session.commit()

        def process(run_row, category, _link):
            if category.category_url.endswith("/1"):
                raise ValueError("broken category")
            category.status = "complete"
            category.criteria_status = "match"
            category.layout_status = "exact"

        sleeper = Mock()
        with patch.object(
            worker, "discover_categories", side_effect=discover
        ), patch.object(worker, "process_category", side_effect=process):
            result = worker.run_bracket_audit(run.id, sleep=sleeper)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.processed_category_count, 2)
        self.assertEqual(result.error_category_count, 1)
        self.assertEqual(result.clean_category_count, 1)
        sleeper.assert_called_once_with(0.5)


class BracketAuditAdminRouteTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.context = self.app_module.app.app_context()
        self.context.push()
        BracketAuditCategory.query.delete()
        BracketAuditRun.query.delete()
        BackgroundTask.query.delete()
        RegistrationLink.query.delete()
        db.session.commit()
        self.admin_module = importlib.import_module("admin.app")
        db_path = os.path.join(self.temp_dir, "test.db")
        self.admin_module.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        with self.admin_module.app.app_context():
            sqlalchemy_ext = self.admin_module.app.extensions["sqlalchemy"]
            sqlalchemy_ext.engines[None] = create_engine(f"sqlite:///{db_path}")
        self.client = self.admin_module.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def test_launch_creates_new_immutable_run_and_task(self):
        link = RegistrationLink(
            name="Test Open",
            event_id="123",
            normalized_name="test open",
            updated_at=datetime(2026, 9, 1),
            link="internal:test-open",
        )
        db.session.add(link)
        db.session.commit()

        with patch.object(self.admin_module.threading, "Thread") as thread:
            response = self.client.post(
                "/bracket_audits",
                data={
                    "tournament_id": "123",
                    "tournament_name": "Test Open",
                    "registration_link_id": str(link.id),
                    "gi_mode": "gi",
                },
            )

        self.assertEqual(response.status_code, 302)
        run = BracketAuditRun.query.one()
        task = BackgroundTask.query.one()
        self.assertEqual(run.background_task_id, task.id)
        self.assertEqual(task.task_type, "bracket_audit")
        thread.return_value.start.assert_called_once()

        report = self.client.get(f"/bracket_audits/{run.id}")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Live bracket seeding and layout audit", report.data)

    def test_report_hides_pending_and_correct_categories_by_default(self):
        run = BracketAuditRun(
            tournament_id="123",
            tournament_name="Test Open",
            gi=True,
            status="complete",
        )
        categories = [
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/match",
                status="complete",
                criteria_status="match",
                layout_status="exact",
            ),
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/tie",
                status="complete",
                criteria_status="tie_order_only",
                layout_status="exact",
            ),
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/layout-mismatch",
                status="complete",
                criteria_status="match",
                layout_status="pairing_mismatch",
            ),
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/points-mismatch",
                status="complete",
                criteria_status="criteria_mismatch",
                layout_status="exact",
            ),
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/pending",
                status="pending",
            ),
            BracketAuditCategory(
                run=run,
                category_url="https://example.test/categories/skipped",
                status="skipped",
            ),
        ]
        for category in categories:
            category.report = {"criteria": {}, "layout": {}}
        categories[2].report = {
            "criteria": {},
            "layout": {
                "expected_slots": [[2, 3], [4, 1]],
                "actual_slots": [[3, 1], [4, 2]],
            },
        }
        db.session.add(run)
        db.session.commit()

        response = self.client.get(f"/bracket_audits/{run.id}")

        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.data, "html.parser")
        rows = soup.select("[data-audit-category-row]")
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["data-audit-state"] for row in rows].count("correct"), 2)
        self.assertEqual([row["data-audit-state"] for row in rows].count("pending"), 1)
        self.assertEqual(
            [row["data-audit-state"] for row in rows].count("attention"), 2
        )
        for element in soup.select(
            '[data-audit-state="correct"], [data-audit-state="pending"]'
        ):
            self.assertTrue(element.has_attr("hidden"))
        for element in soup.select('[data-audit-state="attention"]'):
            self.assertFalse(element.has_attr("hidden"))
        response_text = response.get_data(as_text=True)
        self.assertIn("Points mismatch", response_text)
        self.assertIn("points_mismatch", response_text)
        self.assertNotIn("criteria_mismatch", response_text)
        self.assertNotIn("categories/skipped", response_text)
        mismatch_detail = next(
            detail
            for detail in soup.select("[data-audit-category-detail]")
            if "pairing_mismatch" in detail.get_text()
        )
        expected, actual = [
            json.loads(pre.get_text()) for pre in mismatch_detail.select("pre")
        ]
        self.assertEqual(expected, [[1, 4], [2, 3]])
        self.assertEqual(actual, [[1, 3], [2, 4]])

    def test_delete_report_removes_run_and_categories_but_keeps_task_log(self):
        link = RegistrationLink(
            name="Test Open",
            event_id="123",
            normalized_name="test open",
            updated_at=datetime(2026, 9, 1),
            link="internal:test-open",
        )
        task = BackgroundTask(task_type="bracket_audit", status="success")
        db.session.add_all([link, task])
        db.session.flush()
        run = BracketAuditRun(
            background_task_id=task.id,
            registration_link_id=link.id,
            tournament_id="123",
            tournament_name="Test Open",
            gi=True,
            status="complete",
        )
        category = BracketAuditCategory(
            run=run,
            category_url="https://example.test/categories/1",
            status="complete",
        )
        db.session.add_all([run, category])
        db.session.commit()
        run_id = run.id
        category_id = category.id
        task_id = task.id

        index = self.client.get("/bracket_audits")
        detail = self.client.get(f"/bracket_audits/{run_id}")
        delete_path = f"/bracket_audits/{run_id}/delete".encode()
        self.assertIn(delete_path, index.data)
        self.assertIn(delete_path, detail.data)

        response = self.client.post(f"/bracket_audits/{run_id}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/bracket_audits")
        db.session.expire_all()
        self.assertIsNone(db.session.get(BracketAuditRun, run_id))
        self.assertIsNone(db.session.get(BracketAuditCategory, category_id))
        self.assertIsNotNone(db.session.get(BackgroundTask, task_id))

    def test_delete_report_rejects_a_running_audit(self):
        task = BackgroundTask(task_type="bracket_audit", status="running")
        db.session.add(task)
        db.session.flush()
        run = BracketAuditRun(
            background_task_id=task.id,
            tournament_id="123",
            tournament_name="Test Open",
            gi=True,
            status="running",
        )
        db.session.add(run)
        db.session.commit()
        run_id = run.id

        response = self.client.post(f"/bracket_audits/{run_id}/delete")

        self.assertEqual(response.status_code, 409)
        self.assertIsNotNone(db.session.get(BracketAuditRun, run_id))

    def test_routes_require_admin_login(self):
        anonymous = self.admin_module.app.test_client()
        response = anonymous.get("/bracket_audits")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        response = anonymous.post("/bracket_audits/not-a-run/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
