import io
import os
import sys
import tarfile
import tempfile
import unittest
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

    def test_yt_dlp_options_parse_runtime_path_and_cookie_sources(self):
        options = runner._yt_dlp_options(
            "best",
            "node:/usr/local/bin/node",
            ["ejs:github"],
            cookies="/run/secrets/youtube.cookies",
            cookies_from_browser="chrome+basic:Default",
        )

        self.assertEqual(
            options["js_runtimes"],
            {"node": {"path": "/usr/local/bin/node"}},
        )
        self.assertEqual(options["cookiefile"], "/run/secrets/youtube.cookies")
        self.assertEqual(
            options["cookiesfrombrowser"],
            ("chrome", "Default", "BASIC", None),
        )

    def test_cookies_content_from_args_decodes_base64_fallback(self):
        self.assertEqual(
            runner._cookies_content_from_args(None, "Y29va2llCg=="),
            "cookie\n",
        )

    def test_cookiefile_from_content_writes_temp_file(self):
        with runner._cookiefile_from_content(None, "cookies") as cookiefile:
            cookie_path = Path(cookiefile)
            self.assertTrue(cookie_path.exists())
            self.assertEqual(cookie_path.read_text(), "cookies\n")

        self.assertFalse(cookie_path.exists())

    def test_cookiefile_stats_counts_youtube_related_cookie_rows(self):
        cookies = "\n".join(
            [
                "# Netscape HTTP Cookie File",
                ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tVISITOR_INFO1_LIVE\tvalue",
                "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1893456000\tSID\tvalue",
                ".example.com\tTRUE\t/\tTRUE\t1893456000\tfoo\tbar",
                "",
            ]
        )
        with runner._cookiefile_from_content(None, cookies) as cookiefile:
            self.assertEqual(
                runner._cookiefile_stats(cookiefile),
                "rows=3 youtube_related_rows=2",
            )

    def test_select_available_video_format_prefers_avc_under_1080p(self):
        formats = [
            {
                "format_id": "18",
                "height": 360,
                "fps": 30,
                "tbr": 278,
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "url": "https://example.com/360.mp4",
            },
            {
                "format_id": "399",
                "height": 1080,
                "fps": 60,
                "tbr": 896,
                "vcodec": "av01.0.09M.08",
                "acodec": "none",
                "url": "https://example.com/1080-av1.mp4",
            },
            {
                "format_id": "299",
                "height": 1080,
                "fps": 60,
                "tbr": 2316,
                "vcodec": "avc1.64002a",
                "acodec": "none",
                "url": "https://example.com/1080-avc.mp4",
            },
        ]

        selected = runner._select_available_video_format(formats)
        self.assertEqual(selected["format_id"], "299")

    def test_select_available_video_format_ignores_audio_only_formats(self):
        self.assertIsNone(
            runner._select_available_video_format(
                [
                    {
                        "format_id": "140",
                        "vcodec": "none",
                        "acodec": "mp4a.40.2",
                        "url": "https://example.com/audio.m4a",
                    }
                ]
            )
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
        self.assertLess(command.index("-t"), command.index("-i"))
        self.assertNotIn("-skip_frame", command)
        self.assertNotIn("-copyts", command)
        self.assertNotIn("-frame_pts", command)
        self.assertIn("-filter_complex", command)
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("fps=1", filter_complex)
        self.assertIn("crop=w=trunc(iw*0.25):h=trunc(ih*0.20)", filter_complex)
        self.assertIn("crop=w=trunc(iw*0.22):h=trunc(ih*0.11)", filter_complex)
        self.assertIn("/tmp/frames/%06d_score.jpg", command)
        self.assertEqual(command[-1], "/tmp/frames/%06d_timer.jpg")


class ArchiveLivestreamFramesAdminApiStateTestCase(unittest.TestCase):
    class FakeResponse:
        def __init__(self, status_code=200, payload=None, text=""):
            self.status_code = status_code
            self.payload = payload or {}
            self.text = text

        def json(self):
            return self.payload

    class FakeSession:
        def __init__(self, responses):
            self.responses = list(responses)
            self.requests = []

        def request(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            return self.responses.pop(0)

    def test_claim_next_segment_uses_admin_password_header(self):
        fake_session = self.FakeSession(
            [
                self.FakeResponse(
                    payload={
                        "segment": {
                            "id": "segment-1",
                            "archive_id": "archive-1",
                            "start_second": 600,
                            "end_second": 900,
                            "attempt_count": 2,
                            "archive": {
                                "id": "archive-1",
                                "youtube_video_id": "HxZSos1k_MA",
                                "canonical_url": "https://www.youtube.com/watch?v=HxZSos1k_MA",
                                "frame_rate": 1.0,
                                "image_format": "jpg",
                                "duration_seconds": None,
                            },
                        }
                    }
                )
            ]
        )
        state = runner.AdminApiArchiveState(
            "https://admin.example.com", "secret", session=fake_session
        )

        segment = state.claim_next_segment(youtube_video_id="HxZSos1k_MA")

        self.assertEqual(segment.id, "segment-1")
        self.assertEqual(segment.archive.youtube_video_id, "HxZSos1k_MA")
        method, url, kwargs = fake_session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://admin.example.com/api/livestream_frame_archives/worker/segments/claim",
        )
        self.assertEqual(kwargs["headers"]["X-Admin-Password"], "secret")
        self.assertEqual(kwargs["json"]["youtube_video_id"], "HxZSos1k_MA")

    def test_mark_probe_complete_sends_sanitized_probe_fields_and_updates_archive(self):
        fake_session = self.FakeSession(
            [
                self.FakeResponse(
                    payload={
                        "archive": {
                            "id": "archive-1",
                            "youtube_video_id": "HxZSos1k_MA",
                            "duration_seconds": 1200,
                            "frame_rate": 1.0,
                        },
                        "created_segments": 2,
                    }
                )
            ]
        )
        state = runner.AdminApiArchiveState(
            "https://admin.example.com", "secret", session=fake_session
        )
        archive = runner.ApiObject(
            {
                "id": "archive-1",
                "youtube_video_id": "HxZSos1k_MA",
                "duration_seconds": None,
            }
        )
        selected = {
            "format_id": "299",
            "height": 1080,
            "fps": 60,
            "url": "https://video.example.com/private-token",
        }

        created = state.mark_probe_complete(
            archive,
            {"duration": 1199.2, "formats": ["large payload"]},
            selected,
            "2026.01.01",
            600,
            1.0,
        )

        self.assertEqual(created, 2)
        self.assertEqual(archive.duration_seconds, 1200)
        request_json = fake_session.requests[0][2]["json"]
        self.assertEqual(request_json["duration"], 1199.2)
        self.assertEqual(request_json["selected"]["format_id"], "299")
        self.assertEqual(request_json["selected"]["height"], 1080)
        self.assertNotIn("url", request_json["selected"])
        self.assertNotIn("formats", request_json)


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
        self.assertEqual(archive.s3_prefix, "livestream-frames/HxZSos1k_MA/")

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
                uploaded_frame_count=600,
                last_uploaded_second=599,
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

    def test_queue_archive_capture_requeues_cancelled_segment(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.status = "cancelled"
        archive.last_error = "archive cancelled by admin"
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="cancelled",
                last_error="cancelled by admin",
                finished_at=datetime.utcnow(),
            )
        )
        db.session.commit()

        queued = archive_lib.queue_archive_capture(
            db.session, archive, segment_seconds=600
        )
        db.session.commit()

        segment = LivestreamFrameCaptureSegment.query.one()
        self.assertEqual(queued, 1)
        self.assertEqual(segment.status, "queued")
        self.assertIsNone(segment.last_error)
        self.assertEqual(archive.status, "queued")
        self.assertIsNone(archive.last_error)

    def test_recompute_archive_status_from_segments(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="success",
                uploaded_frame_count=600,
                last_uploaded_second=599,
                finished_at=datetime.utcnow(),
            )
        )
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=600,
                end_second=1200,
                status="error",
                uploaded_frame_count=10,
                last_uploaded_second=609,
                last_error="boom",
                finished_at=datetime.utcnow(),
            )
        )
        archive_lib.recompute_archive_status(db.session, archive)
        self.assertEqual(archive.status, "partial")
        self.assertEqual(archive.uploaded_frame_count, 600)
        self.assertEqual(archive.last_uploaded_second, 599)

    def test_retry_failed_segments_requeues_cancelled_segments(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.status = "cancelled"
        archive.last_error = "archive cancelled by admin"
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="cancelled",
                last_error="cancelled by admin",
                finished_at=datetime.utcnow(),
            )
        )
        db.session.commit()

        requeued = archive_lib.retry_failed_segments(db.session, [archive.id])
        db.session.commit()

        segment = LivestreamFrameCaptureSegment.query.one()
        self.assertEqual(requeued, 1)
        self.assertEqual(segment.status, "queued")
        self.assertIsNone(segment.last_error)
        self.assertIsNone(segment.finished_at)
        self.assertEqual(segment.archive.status, "queued")
        self.assertIsNone(segment.archive.last_error)

    def test_retry_failed_segments_clears_selected_archive_error_without_segments(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.status = "error"
        archive.last_error = "stale archive error"
        db.session.commit()

        requeued = archive_lib.retry_failed_segments(db.session, [archive.id])
        db.session.commit()

        self.assertEqual(requeued, 0)
        self.assertIsNone(archive.last_error)

    def test_requeue_completed_segments_clears_upload_metadata(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive.status = "success"
        archive.duration_seconds = 1200
        archive.uploaded_frame_count = 1200
        archive.last_uploaded_second = 1199
        archive.completed_at = datetime.utcnow()
        db.session.flush()
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=600,
                status="success",
                attempt_count=1,
                uploaded_frame_count=600,
                sampled_frame_count=0,
                last_uploaded_second=599,
                batch_s3_key="livestream-frame-batches/HxZSos1k_MA/000000000-000000600.tgz",
                batch_uploaded_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            )
        )
        db.session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=600,
                end_second=1200,
                status="error",
                uploaded_frame_count=10,
                last_uploaded_second=609,
                last_error="boom",
                finished_at=datetime.utcnow(),
            )
        )
        db.session.commit()

        requeued = archive_lib.requeue_completed_segments(db.session, archive)
        db.session.commit()

        segments = LivestreamFrameCaptureSegment.query.order_by(
            LivestreamFrameCaptureSegment.start_second
        ).all()
        self.assertEqual(requeued, 1)
        self.assertEqual(segments[0].status, "queued")
        self.assertEqual(segments[0].uploaded_frame_count, 0)
        self.assertIsNone(segments[0].last_uploaded_second)
        self.assertIsNone(segments[0].batch_s3_key)
        self.assertIsNone(segments[0].batch_uploaded_at)
        self.assertIsNone(segments[0].started_at)
        self.assertIsNone(segments[0].finished_at)
        self.assertIsNone(segments[0].last_error)
        self.assertEqual(segments[1].status, "error")
        self.assertEqual(segments[1].last_error, "boom")
        self.assertEqual(archive.status, "queued")
        self.assertEqual(archive.uploaded_frame_count, 0)
        self.assertIsNone(archive.last_uploaded_second)
        self.assertIsNone(archive.completed_at)
        self.assertEqual(archive.expected_frame_count, 1200)

    def test_claim_next_segment_marks_running(self):
        archive, _ = archive_lib.get_or_create_archive(db.session, "HxZSos1k_MA")
        archive_lib.queue_archive_capture(db.session, archive)
        db.session.commit()

        segment = archive_lib.claim_next_segment(db.session)
        self.assertIsNotNone(segment)
        self.assertEqual(segment.status, "running")
        self.assertEqual(segment.attempt_count, 1)
        self.assertEqual(segment.archive.status, "running")


class UploadMappingTestCase(unittest.TestCase):
    def test_upload_segment_artifacts_batches_crops_without_full_frame_samples(self):
        class FakeS3:
            def __init__(self):
                self.uploads = []

            def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
                self.uploads.append((bucket, key, ExtraArgs, fileobj.read()))

        archive = LivestreamFrameArchive(
            youtube_video_id="HxZSos1k_MA",
            canonical_url="https://www.youtube.com/watch?v=HxZSos1k_MA",
            s3_prefix="livestream-frames/HxZSos1k_MA/",
            status="running",
            frame_rate=1.0,
            image_format="jpg",
        )
        segment = LivestreamFrameCaptureSegment(
            start_second=600,
            end_second=603,
            status="running",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            frames_dir = Path(temp_dir)
            (frames_dir / "000001_score.jpg").write_bytes(b"one-score")
            (frames_dir / "000001_timer.jpg").write_bytes(b"one-timer")
            (frames_dir / "000002_score.jpg").write_bytes(b"two-score")
            (frames_dir / "000002_timer.jpg").write_bytes(b"two-timer")
            (frames_dir / "000003_score.jpg").write_bytes(b"three-score")
            (frames_dir / "000003_timer.jpg").write_bytes(b"three-timer")
            (frames_dir / "000004_score.jpg").write_bytes(b"out-score")
            (frames_dir / "000004_timer.jpg").write_bytes(b"out-timer")
            (frames_dir / "000001.jpg").write_bytes(b"full-frame")

            fake_s3 = FakeS3()
            uploaded, last_second, sampled, batch_key = runner.upload_segment_artifacts(
                archive,
                segment,
                frames_dir,
                fake_s3,
                "bucket",
                dry_run=False,
            )

        self.assertEqual(uploaded, 3)
        self.assertEqual(last_second, 602)
        self.assertEqual(sampled, 0)
        self.assertEqual(
            batch_key,
            "livestream-frame-batches/HxZSos1k_MA/000000600-000000603.tgz",
        )
        self.assertEqual(segment.uploaded_frame_count, 3)
        self.assertEqual(segment.sampled_frame_count, 0)
        self.assertEqual(segment.last_uploaded_second, 602)
        self.assertEqual(segment.batch_s3_key, batch_key)

        self.assertEqual(len(fake_s3.uploads), 1)
        batch_upload = fake_s3.uploads[0]
        self.assertEqual(
            batch_upload[:3],
            (
                "bucket",
                "livestream-frame-batches/HxZSos1k_MA/000000600-000000603.tgz",
                {"ContentType": "application/gzip"},
            ),
        )
        with tarfile.open(fileobj=io.BytesIO(batch_upload[3]), mode="r:gz") as tar:
            self.assertEqual(
                sorted(tar.getnames()),
                [
                    "000000600_score.jpg",
                    "000000600_timer.jpg",
                    "000000601_score.jpg",
                    "000000601_timer.jpg",
                    "000000602_score.jpg",
                    "000000602_timer.jpg",
                ],
            )
            self.assertEqual(
                tar.extractfile("000000600_score.jpg").read(), b"one-score"
            )
            self.assertEqual(
                tar.extractfile("000000600_timer.jpg").read(), b"one-timer"
            )
            self.assertEqual(
                tar.extractfile("000000601_score.jpg").read(), b"two-score"
            )
            self.assertEqual(
                tar.extractfile("000000601_timer.jpg").read(), b"two-timer"
            )
            self.assertEqual(
                tar.extractfile("000000602_score.jpg").read(), b"three-score"
            )
            self.assertEqual(
                tar.extractfile("000000602_timer.jpg").read(), b"three-timer"
            )

    def test_upload_segment_artifacts_requires_paired_crops(self):
        class FakeS3:
            def __init__(self):
                self.keys = []

            def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
                self.keys.append(key)

        archive = LivestreamFrameArchive(
            youtube_video_id="HxZSos1k_MA",
            canonical_url="https://www.youtube.com/watch?v=HxZSos1k_MA",
            s3_prefix="livestream-frames/HxZSos1k_MA/",
            status="running",
            frame_rate=1.0,
            image_format="jpg",
        )
        segment = LivestreamFrameCaptureSegment(
            start_second=600,
            end_second=602,
            status="running",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            frames_dir = Path(temp_dir)
            (frames_dir / "000001_score.jpg").write_bytes(b"one")

            fake_s3 = FakeS3()
            with self.assertRaisesRegex(RuntimeError, "Missing timer crop"):
                runner.upload_segment_artifacts(
                    archive,
                    segment,
                    frames_dir,
                    fake_s3,
                    "bucket",
                    dry_run=False,
                )
            self.assertEqual(fake_s3.keys, [])


if __name__ == "__main__":
    unittest.main()
