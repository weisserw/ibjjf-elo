import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from extensions import db  # noqa: E402
from models import (  # noqa: E402
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameOcrReading,
)
from test_db import TestDbMixin  # noqa: E402
from youtube_utils import (  # noqa: E402
    canonical_youtube_url,
    extract_youtube_video_id,
    offset_from_url,
    strip_offset_from_url,
)

import archive_livestream_frames as runner  # noqa: E402
import livestream_frame_archive as archive_lib  # noqa: E402


class ArchiveLivestreamFramesOptionsTestCase(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(runner._format_duration(None), "unknown")
        self.assertEqual(runner._format_duration(65), "1m05s")
        self.assertEqual(runner._format_duration(3661), "1h01m01s")

    def test_yt_dlp_options_enable_node_ejs_defaults(self):
        options = runner._yt_dlp_options(
            "best",
            "node",
            ["ejs:github"],
        )

        self.assertEqual(options["format"], "best")
        self.assertEqual(options["js_runtimes"], {"node": {}})
        self.assertEqual(options["remote_components"], ["ejs:github"])

    def test_yt_dlp_options_parse_runtime_path(self):
        options = runner._yt_dlp_options(
            "best",
            "node:/usr/local/bin/node",
            ["ejs:github"],
        )

        self.assertEqual(
            options["js_runtimes"],
            {"node": {"path": "/usr/local/bin/node"}},
        )

    def test_ffmpeg_extract_command_can_include_progress_output(self):
        command = runner._ffmpeg_extract_command(
            "https://example.com/video",
            60,
            120,
            1.0,
            2,
            Path("/tmp/frames"),
            progress=True,
        )

        self.assertIn("-progress", command)
        self.assertIn("pipe:1", command)
        self.assertIn("-nostats", command)
        self.assertEqual(command[-1], "/tmp/frames/%06d.jpg")

    def test_ocr_max_frames_caps_extraction_duration(self):
        self.assertEqual(runner.extraction_duration_for_ocr(3600, 1.0, 60), 60)
        self.assertEqual(runner.extraction_duration_for_ocr(3600, 2.0, 60), 30)
        self.assertEqual(runner.extraction_duration_for_ocr(30, 1.0, 60), 30)
        self.assertEqual(runner.extraction_duration_for_ocr(3600, 1.0, None), 3600)


class YoutubeUtilsTestCase(unittest.TestCase):
    def test_extract_youtube_video_id_from_watch_url(self):
        self.assertEqual(
            extract_youtube_video_id(
                "https://www.youtube.com/watch?v=HxZSos1k_MA&t=1175s&foo=bar"
            ),
            "HxZSos1k_MA",
        )

    def test_extract_youtube_video_id_from_short_url(self):
        self.assertEqual(
            extract_youtube_video_id("https://youtu.be/XtUY5re03CA?start=12"),
            "XtUY5re03CA",
        )

    def test_offset_helpers(self):
        url = "https://www.youtube.com/watch?v=HxZSos1k_MA&t=1h2m3s#t=10"
        self.assertEqual(offset_from_url(url), 3723)
        self.assertEqual(
            strip_offset_from_url(url),
            "https://www.youtube.com/watch?v=HxZSos1k_MA",
        )

    def test_canonical_youtube_url(self):
        self.assertEqual(
            canonical_youtube_url("HxZSos1k_MA"),
            "https://www.youtube.com/watch?v=HxZSos1k_MA",
        )


class LivestreamFrameArchiveDbTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        event = Event(
            ibjjf_id="E1",
            name="Test Open 2026",
            normalized_name="test open 2026",
            slug="test-open-2026",
        )
        db.session.add(event)
        db.session.add(
            LiveStream(
                event_id="E1",
                platform="youtube",
                mat_number=1,
                day_number=1,
                start_hour=9,
                start_minute=30,
                start_seconds=0,
                end_hour=18,
                end_minute=0,
                drift_factor=1.0,
                hide_all=False,
                link="https://www.youtube.com/watch?v=HxZSos1k_MA&t=10s",
            )
        )
        db.session.add(
            LiveStream(
                event_id="E1",
                platform="youtube",
                mat_number=2,
                day_number=1,
                start_hour=9,
                start_minute=30,
                start_seconds=0,
                end_hour=18,
                end_minute=0,
                drift_factor=1.0,
                hide_all=False,
                link="https://youtu.be/HxZSos1k_MA?start=20",
            )
        )
        db.session.add(
            LiveStream(
                event_id="E1",
                platform="flo",
                mat_number=3,
                day_number=1,
                start_hour=9,
                start_minute=30,
                start_seconds=0,
                end_hour=18,
                end_minute=0,
                drift_factor=1.0,
                hide_all=False,
                link="https://example.com/not-youtube",
            )
        )
        db.session.commit()

    def setUp(self):
        self.app_context = self.app_module.app.app_context()
        self.app_context.push()
        LivestreamFrameOcrReading.query.delete()
        LivestreamFrameCaptureSegment.query.delete()
        LivestreamFrameArchive.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_sync_archives_from_livestreams_is_unique_and_idempotent(self):
        result = archive_lib.sync_archives_from_livestreams(db.session)
        db.session.commit()
        self.assertEqual(result, {"created": 1, "discovered": 1})

        result = archive_lib.sync_archives_from_livestreams(db.session)
        db.session.commit()
        self.assertEqual(result, {"created": 0, "discovered": 1})
        archive = LivestreamFrameArchive.query.one()
        self.assertEqual(archive.youtube_video_id, "HxZSos1k_MA")
        self.assertEqual(
            archive.canonical_url,
            "https://www.youtube.com/watch?v=HxZSos1k_MA",
        )

    def test_discovery_keeps_multiple_livestream_rows(self):
        usages = archive_lib.discover_livestream_usages(db.session)
        self.assertEqual(len(usages["HxZSos1k_MA"]), 2)
        self.assertEqual(usages["HxZSos1k_MA"][0].event_name, "Test Open 2026")

    def test_queue_archive_segments_for_known_duration(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.duration_seconds = 1201
        archive_lib.queue_archive_capture(db.session, archive, segment_seconds=600)
        db.session.commit()

        segments = LivestreamFrameCaptureSegment.query.order_by(
            LivestreamFrameCaptureSegment.start_second
        ).all()
        self.assertEqual(
            [(segment.start_second, segment.end_second) for segment in segments],
            [(0, 600), (600, 1200), (1200, 1201)],
        )
        self.assertEqual(archive.expected_frame_count, 1201)

    def test_queue_archive_segments_fills_gap_after_segment_size_change(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.duration_seconds = 7200
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="success",
                processed_frame_count=600,
                last_processed_second=599,
                finished_at=datetime.utcnow(),
            )
        )
        db.session.commit()

        archive_lib.queue_archive_capture(db.session, archive, segment_seconds=3600)
        db.session.commit()

        segments = LivestreamFrameCaptureSegment.query.order_by(
            LivestreamFrameCaptureSegment.start_second
        ).all()
        self.assertEqual(
            [(segment.start_second, segment.end_second) for segment in segments],
            [(0, 600), (600, 3600), (3600, 7200)],
        )

    def test_recompute_archive_status_from_segments(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="success",
                processed_frame_count=600,
                last_processed_second=599,
                finished_at=datetime.utcnow(),
            )
        )
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=600,
                end_second=1200,
                status="error",
                processed_frame_count=10,
                last_processed_second=609,
                last_error="boom",
                finished_at=datetime.utcnow(),
            )
        )
        archive_lib.recompute_archive_status(db.session, archive)
        self.assertEqual(archive.status, "partial")
        self.assertEqual(archive.processed_frame_count, 600)
        self.assertEqual(archive.last_processed_second, 599)

    def test_claim_next_segment_marks_running(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive_lib.queue_archive_capture(db.session, archive)
        db.session.commit()

        segment = archive_lib.claim_next_segment(db.session)
        self.assertIsNotNone(segment)
        self.assertEqual(segment.status, "running")
        self.assertEqual(segment.attempt_count, 1)
        self.assertEqual(segment.archive.status, "running")

    def test_upsert_ocr_reading_updates_existing_frame_second(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        db.session.flush()
        segment = LivestreamFrameCaptureSegment(
            archive_id=archive.id,
            start_second=600,
            end_second=603,
            status="running",
            processed_frame_count=0,
        )
        db.session.add(segment)
        db.session.flush()

        reading = SimpleNamespace(
            frame_second=600,
            frame_index=0,
            video_offset_seconds=600.0,
            ocr_engine="paddleocr",
            overlay_style="paddleocr",
            clock="09:51",
            red_points=0,
            red_advantages=0,
            red_penalties=0,
            blue_points=0,
            blue_advantages=1,
            blue_penalties=0,
            known_score_count=6,
            score_complete=True,
            clock_detected=True,
            victory=False,
            victory_text=None,
            scoreboard_text="red\nblue",
            timer_text="09:51",
        )
        archive_lib.upsert_ocr_reading(db.session, archive, segment, reading)
        db.session.commit()

        reading.clock = "09:50"
        archive_lib.upsert_ocr_reading(db.session, archive, segment, reading)
        db.session.commit()

        rows = LivestreamFrameOcrReading.query.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].frame_second, 600)
        self.assertEqual(rows[0].clock, "09:50")

    def test_process_segment_frames_with_ocr_persists_frame_readings(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        db.session.flush()
        segment = LivestreamFrameCaptureSegment(
            archive_id=archive.id,
            start_second=600,
            end_second=603,
            status="running",
            processed_frame_count=0,
        )
        db.session.add(segment)
        db.session.flush()

        with tempfile.TemporaryDirectory() as temp_dir:
            frames_dir = Path(temp_dir)
            (frames_dir / "000001.jpg").write_bytes(b"one")
            (frames_dir / "000002.jpg").write_bytes(b"two")
            (frames_dir / "000003.jpg").write_bytes(b"three")

            def fake_process_frame(_path, frame_index, frame_second, **_kwargs):
                return SimpleNamespace(
                    frame_second=frame_second,
                    frame_index=frame_index,
                    video_offset_seconds=float(frame_second),
                    ocr_engine="opencv_rules",
                    overlay_style="new",
                    clock=f"09:{51 - frame_index:02d}",
                    red_points=0,
                    red_advantages=0,
                    red_penalties=0,
                    blue_points=0,
                    blue_advantages=1,
                    blue_penalties=0,
                    red_athlete_name="Red Athlete",
                    red_team_name="Red Team",
                    blue_athlete_name="Blue Athlete",
                    blue_team_name="Blue Team",
                    known_score_count=6,
                    score_complete=True,
                    clock_detected=True,
                    victory=False,
                    victory_text=None,
                    scoreboard_text="scoreboard",
                    timer_text="timer",
                )

            with mock.patch(
                "scoreboard_ocr.process_frame_fast", side_effect=fake_process_frame
            ):
                (
                    processed,
                    last_second,
                    completed_segment,
                ) = runner.process_segment_frames_with_ocr(
                    archive,
                    segment,
                    frames_dir,
                )
            db.session.commit()

        self.assertEqual(processed, 3)
        self.assertEqual(last_second, 602)
        self.assertTrue(completed_segment)
        self.assertEqual(segment.processed_frame_count, 3)
        self.assertEqual(segment.last_processed_second, 602)
        self.assertEqual(
            [
                row.frame_second
                for row in LivestreamFrameOcrReading.query.order_by(
                    LivestreamFrameOcrReading.frame_second
                ).all()
            ],
            [600, 601, 602],
        )
        first_row = LivestreamFrameOcrReading.query.filter_by(frame_second=600).one()
        self.assertEqual(first_row.red_athlete_name, "Red Athlete")
        self.assertEqual(first_row.red_team_name, "Red Team")
        self.assertEqual(first_row.blue_athlete_name, "Blue Athlete")
        self.assertEqual(first_row.blue_team_name, "Blue Team")


if __name__ == "__main__":
    unittest.main()
