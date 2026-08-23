import io
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

from PIL import Image
from sqlalchemy import event as sqlalchemy_event

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    AthleteRatingAverage,
    Division,
    Event,
    Match,
    MatchParticipant,
    Team,
)
from test_db import TestDbMixin


class HighlightsResearchApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        team = Team(name="Research Team", normalized_name="research team")
        other_team = Team(name="Other Team", normalized_name="other team")
        athlete = Athlete(
            name="Secret Athlete Name",
            normalized_name="secret athlete name",
            personal_name="Public Athlete",
            normalized_personal_name="public athlete",
            hide_full_name=True,
            slug="public-athlete",
            country="US",
            profile_image_saved_at=datetime.now(timezone.utc),
        )
        opponent = Athlete(
            name="Opponent Athlete",
            normalized_name="opponent athlete",
            slug="opponent-athlete",
            country="BR",
        )
        ambiguous = Athlete(
            name="Another Public Athlete",
            normalized_name="another public athlete",
            personal_name="Public Athlete",
            normalized_personal_name="public athlete",
            slug="public-athlete-two",
        )
        tournament = Event(
            name="Research Open 2026",
            normalized_name="research open 2026",
            slug="research-open-2026",
            ibjjf_id="research-open",
            medals_only=False,
        )
        division = Division(gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=LIGHT)
        db.session.add_all(
            [team, other_team, athlete, opponent, ambiguous, tournament, division]
        )
        db.session.flush()

        for index, happened_at in enumerate(
            [datetime(2026, 1, 2, 10, 0), datetime(2026, 1, 1, 10, 0)]
        ):
            match = Match(
                event_id=tournament.id,
                division_id=division.id,
                happened_at=happened_at,
                rated=True,
                video_link=f"https://www.youtube.com/watch?v=research{index:03d}",
                video_start_offset_seconds=100 + index,
                final_match_time_seconds=120 if index == 0 else 0,
                final_top_points=2,
                final_top_advantages=0,
                final_top_penalties=0,
                final_bottom_points=0,
                final_bottom_advantages=0,
                final_bottom_penalties=0,
            )
            db.session.add(match)
            db.session.flush()
            db.session.add_all(
                [
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athlete.id,
                        team_id=team.id if index == 0 else other_team.id,
                        seed=1,
                        red=True,
                        winner=True,
                        start_rating=1500,
                        end_rating=1510,
                        start_match_count=5,
                        end_match_count=6,
                        scoreboard_position="top",
                    ),
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=opponent.id,
                        team_id=other_team.id,
                        seed=2,
                        red=False,
                        winner=False,
                        start_rating=1490,
                        end_rating=1480,
                        start_match_count=5,
                        end_match_count=6,
                        scoreboard_position="bottom",
                    ),
                ]
            )

        db.session.add_all(
            [
                AthleteRatingAverage(
                    gender=MALE,
                    age=ADULT,
                    belt=BLACK,
                    gi=True,
                    weight=LIGHT,
                    avg_rating=1450,
                ),
                AthleteRating(
                    athlete_id=athlete.id,
                    gender=MALE,
                    age=ADULT,
                    belt=BLACK,
                    gi=True,
                    weight=LIGHT,
                    rating=1510,
                    match_happened_at=datetime(2026, 1, 2),
                    rank=1,
                    percentile=0.1,
                    match_count=6,
                    previous_rating=1500,
                    previous_rank=2,
                    previous_match_count=5,
                ),
            ]
        )
        db.session.commit()
        cls.athlete_id = athlete.id
        cls.event_id = tournament.id
        cls.match_id = Match.query.order_by(Match.happened_at.desc()).first().id

    def setUp(self):
        self.app_context = self.app_module.app.app_context()
        self.app_context.push()
        self.client = self.app_module.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_athlete_search_is_bounded_ambiguous_and_private(self):
        response = self.client.get("/api/highlights/v1/athletes?query=public&limit=10")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, payload["schema_version"])
        self.assertIn("as_of", payload)
        self.assertEqual(2, len(payload["athletes"]))
        result = next(
            row
            for row in payload["athletes"]
            if row["athlete_id"] == str(self.athlete_id)
        )
        self.assertEqual("Public Athlete", result["display_name"])
        self.assertEqual("Research Team", result["current_team"])
        self.assertTrue(result["photo"]["available"])
        self.assertTrue(result["ambiguity"]["multiple_results"])
        self.assertNotIn("Secret Athlete Name", response.get_data(as_text=True))

        hidden = self.client.get("/api/highlights/v1/athletes?query=secret%20athlete")
        self.assertEqual([], hidden.get_json()["athletes"])
        invalid = self.client.get("/api/highlights/v1/athletes?query=x&limit=999")
        self.assertEqual(400, invalid.status_code)
        self.assertEqual("invalid_query", invalid.get_json()["error"]["code"])

    @mock.patch("routes.highlights.load_livestream_links")
    @mock.patch("routes.highlights.load_linked_archive_video_links", return_value={})
    def test_profile_matches_match_rankings_and_events_contracts(
        self, _archive_links, livestream_links
    ):
        livestream_links.return_value = {
            "tournament_days": {},
            "live_streams": {},
            "flo_event_tags": {},
        }
        profile = self.client.get(
            f"/api/highlights/v1/athletes/{self.athlete_id}?gi=true"
        )
        self.assertEqual(200, profile.status_code)
        profile_json = profile.get_json()
        self.assertEqual("Public Athlete", profile_json["athlete"]["display_name"])
        self.assertEqual(1, profile_json["ranks"][0]["rank"])
        self.assertTrue(profile_json["athlete"]["photo"]["available"])

        matches = self.client.get(
            f"/api/highlights/v1/athletes/{self.athlete_id}/matches"
            "?gi=true&page=1&page_size=1"
        )
        self.assertEqual(200, matches.status_code)
        matches_json = matches.get_json()
        self.assertEqual(2, matches_json["pagination"]["total_items"])
        self.assertEqual(2, matches_json["pagination"]["total_pages"])
        self.assertEqual("Submission", matches_json["matches"][0]["result"]["method"])
        self.assertNotIn("Secret Athlete Name", matches.get_data(as_text=True))

        detail = self.client.get(f"/api/highlights/v1/matches/{self.match_id}")
        self.assertEqual(200, detail.status_code)
        self.assertEqual(str(self.match_id), detail.get_json()["match"]["match_id"])

        rankings = self.client.get(
            "/api/highlights/v1/rankings"
            f"?gender={MALE}&age={ADULT}&belt={BLACK}&gi=true&weight={LIGHT}"
        )
        self.assertEqual(200, rankings.status_code)
        ranking_json = rankings.get_json()
        self.assertEqual(str(self.athlete_id), ranking_json["rows"][0]["athlete_id"])
        self.assertEqual("Public Athlete", ranking_json["rows"][0]["display_name"])
        self.assertNotIn("Secret Athlete Name", rankings.get_data(as_text=True))

        events = self.client.get("/api/highlights/v1/events?query=research")
        self.assertEqual(200, events.status_code)
        self.assertEqual(str(self.event_id), events.get_json()["events"][0]["event_id"])
        event_detail = self.client.get(f"/api/highlights/v1/events/{self.event_id}")
        self.assertEqual(200, event_detail.status_code)
        self.assertTrue(event_detail.get_json()["event"]["gi"])

    def test_search_query_count_is_constant(self):
        engine = db.session.get_bind()
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        sqlalchemy_event.listen(engine, "before_cursor_execute", record)
        try:
            response = self.client.get(
                "/api/highlights/v1/athletes?query=public&limit=20"
            )
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)
        self.assertEqual(200, response.status_code)
        self.assertLessEqual(len(statements), 2)

        statements.clear()
        sqlalchemy_event.listen(engine, "before_cursor_execute", record)
        try:
            response = self.client.get(
                f"/api/highlights/v1/athletes/{self.athlete_id}?gi=true"
            )
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)
        self.assertEqual(200, response.status_code)
        normalized_statements = [
            " ".join(statement.split()) for statement in statements
        ]
        lazy_relationship_loads = [
            statement
            for statement in normalized_statements
            if any(
                f"FROM {table} WHERE {table}.id =" in statement
                for table in ("matches", "divisions", "teams")
            )
        ]
        self.assertEqual([], lazy_relationship_loads)

        statements.clear()
        sqlalchemy_event.listen(engine, "before_cursor_execute", record)
        try:
            response = self.client.get("/api/highlights/v1/events?query=research")
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)
        self.assertEqual(200, response.status_code)
        self.assertLessEqual(len(statements), 4)

        statements.clear()
        sqlalchemy_event.listen(engine, "before_cursor_execute", record)
        try:
            with mock.patch(
                "routes.highlights.load_linked_archive_video_links", return_value={}
            ), mock.patch(
                "routes.highlights.load_livestream_links",
                return_value={
                    "tournament_days": {},
                    "live_streams": {},
                    "flo_event_tags": {},
                },
            ):
                response = self.client.get(
                    f"/api/highlights/v1/athletes/{self.athlete_id}/matches"
                    "?gi=true&page_size=20"
                )
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)
        self.assertEqual(200, response.status_code)
        self.assertLessEqual(len(statements), 4)

    @mock.patch("routes.highlights.get_s3_client")
    def test_logical_asset_validates_and_caches_image(self, get_s3_client):
        image = Image.new("RGB", (4, 3), "red")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        get_s3_client.return_value.get_object.return_value = {
            "ContentType": "image/jpeg",
            "Body": io.BytesIO(buffer.getvalue()),
        }
        asset_ref = f"athlete-photo.{self.athlete_id}"
        response = self.client.get(f"/api/highlights/v1/assets/{asset_ref}")
        self.assertEqual(200, response.status_code)
        self.assertEqual("image/jpeg", response.content_type)
        self.assertIn("max-age", response.headers["Cache-Control"])
        self.assertEqual("4", response.headers["X-Image-Width"])
        self.assertIn("ETag", response.headers)

        png = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 100)).save(png, format="PNG")
        get_s3_client.return_value.get_object.return_value = {
            "ContentType": "image/png",
            "Body": io.BytesIO(png.getvalue()),
        }
        normalized = self.client.get(f"/api/highlights/v1/assets/{asset_ref}")
        self.assertEqual(200, normalized.status_code)
        self.assertEqual("image/jpeg", normalized.content_type)
        self.assertTrue(normalized.data.startswith(b"\xff\xd8\xff"))

        missing = self.client.get(
            f"/api/highlights/v1/assets/athlete-photo.{uuid.uuid4()}"
        )
        self.assertEqual(404, missing.status_code)

    def test_contract_rejects_unknown_fields_and_bad_pagination(self):
        unknown = self.client.get(
            "/api/highlights/v1/events?query=research&unexpected=true"
        )
        self.assertEqual(400, unknown.status_code)
        bad_page = self.client.get(
            f"/api/highlights/v1/athletes/{self.athlete_id}/matches"
            "?page=0&page_size=500"
        )
        self.assertEqual(400, bad_page.status_code)
        bad_rank = self.client.get(
            f"/api/highlights/v1/rankings?gender={MALE}&age={ADULT}"
            f"&belt={BLACK}&gi=maybe&weight={LIGHT}"
        )
        self.assertEqual(400, bad_rank.status_code)


if __name__ == "__main__":
    unittest.main()
