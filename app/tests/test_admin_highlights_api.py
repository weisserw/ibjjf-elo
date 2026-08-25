import importlib
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "admin")))

from constants import ADULT, BLACK, FEMALE, LIGHT, MALE, MASTER_1  # noqa: E402
from extensions import db  # noqa: E402
from livestream_frame_text_scan import queue_text_scan  # noqa: E402
from normalize import normalize  # noqa: E402
from models import (  # noqa: E402
    Athlete,
    AthleteRating,
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
        AthleteRating.query.delete()
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
                    sqlalchemy_ext.engines[None] = create_engine(f"sqlite:///{db_path}")
            self.admin_password = self.admin_module.ADMIN_PASSWORD
        return self.admin_module.app.test_client()

    def _create_linked_match(
        self, *, youtube_url, happened_at, final_match_time_seconds
    ):
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
        top_team = Team(
            name="Top Team", normalized_name=f"top-team-{uuid.uuid4().hex[:8]}"
        )
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
        scan_segment = LivestreamFrameTextScanSegment.query.filter_by(
            scan_id=scan.id
        ).one()

        return match, scan, scan_segment, capture_segment, archive

    def _add_rating(self, match, *, percentile, age=ADULT):
        athlete = next(
            participant.athlete for participant in match.participants if participant.red
        )
        db.session.add(
            AthleteRating(
                athlete_id=athlete.id,
                gender=match.division.gender,
                age=age,
                belt=BLACK,
                gi=match.division.gi,
                weight=LIGHT,
                rating=1200,
                match_happened_at=match.happened_at,
                rank=1,
                percentile=percentile,
                match_count=10,
            )
        )

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

        unauthorized = client.get(
            "/api/highlights/score-events?event_type=submission&days=7"
        )
        self.assertEqual(unauthorized.status_code, 401)

        authorized = client.get(
            "/api/highlights/score-events?event_type=submission&days=7",
            headers={"X-Admin-Password": self.admin_password},
        )
        self.assertEqual(authorized.status_code, 200)

    def test_highlights_submission_events_returns_expected_payload(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=submission01",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=143,
            )
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
        self.assertEqual(
            event["youtube_url"], "https://www.youtube.com/watch?v=submission01"
        )
        self.assertEqual(event["video_offset_seconds"], 143)
        self.assertEqual(event["video_lead_seconds"], 15)
        self.assertEqual(event["winner"], "Top Athlete")
        self.assertEqual(event["loser"], "Bottom Athlete")

    def test_highlights_match_start_defaults_to_all_time_and_thirty_results(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=matchstart01",
                happened_at=datetime.utcnow() - timedelta(days=365),
                final_match_time_seconds=143,
            )
        )
        match.video_start_offset_seconds = 100
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=100,
            end_second=143,
            running_timer="5:00",
        )
        db.session.commit()

        query_class = type(Match.query)
        original_yield_per = query_class.yield_per
        yield_sizes = []

        def recording_yield_per(query, count):
            yield_sizes.append(count)
            return original_yield_per(query, count)

        with patch.object(query_class, "yield_per", recording_yield_per):
            response = self._admin_client().get(
                "/api/highlights/score-events?event_type=match_start",
                headers={"X-Admin-Password": self.admin_password},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(yield_sizes, [100])
        payload = response.get_json()
        self.assertEqual(payload["filters"]["days"], None)
        self.assertEqual(payload["filters"]["limit"], 30)
        self.assertEqual(payload["filters"]["gi"], True)
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "match_start")
        self.assertEqual(event["match_time"], "5:00")
        self.assertEqual(event["video_offset_seconds"], 100)
        self.assertEqual(event["video_lead_seconds"], 10)

        match.division.gi = False
        db.session.commit()
        all_response = self._admin_client().get(
            "/api/highlights/score-events?event_type=match_start&gi=all",
            headers={"X-Admin-Password": self.admin_password},
        )
        self.assertEqual(all_response.get_json()["filters"]["gi"], None)
        self.assertEqual(all_response.get_json()["count"], 1)

    def test_highlights_submission_filters_by_adult_black_belt(self):
        (
            included_match,
            included_scan,
            included_scan_segment,
            included_capture_segment,
            _archive,
        ) = self._create_linked_match(
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

        (
            excluded_match,
            excluded_scan,
            excluded_scan_segment,
            excluded_capture_segment,
            _archive,
        ) = self._create_linked_match(
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
        self.assertEqual(
            event["youtube_url"], "https://www.youtube.com/watch?v=adultblack01"
        )
        self.assertEqual(str(event["division_age"]).lower(), "adult")
        self.assertEqual(str(event["division_belt"]).lower(), "black")
        self.assertTrue(event["division_gi"])

    def test_highlights_submission_filters_by_event_name(self):
        (
            included_match,
            included_scan,
            included_scan_segment,
            included_capture_segment,
            _archive,
        ) = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=eventname001",
            happened_at=datetime.utcnow() - timedelta(days=2),
            final_match_time_seconds=111,
        )
        included_match.event.name = "IBJJF Worlds 2026"
        included_match.event.normalized_name = normalize(included_match.event.name)
        self._attach_match_events(
            match=included_match,
            scan=included_scan,
            scan_segment=included_scan_segment,
            capture_segment=included_capture_segment,
            start_second=80,
            end_second=111,
        )

        (
            excluded_match,
            excluded_scan,
            excluded_scan_segment,
            excluded_capture_segment,
            _archive,
        ) = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=eventname002",
            happened_at=datetime.utcnow() - timedelta(days=2),
            final_match_time_seconds=119,
        )
        excluded_match.event.name = "IBJJF Brasileiros 2026"
        excluded_match.event.normalized_name = normalize(excluded_match.event.name)
        self._attach_match_events(
            match=excluded_match,
            scan=excluded_scan,
            scan_segment=excluded_scan_segment,
            capture_segment=excluded_capture_segment,
            start_second=88,
            end_second=119,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=submission&days=9&event_name=IBJJF%20Worlds%202026",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(
            event["youtube_url"], "https://www.youtube.com/watch?v=eventname001"
        )
        self.assertEqual(event["event_name"], "IBJJF Worlds 2026")

    def test_highlights_submission_event_name_filter_is_exact(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=eventname003",
                happened_at=datetime.utcnow() - timedelta(days=2),
                final_match_time_seconds=111,
            )
        )
        match.event.name = "IBJJF Worlds 2026"
        match.event.normalized_name = normalize(match.event.name)
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=80,
            end_second=111,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=submission&days=9&event_name=worlds",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 0)

    def test_highlights_submission_results_are_ordered_by_happened_at(self):
        earlier_match, earlier_scan, earlier_segment, earlier_capture, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=ordered001",
                happened_at=datetime.utcnow() - timedelta(days=2),
                final_match_time_seconds=111,
            )
        )
        earlier_match.event.name = "IBJJF Worlds 2026"
        earlier_match.event.normalized_name = normalize(earlier_match.event.name)
        self._attach_match_events(
            match=earlier_match,
            scan=earlier_scan,
            scan_segment=earlier_segment,
            capture_segment=earlier_capture,
            start_second=80,
            end_second=111,
        )

        later_match, later_scan, later_segment, later_capture, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=ordered002",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=125,
            )
        )
        later_match.event.name = "IBJJF Worlds 2026"
        later_match.event.normalized_name = normalize(later_match.event.name)
        self._attach_match_events(
            match=later_match,
            scan=later_scan,
            scan_segment=later_segment,
            capture_segment=later_capture,
            start_second=90,
            end_second=125,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?event_type=submission&days=9&event_name=IBJJF%20Worlds%202026",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        happened_ats = [event["happened_at"] for event in payload["events"]]
        self.assertEqual(happened_ats, sorted(happened_ats))

    def test_highlights_score_events_can_filter_for_two_point_scores(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=points000001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=0,
            )
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
        self.assertEqual(event["video_lead_seconds"], 15)
        self.assertEqual(event["action_athlete_name"], "Top")
        self.assertEqual(
            event["youtube_url"], "https://www.youtube.com/watch?v=points000001"
        )

    def test_highlights_decision_and_all_event_types(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=decision001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=0,
            )
        )
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=30,
            end_second=90,
            running_timer="1:00",
            stopped_timer="0:00",
        )

        submission_match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=allsubmit01",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=45,
            )
        )
        self._attach_match_events(
            match=submission_match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=20,
            end_second=65,
            running_timer="1:00",
            stopped_timer="0:45",
        )
        db.session.commit()

        client = self._admin_client()
        headers = {"X-Admin-Password": self.admin_password}
        decision_response = client.get(
            "/api/highlights/score-events?event_type=decision&days=3",
            headers=headers,
        )
        all_response = client.get(
            "/api/highlights/score-events?event_type=all&days=3",
            headers=headers,
        )

        self.assertEqual(decision_response.status_code, 200)
        decision_payload = decision_response.get_json()
        self.assertEqual(decision_payload["count"], 1)
        self.assertEqual(decision_payload["events"][0]["event_type"], "decision")
        self.assertEqual(decision_payload["events"][0]["match_time"], "0:00")
        self.assertEqual(decision_payload["events"][0]["ending_method"], "points")

        self.assertEqual(all_response.status_code, 200)
        all_payload = all_response.get_json()
        self.assertEqual(
            {"decision", "score", "submission"},
            {event["event_type"] for event in all_payload["events"]},
        )

    def test_highlights_dq_uses_final_match_detail_video_window(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=dqevent00001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=30,
            )
        )
        MatchParticipant.query.filter_by(match_id=match.id, red=False).one().note = (
            "Disqualified by technical desc."
        )
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=30,
            end_second=90,
            running_timer="1:00",
            stopped_timer="0:30",
        )

        ordinary_match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=notdqevent01",
                happened_at=datetime.utcnow(),
                final_match_time_seconds=30,
            )
        )
        self._attach_match_events(
            match=ordinary_match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=15,
            end_second=45,
            running_timer="1:00",
            stopped_timer="0:30",
        )

        unlinked_match, _scan, _segment, _capture, _archive = self._create_linked_match(
            youtube_url="https://www.youtube.com/watch?v=dqnoscores01",
            happened_at=datetime.utcnow() - timedelta(days=1),
            final_match_time_seconds=30,
        )
        MatchParticipant.query.filter_by(
            match_id=unlinked_match.id, red=False
        ).one().note = "Disqualified by disciplinary desc."
        db.session.commit()

        client = self._admin_client()
        with patch.object(
            self.admin_module,
            "build_match_detail_payload",
            wraps=self.admin_module.build_match_detail_payload,
        ) as build_payload:
            response = client.get(
                "/api/highlights/score-events?event_type=dq&days=3",
                headers={"X-Admin-Password": self.admin_password},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [match.id],
            [call.args[0].id for call in build_payload.call_args_list],
        )
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        event = payload["events"][0]
        self.assertEqual(event["event_type"], "dq")
        self.assertEqual(event["ending_method"], "DQ")
        self.assertEqual(event["video_offset_seconds"], 90)
        self.assertEqual(event["video_lead_seconds"], 10)
        self.assertEqual(
            event["youtube_url"],
            "https://www.youtube.com/watch?v=dqevent00001",
        )

    def test_highlights_athlete_filter_uses_exact_full_name_not_personal_name(self):
        match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=athlete0001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        athlete = next(
            participant.athlete for participant in match.participants if participant.red
        )
        athlete.name = "Gabrieli Pessanha"
        athlete.normalized_name = "gabrieli pessanha"
        athlete.personal_name = "Gabi"
        athlete.normalized_personal_name = "gabi"
        self._attach_match_events(
            match=match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=80,
            end_second=120,
        )
        db.session.commit()

        client = self._admin_client()
        headers = {"X-Admin-Password": self.admin_password}
        exact = client.get(
            "/api/highlights/score-events?athlete_name=GABRIELI%20PESSANHA",
            headers=headers,
        )
        personal = client.get(
            "/api/highlights/score-events?days=3&athlete_name=Gabi",
            headers=headers,
        )
        partial = client.get(
            "/api/highlights/score-events?days=3&athlete_name=Gabrieli",
            headers=headers,
        )

        self.assertEqual(exact.get_json()["count"], 1)
        self.assertEqual(personal.get_json()["count"], 0)
        self.assertEqual(partial.get_json()["count"], 0)

    def test_highlights_athlete_id_filter_is_exact_and_validated(self):
        selected, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=athleteid01",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        self._attach_match_events(
            match=selected,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=80,
            end_second=120,
        )
        other, other_scan, other_scan_segment, other_capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=athleteid02",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        self._attach_match_events(
            match=other,
            scan=other_scan,
            scan_segment=other_scan_segment,
            capture_segment=other_capture_segment,
            start_second=140,
            end_second=180,
        )
        athlete_id = next(
            participant.athlete_id
            for participant in selected.participants
            if participant.red
        )
        db.session.commit()

        client = self._admin_client()
        headers = {"X-Admin-Password": self.admin_password}
        exact = client.get(
            f"/api/highlights/score-events?athlete_id={athlete_id}",
            headers=headers,
        )
        invalid = client.get(
            "/api/highlights/score-events?athlete_id=athlete_01",
            headers=headers,
        )

        self.assertEqual(exact.status_code, 200)
        payload = exact.get_json()
        self.assertEqual(payload["filters"]["athlete_id"], str(athlete_id))
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["match_id"], str(selected.id))
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "athlete_id must be a UUID")

    def test_highlights_match_id_filter_is_exact_and_validated(self):
        selected, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=matchid0001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        self._attach_match_events(
            match=selected,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=80,
            end_second=120,
        )
        other, other_scan, other_scan_segment, other_capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=matchid0002",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        self._attach_match_events(
            match=other,
            scan=other_scan,
            scan_segment=other_scan_segment,
            capture_segment=other_capture_segment,
            start_second=80,
            end_second=120,
        )
        db.session.commit()

        client = self._admin_client()
        headers = {"X-Admin-Password": self.admin_password}
        exact = client.get(
            f"/api/highlights/score-events?event_type=all&match_id={selected.id}",
            headers=headers,
        )
        invalid = client.get(
            "/api/highlights/score-events?match_id=match_01",
            headers=headers,
        )

        self.assertEqual(exact.status_code, 200)
        self.assertGreater(exact.get_json()["count"], 0)
        self.assertTrue(
            all(
                row["match_id"] == str(selected.id)
                for row in exact.get_json()["events"]
            )
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "match_id must be a UUID")

    def test_highlights_gender_filter_is_exact(self):
        female_match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=female00001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=120,
            )
        )
        female_match.division.gender = FEMALE
        self._attach_match_events(
            match=female_match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=80,
            end_second=120,
        )

        male_match, scan, scan_segment, capture_segment, _archive = (
            self._create_linked_match(
                youtube_url="https://www.youtube.com/watch?v=male0000001",
                happened_at=datetime.utcnow() - timedelta(days=1),
                final_match_time_seconds=110,
            )
        )
        self._attach_match_events(
            match=male_match,
            scan=scan,
            scan_segment=scan_segment,
            capture_segment=capture_segment,
            start_second=70,
            end_second=110,
        )
        db.session.commit()

        client = self._admin_client()
        response = client.get(
            "/api/highlights/score-events?days=3&gender=female",
            headers={"X-Admin-Password": self.admin_password},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["division_gender"], FEMALE)

    def test_highlights_elite_filter_uses_non_masters_badge_tiers(self):
        cases = (
            ("tier3", 0.09, ADULT),
            ("tier2", 0.04, ADULT),
            ("tier1", 0.01, ADULT),
            ("masters", 0.001, MASTER_1),
            ("boundary", 0.10, ADULT),
        )
        for index, (_name, percentile, rating_age) in enumerate(cases):
            match, scan, scan_segment, capture_segment, _archive = (
                self._create_linked_match(
                    youtube_url=f"https://www.youtube.com/watch?v=elite{index:06d}",
                    happened_at=datetime.utcnow() - timedelta(days=1),
                    final_match_time_seconds=100 + index,
                )
            )
            self._add_rating(match, percentile=percentile, age=rating_age)
            self._attach_match_events(
                match=match,
                scan=scan,
                scan_segment=scan_segment,
                capture_segment=capture_segment,
                start_second=60,
                end_second=100 + index,
                stopped_timer=f"1:{40 - index:02d}",
            )
        db.session.commit()

        client = self._admin_client()
        headers = {"X-Admin-Password": self.admin_password}
        expected_counts = {"tier3": 3, "tier2": 2, "tier1": 1}
        for elite, expected_count in expected_counts.items():
            with self.subTest(elite=elite):
                response = client.get(
                    f"/api/highlights/score-events?days=3&elite={elite}",
                    headers=headers,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["count"], expected_count)


if __name__ == "__main__":
    unittest.main()
