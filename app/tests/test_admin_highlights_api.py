import importlib
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import create_engine

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "admin")))

from constants import ADULT, BLACK, LIGHT, MALE  # noqa: E402
from extensions import db  # noqa: E402
from livestream_frame_text_scan import queue_text_scan  # noqa: E402
from models import (  # noqa: E402
    Athlete,
    Division,
    Event,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    LivestreamFrameTextScanSegment,
    Match,
    MatchParticipant,
    Team,
)
from test_db import TestDbMixin  # noqa: E402


class AdminHighlightsApiTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.app_context = self.app_module.app.app_context()
        self.app_context.push()
        LivestreamFrameTextEvent.query.delete()
        LivestreamFrameTextScanSegment.query.delete()
        LivestreamFrameTextScan.query.delete()
        LivestreamFrameCaptureSegment.query.delete()
        LivestreamFrameArchive.query.delete()
        MatchParticipant.query.delete()
        Match.query.delete()
        Athlete.query.delete()
        Team.query.delete()
        Division.query.delete()
        Event.query.delete()
        db.session.commit()
        self.admin_module = None
        self.admin_password = "admin"

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def _admin_client(self):
        if self.admin_module is None:
            self.admin_module = importlib.import_module("admin.app")
            db_path = os.path.join(self.temp_dir, "test.db")
            self.admin_module.app.config.update(
                TESTING=True,
                SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
                SQLALCHEMY_TRACK_MODIFICATIONS=False,
            )
            with self.admin_module.app.app_context():
                sqlalchemy_ext = self.admin_module.app.extensions.get("sqlalchemy")
                if (
                    sqlalchemy_ext
                    and getattr(sqlalchemy_ext, "engines", None) is not None
                ):
                    sqlalchemy_ext.engines[None] = create_engine(
                        f"sqlite:///{db_path}"
                    )
            self.admin_password = self.admin_module.ADMIN_PASSWORD
        return self.admin_module.app.test_client()

    def _create_linked_match(self, *, youtube_url, happened_at, final_match_time_seconds):
        event = Event(
            name=f"Test Open {uuid.uuid4().hex[:8]}",
            normalized_name="test open",
            slug=f"test-open-{uuid.uuid4().hex[:8]}",
            ibjjf_id=f"E-{uuid.uuid4().hex[:8]}",
        )
        division = Division(
            gi=True,
            gender=MALE,
            age=ADULT,
            belt=BLACK,
            weight=LIGHT,
        )
        top_athlete = Athlete(
            name="Top Athlete",
            normalized_name="top athlete",
            slug=f"top-athlete-{uuid.uuid4().hex[:8]}",
            country="us",
        )
        bottom_athlete = Athlete(
            name="Bottom Athlete",
            normalized_name="bottom athlete",
            slug=f"bottom-athlete-{uuid.uuid4().hex[:8]}",
            country="br",
        )
        top_team = Team(name="Top Team", normalized_name=f"top-team-{uuid.uuid4().hex[:8]}")
        bottom_team = Team(
            name="Bottom Team", normalized_name=f"bottom-team-{uuid.uuid4().hex[:8]}"
        )
        db.session.add_all(
            [event, division, top_athlete, bottom_athlete, top_team, bottom_team]
        )
        db.session.flush()

        match = Match(
            event_id=event.id,
            division_id=division.id,
            happened_at=happened_at,
            rated=True,
            match_location="Mat 1",
            video_link=youtube_url,
            final_match_time_seconds=final_match_time_seconds,
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
                    athlete_id=top_athlete.id,
                    team_id=top_team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1000,
                    end_rating=1010,
                    start_match_count=0,
                    end_match_count=1,
                    scoreboard_position="top",
                ),
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=bottom_athlete.id,
                    team_id=bottom_team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1000,
                    end_rating=990,
                    start_match_count=0,
                    end_match_count=1,
                    scoreboard_position="bottom",
                ),
            ]
        )

        video_id = uuid.uuid4().hex[:11]
        archive = LivestreamFrameArchive(
            youtube_video_id=video_id,
            canonical_url=youtube_url,
            s3_prefix=f"livestream-frames/{video_id}/",
            status="success",
            frame_rate=1.0,
            image_format="jpg",
        )
        db.session.add(archive)
        db.session.flush()

        capture_segment = LivestreamFrameCaptureSegment(
            archive_id=archive.id,
            start_second=0,
            end_second=300,
            status="success",
            uploaded_frame_count=300,
            last_uploaded_second=299,
            batch_s3_key=f"batch-{video_id}.tgz",
        )
        db.session.add(capture_segment)
        db.session.commit()

        queue_text_scan(db.session, archive, score_engine="none")
        db.session.flush()
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        scan_segment = LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id).one()

        return match, scan, scan_segment, capture_segment, archive

    def _attach_match_events(
        self,
        *,
        match,
        scan,
        scan_segment,
        capture_segment,
        start_second,
        end_second,
        running_timer="2:30",
        stopped_timer="2:23",
    ):
        db.session.add_all(
            [
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=scan.archive_id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=start_second,
                    timer_state="running",
                    timer_value=running_timer,
                    top_points=0,
                    bottom_points=0,
                ),
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=scan.archive_id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=end_second,
                    timer_state="stopped",
                    timer_value=stopped_timer,
                    top_points=2,
                    bottom_points=0,
                ),
            ]
        )

    def test_highlights_api_requires_existing_admin_password_auth(self):
        client = self._admin_client()

        unauthorized = client.get("/api/highlights/score-events?event_type=submission&days=7")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = client.get(
            "/api/highlights/score-events?event_type=submission&days=7",
            headers={"X-Admin-Password": self.admin_password},
        )
        self.assertEqual(authorized.status_code, 200)

    def test_highlights_submission_events_returns_expected_payload(self):
        match, scan, scan_segment, capture_segment, _archive = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=submission01",
            happened_at=datetime.utcnow() - timedelta(days=1),
            final_match_time_seconds=143,
        )
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=100,
            end_second=143,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=submission&days=7",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "submission")
        self.assertEqual(event["youtube_url"], "https://www.youtube.com/watch?v=submission01")
        self.assertEqual(event["video_offset_seconds"], 143)
        self.assertEqual(event["winner"], "Top Athlete")
        self.assertEqual(event["loser"], "Bottom Athlete")

    def test_highlights_submission_filters_by_adult_black_belt(self):
        included_match, included_scan, included_scan_segment, included_capture_segment, _archive = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=adultblack01",
            happened_at=datetime.utcnow() - timedelta(days=1),
            final_match_time_seconds=121,
        )
        self._attach_match_events(
            match=included_match,
            scan=included_scan,
            scan_segment=included_scan_segment,
            capture_segment=included_capture_segment,
            start_second=90,
            end_second=121,
        )

        excluded_match, excluded_scan, excluded_scan_segment, excluded_capture_segment, _archive = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=masterblack01",
            happened_at=datetime.utcnow() - timedelta(days=1),
            final_match_time_seconds=130,
        )
        excluded_match.division.age = "Master 1"
        self._attach_match_events(
            match=excluded_match,
            scan=excluded_scan,
            scan_segment=excluded_scan_segment,
            capture_segment=excluded_capture_segment,
            start_second=100,
            end_second=130,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=submission&days=9&gi=true&age=adult&belt=black",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(event["youtube_url"], "https://www.youtube.com/watch?v=adultblack01")
        self.assertEqual(str(event["division_age"]).lower(), "adult")
        self.assertEqual(str(event["division_belt"]).lower(), "black")
        self.assertTrue(event["division_gi"])

    def test_highlights_score_events_can_filter_for_two_point_scores(self):
        match, scan, scan_segment, capture_segment, _archive = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=points000001",
            happened_at=datetime.utcnow() - timedelta(days=1),
            final_match_time_seconds=0,
        )

        db.session.add_all(
            [
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=scan.archive_id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=30,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    bottom_points=0,
                ),
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=scan.archive_id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=50,
                    timer_state="running",
                    timer_value="4:40",
                    top_points=2,
                    top_advantages=0,
                    bottom_points=0,
                ),
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=scan.archive_id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=60,
                    timer_state="running",
                    timer_value="4:30",
                    top_points=2,
                    top_advantages=1,
                    bottom_points=0,
                ),
            ]
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=score&days=3&score_category=points&score_delta=2",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "score")
        self.assertEqual(event["score_category"], "points")
        self.assertEqual(event["score_delta"], 2)
        self.assertEqual(event["action_athlete_name"], "Top")
        self.assertEqual(event["youtube_url"], "https://www.youtube.com/watch?v=points000001")


if __name__ == "__main__":
    unittest.main()
