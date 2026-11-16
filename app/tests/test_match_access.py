import os
import sys
import unittest
import importlib.util
from unittest.mock import Mock, patch

import requests
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask
from sqlalchemy import create_engine, inspect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from match_access import (
    BURST_REQUESTS,
    COOKIE_NAME,
    SESSION_UNITS,
    MatchAccessSession,
    configure_match_access,
)
from test_db import TestDbMixin


class MatchAccessTests(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.app = self.app_module.app
        self.saved_config = self.app.config.copy()
        self.app.config.update(
            MATCH_ACCESS_ENABLED=True,
            TURNSTILE_SECRET_KEY="test-secret",
            MATCH_ACCESS_SIGNING_KEY="s" * 32,
            TURNSTILE_HOSTNAMES={"jiujitsu.net", "www.jiujitsu.net"},
        )
        self.client = self.app.test_client()
        self.clock = patch("match_access.time", return_value=100000)
        self.clock.start()
        self.remote = patch("match_access.requests.post")
        self.verify = self.remote.start()
        self.photos = patch("routes.matches.get_s3_client", return_value=None)
        self.photos.start()
        self.verify.return_value = Mock(
            json=Mock(
                return_value={
                    "success": True,
                    "hostname": "jiujitsu.net",
                    "action": "match_access",
                }
            )
        )
        with self.app.app_context():
            MatchAccessSession.query.delete()
            db.session.commit()

    def tearDown(self):
        self.clock.stop()
        self.remote.stop()
        self.photos.stop()
        self.app.config.clear()
        self.app.config.update(self.saved_config)

    def grant(self):
        response = self.client.post("/api/access/verify", json={"token": "test-token"})
        self.assertEqual(response.status_code, 200)
        return response

    def test_missing_and_forged_cookies_block_before_match_query(self):
        for path in ("/api/matches?gi=true", "/api/matches/invalid/detail-events"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json["code"], "match_access_required")
        self.client.set_cookie(COOKIE_NAME, "forged")
        self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 403)

    def test_config_exposes_only_public_settings(self):
        response = self.client.get("/api/access/config")
        self.assertEqual(set(response.json), {"enabled", "siteKey"})
        self.assertNotIn("test-secret", response.get_data(as_text=True))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_success_issues_secure_cookie_and_allows_matches(self):
        response = self.grant()
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/api/"):
            self.assertIn(flag, cookie)
        self.verify.assert_called_once_with(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": "test-secret", "response": "test-token"},
            timeout=8,
        )
        self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 200)
        self.assertEqual(
            self.client.get("/api/matches/invalid/detail-events").status_code, 404
        )

    def test_bad_token_input_never_calls_cloudflare(self):
        for payload in (
            None,
            [],
            {},
            {"token": 42},
            {"token": ""},
            {"token": "x" * 2049},
        ):
            response = self.client.post("/api/access/verify", json=payload)
            self.assertEqual(response.status_code, 400)
        self.verify.assert_not_called()

    def test_verification_rejects_failure_wrong_hostname_and_action(self):
        for result in (
            {"success": False},
            {"success": True, "hostname": "attacker.example", "action": "match_access"},
            {"success": True, "hostname": "jiujitsu.net", "action": "other"},
            None,
        ):
            self.verify.return_value.json.return_value = result
            response = self.client.post("/api/access/verify", json={"token": "token"})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("Set-Cookie", response.headers)

    def test_cloudflare_outage_fails_closed(self):
        for failure in (requests.Timeout(), requests.HTTPError(), ValueError()):
            self.verify.side_effect = failure
            response = self.client.post("/api/access/verify", json={"token": "token"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("Set-Cookie", response.headers)

    def test_expired_or_deleted_session_requires_verification(self):
        for delete in (False, True):
            self.grant()
            with self.app.app_context():
                session = MatchAccessSession.query.one()
                if delete:
                    db.session.delete(session)
                else:
                    session.expires_at = 100000
                db.session.commit()
            response = self.client.get("/api/matches?gi=true")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json["code"], "match_access_required")
            with self.app.app_context():
                MatchAccessSession.query.delete()
                db.session.commit()

    def test_signature_expiry(self):
        self.grant()
        with patch("itsdangerous.timed.time.time", return_value=10**11):
            self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 403)

    def test_limits_survive_another_client_and_ip(self):
        self.grant()
        other_client = self.app.test_client()
        cookie = self.client.get_cookie(COOKIE_NAME, path="/api/")
        other_client.set_cookie(COOKIE_NAME, cookie.value, path="/api/")
        for i in range(BURST_REQUESTS):
            client = self.client if i % 2 else other_client
            self.assertEqual(client.get("/api/matches?gi=true").status_code, 200)
        response = other_client.get(
            "/api/matches?gi=true", headers={"CF-Connecting-IP": "192.0.2.99"}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["code"], "match_access_limited")
        self.assertEqual(response.headers["Retry-After"], "10")
        with patch("match_access.time", return_value=100010):
            self.assertEqual(other_client.get("/api/matches?gi=true").status_code, 200)

    def test_athlete_quota_renews_only_with_fresh_proof_and_revokes_old_cookie(self):
        self.grant()
        old_cookie = self.client.get_cookie(COOKIE_NAME, path="/api/").value
        scraper = self.app.test_client()
        scraper.set_cookie(COOKIE_NAME, old_cookie, path="/api/")
        with self.app.app_context():
            session = MatchAccessSession.query.one()
            session.units = SESSION_UNITS - 50
            db.session.commit()
        path = "/api/matches?gi=true&athlete_id=00000000-0000-0000-0000-000000000001"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["code"], "match_access_required")
        self.assertEqual(response.json["reason"], "quota_exhausted")
        # Merely posting the valid cookie cannot refresh the allowance.
        response = self.client.post("/api/access/verify", json={})
        self.assertEqual(response.status_code, 400)
        self.verify.assert_called_once()
        with self.app.app_context():
            self.assertEqual(MatchAccessSession.query.one().units, SESSION_UNITS - 50)
        # Failed Cloudflare verification must not revoke or refresh the session.
        self.verify.return_value.json.return_value = {"success": False}
        response = self.client.post("/api/access/verify", json={"token": "bad"})
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(MatchAccessSession.query.one().units, SESSION_UNITS - 50)
        self.verify.return_value.json.return_value = {
            "success": True,
            "hostname": "jiujitsu.net",
            "action": "match_access",
        }
        self.grant()
        self.assertNotEqual(
            old_cookie, self.client.get_cookie(COOKIE_NAME, path="/api/").value
        )
        with self.app.app_context():
            self.assertEqual(MatchAccessSession.query.one().units, 0)
        self.assertEqual(self.client.get(path).status_code, 200)
        # Even a smaller query cannot use the old cookie after rotation.
        response = scraper.get("/api/matches?gi=true")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["code"], "match_access_required")

    def test_exact_quota_boundary_requires_verification_on_next_request(self):
        self.grant()
        with self.app.app_context():
            session = MatchAccessSession.query.one()
            session.units = SESSION_UNITS - 12
            db.session.commit()
        self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 200)
        response = self.client.get("/api/matches?gi=true")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["reason"], "quota_exhausted")
        with self.app.app_context():
            self.assertEqual(MatchAccessSession.query.one().units, SESSION_UNITS)

    def test_fresh_proof_does_not_reset_burst_counter(self):
        self.grant()
        with self.app.app_context():
            session = MatchAccessSession.query.one()
            session.units = SESSION_UNITS
            session.burst_bucket = 100000 // 10
            session.burst_requests = BURST_REQUESTS
            db.session.commit()
        self.grant()
        response = self.client.get("/api/matches?gi=true")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["code"], "match_access_limited")
        with patch("match_access.time", return_value=100010):
            self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 200)

    def test_disabled_access_preserves_local_development(self):
        self.app.config["MATCH_ACCESS_ENABLED"] = False
        self.assertEqual(self.client.get("/api/matches?gi=true").status_code, 200)
        self.assertEqual(
            self.client.post("/api/access/verify", json={}).status_code, 200
        )
        self.verify.assert_not_called()

    def test_enabled_configuration_requires_secrets(self):
        with patch.dict(os.environ, {"MATCH_ACCESS_ENABLED": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TURNSTILE_SECRET_KEY"):
                configure_match_access(Flask(__name__))
        with patch.dict(
            os.environ,
            {
                "MATCH_ACCESS_ENABLED": "true",
                "TURNSTILE_SECRET_KEY": "secret",
                "MATCH_ACCESS_SIGNING_KEY": "short",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "SIGNING_KEY"):
                configure_match_access(Flask(__name__))

    def test_purge_only_deletes_expired_sessions(self):
        self.grant()
        with self.app.app_context():
            db.session.add(MatchAccessSession(id="expired", expires_at=99999))
            db.session.commit()
        with patch.object(self.app_module, "time", return_value=100000):
            result = self.app.test_cli_runner().invoke(
                args=["purge-expired-match-access"]
            )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Deleted 1", result.output)
        with self.app.app_context():
            self.assertEqual(MatchAccessSession.query.count(), 1)


class MatchAccessMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade(self):
        filename = os.path.join(
            os.path.dirname(__file__),
            "..",
            "migrations",
            "versions",
            "a3b5c7d9e1f2_add_match_access_sessions.py",
        )
        spec = importlib.util.spec_from_file_location("access_migration", filename)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()
                    columns = inspect(connection).get_columns("match_access_sessions")
                    self.assertEqual(
                        {column["name"] for column in columns},
                        set(MatchAccessSession.__table__.columns.keys()),
                    )
                    migration.downgrade()
                    self.assertFalse(
                        inspect(connection).has_table("match_access_sessions")
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
