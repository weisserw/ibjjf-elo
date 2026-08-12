import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from models import (
    Athlete,
    Division,
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    LivestreamFrameTextScanSegment,
    Match,
    MatchParticipant,
    Team,
)
from site_statistics import get_covered_match_count, refresh_covered_match_count
from livestreams import load_linked_archive_video_links
from test_db import TestDbMixin


class SiteStatisticsTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        event = Event(
            ibjjf_id="event-1",
            name="Test Event",
            normalized_name="test event",
            slug="test-event",
        )
        division = Division(
            gi=True,
            gender="Male",
            age="Adult",
            belt="Black",
            weight="Light",
        )
        athletes = [
            Athlete(
                ibjjf_id=f"athlete-{index}",
                name=name,
                normalized_name=name.lower(),
                slug=name.lower().replace(" ", "-"),
            )
            for index, name in enumerate(("First Athlete", "Second Athlete"), 1)
        ]
        teams = [
            Team(name=f"Team {index}", normalized_name=f"team {index}")
            for index in (1, 2)
        ]
        db.session.add_all([event, division, *athletes, *teams])
        db.session.flush()

        db.session.add_all(
            [
                LiveStream(
                    event_id=event.ibjjf_id,
                    platform="youtube",
                    mat_number=1,
                    day_number=1,
                    start_hour=9,
                    start_minute=0,
                    start_seconds=0,
                    end_hour=12,
                    end_minute=0,
                    drift_factor=1.0,
                    hide_all=False,
                    link="https://www.youtube.com/watch?v=stream123",
                ),
                LiveStream(
                    event_id=event.ibjjf_id,
                    platform="youtube",
                    mat_number=2,
                    day_number=1,
                    start_hour=9,
                    start_minute=0,
                    start_seconds=0,
                    end_hour=12,
                    end_minute=0,
                    drift_factor=1.0,
                    hide_all=True,
                    link="https://www.youtube.com/watch?v=hidden123",
                ),
            ]
        )

        def add_match(hour, minute, mat, video_link=None, note=None):
            match = Match(
                happened_at=datetime(2026, 1, 10, hour, minute),
                event_id=event.id,
                division_id=division.id,
                rated=True,
                match_location=f"Mat {mat}" if mat is not None else None,
                video_link=video_link,
            )
            db.session.add(match)
            db.session.flush()
            db.session.add_all(
                [
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athletes[0].id,
                        team_id=teams[0].id,
                        seed=1,
                        red=False,
                        winner=True,
                        note=note,
                        start_rating=1500,
                        end_rating=1510,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athletes[1].id,
                        team_id=teams[1].id,
                        seed=2,
                        red=True,
                        winner=False,
                        start_rating=1500,
                        end_rating=1490,
                        start_match_count=1,
                        end_match_count=2,
                    ),
                ]
            )
            return match

        archive_resources = {}

        def link_match_to_archive(match, youtube_video_id):
            existing = archive_resources.get(youtube_video_id)
            if existing:
                archive, capture_segment, scan, scan_segment, event_index = existing
                archive_resources[youtube_video_id] = (
                    archive,
                    capture_segment,
                    scan,
                    scan_segment,
                    event_index + 1,
                )
                db.session.add(
                    LivestreamFrameTextEvent(
                        scan_id=scan.id,
                        archive_id=archive.id,
                        match_id=match.id,
                        scan_segment_id=scan_segment.id,
                        capture_segment_id=capture_segment.id,
                        frame_second=100 + event_index,
                    )
                )
                return

            archive = LivestreamFrameArchive(
                youtube_video_id=youtube_video_id,
                canonical_url=(f"https://www.youtube.com/watch?v={youtube_video_id}"),
                s3_prefix=f"livestream-frames/{youtube_video_id}/",
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
                sampled_frame_count=300,
            )
            scan = LivestreamFrameTextScan(
                archive_id=archive.id,
                status="success",
                total_segment_count=1,
                processed_segment_count=1,
            )
            db.session.add_all([capture_segment, scan])
            db.session.flush()
            scan_segment = LivestreamFrameTextScanSegment(
                scan_id=scan.id,
                archive_id=archive.id,
                capture_segment_id=capture_segment.id,
                start_second=0,
                end_second=300,
                status="success",
            )
            db.session.add(scan_segment)
            db.session.flush()
            archive_resources[youtube_video_id] = (
                archive,
                capture_segment,
                scan,
                scan_segment,
                1,
            )
            db.session.add(
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=archive.id,
                    match_id=match.id,
                    scan_segment_id=scan_segment.id,
                    capture_segment_id=capture_segment.id,
                    frame_second=100,
                )
            )

        add_match(10, 0, 1)
        add_match(10, 0, 2)
        add_match(10, 30, 1, video_link="NONE")
        add_match(14, 0, 3, video_link="https://youtu.be/direct123")
        add_match(10, 45, 1, video_link="https://www.flograppling.com/events/test")
        add_match(11, 0, 1, note="Disqualified by no show")
        add_match(13, 0, 3)
        matless_linked_match = add_match(8, 0, None)
        matless_linked_match.video_start_offset_seconds = 321
        hidden_matless_linked_match = add_match(8, 10, None)
        suppressed_matless_linked_match = add_match(8, 20, None, video_link="NONE")
        link_match_to_archive(matless_linked_match, "stream123")
        link_match_to_archive(hidden_matless_linked_match, "hidden123")
        link_match_to_archive(suppressed_matless_linked_match, "stream123")

        refresh_covered_match_count(db.session)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_refresh_counts_only_visible_youtube_match_links(self):
        with self.app_module.app.app_context():
            self.assertEqual(get_covered_match_count(db.session), 3)
            self.assertEqual(refresh_covered_match_count(db.session), 3)

    def test_site_statistics_api_returns_cached_count(self):
        response = self.client.get("/api/site-statistics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"coveredMatchCount": 3})

    def test_visible_ocr_archive_link_includes_match_video_offset(self):
        with self.app_module.app.app_context():
            match = Match.query.filter_by(
                match_location=None,
                video_start_offset_seconds=321,
            ).one()

            self.assertEqual(
                load_linked_archive_video_links(db.session, [match.id]),
                {match.id: ("https://www.youtube.com/watch?v=stream123&t=321s")},
            )


if __name__ == "__main__":
    unittest.main()
