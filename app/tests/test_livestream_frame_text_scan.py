import io
import os
import sys
import tarfile
import unittest
from unittest import mock

from sqlalchemy import create_engine

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "admin")),
)

from extensions import db  # noqa: E402
from models import (  # noqa: E402
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    LivestreamFrameTextScanSegment,
)
from test_db import TestDbMixin  # noqa: E402

import livestream_frame_text_scan as text_scan  # noqa: E402
import scan_livestream_frame_text as runner  # noqa: E402


class DictFrameProvider(text_scan.FrameBatchProvider):
    def __init__(self):
        self.calls = []

    def get_frame(self, frame_second, crop_variant):
        self.calls.append((frame_second, crop_variant))
        return f"{frame_second}:{crop_variant}".encode()


class TimelineParser:
    def __init__(self, readings):
        self.readings = readings
        self.calls = []

    def parse(self, frame_second, score_image, timer_image):
        self.calls.append(frame_second)
        values = {}
        for start_second, reading_values in sorted(self.readings.items()):
            if frame_second >= start_second:
                values = reading_values
        return text_scan.FrameReading(frame_second=frame_second, **values)


class FakeS3Body:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.keys = []

    def get_object(self, Bucket, Key):
        self.keys.append((Bucket, Key))
        return {"Body": FakeS3Body(self.objects[Key])}


def make_tgz(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            payload = data.encode() if isinstance(data, str) else data
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class LivestreamFrameTextScanAlgorithmTestCase(unittest.TestCase):
    def test_scanner_binary_searches_to_first_score_change(self):
        provider = DictFrameProvider()
        parser = TimelineParser(
            {
                0: {
                    "top_points": 0,
                    "top_advantages": 0,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 0,
                    "bottom_penalties": 0,
                },
                37: {"top_points": 2},
            }
        )
        debug_messages = []

        events = text_scan.scan_frame_text_segment(
            provider,
            parser,
            0,
            121,
            coarse_interval_seconds=120,
            debug_callback=debug_messages.append,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[1].top_points, 2)
        self.assertIn(37, parser.calls)
        self.assertTrue(
            any("binary search start range=1-120" in item for item in debug_messages)
        )
        self.assertTrue(
            any("binary search result second=37" in item for item in debug_messages)
        )
        self.assertTrue(
            any("event second=37 fields=top_points" in item for item in debug_messages)
        )

    def test_name_only_changes_do_not_emit_events(self):
        provider = DictFrameProvider()
        parser = TimelineParser(
            {
                0: {"top_athlete_name": "ALICE"},
                37: {"top_athlete_name": "BOB"},
            }
        )
        debug_messages = []

        events = text_scan.scan_frame_text_segment(
            provider,
            parser,
            0,
            121,
            coarse_interval_seconds=120,
            debug_callback=debug_messages.append,
        )

        self.assertEqual(events, [])
        self.assertFalse(any("binary search start" in item for item in debug_messages))

    def test_name_noise_does_not_pull_score_binary_search_earlier(self):
        provider = DictFrameProvider()

        class NoisyNameParser:
            def parse(self, frame_second, score_image, timer_image):
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    top_points=2 if frame_second >= 37 else 0,
                    top_athlete_name=f"NOISE {frame_second}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            NoisyNameParser(),
            0,
            121,
            coarse_interval_seconds=120,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[1].top_points, 2)
        self.assertEqual(events[1].top_athlete_name, "NOISE 37")

    def test_running_timer_tickdown_does_not_emit_events(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                remaining = 300 - frame_second
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=f"{remaining // 60}:{remaining % 60:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            241,
            coarse_interval_seconds=120,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].frame_second, 0)
        self.assertEqual(events[0].timer_state, "running")
        self.assertEqual(events[0].timer_value, "5:00")

    def test_repeated_running_timer_value_does_not_emit_duplicate_events(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value="4:00",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            241,
            coarse_interval_seconds=120,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "4:00")],
        )

    def test_timer_stop_and_blank_are_sparse_events(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                if frame_second >= 80:
                    return text_scan.FrameReading(
                        frame_second=frame_second,
                        timer_state="blank",
                        timer_value=None,
                    )
                if frame_second >= 50:
                    return text_scan.FrameReading(
                        frame_second=frame_second,
                        timer_state="stopped",
                        timer_value="4:10",
                    )
                remaining = 300 - frame_second
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=f"{remaining // 60}:{remaining % 60:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            121,
            coarse_interval_seconds=120,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "5:00"), (50, "stopped", "4:10"), (80, "blank", None)],
        )


class LivestreamFrameTextScanDbTestCase(TestDbMixin, unittest.TestCase):
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
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def _archive_with_segments(self, status="success"):
        archive = LivestreamFrameArchive(
            youtube_video_id="HxZSos1k_MA",
            canonical_url="https://www.youtube.com/watch?v=HxZSos1k_MA",
            s3_prefix="livestream-frames/HxZSos1k_MA/",
            status=status,
            frame_rate=1.0,
            image_format="jpg",
            uploaded_frame_count=240,
        )
        db.session.add(archive)
        db.session.flush()
        segments = [
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=0,
                end_second=120,
                status="success",
                uploaded_frame_count=120,
                last_uploaded_second=119,
                batch_s3_key="batch-0.tgz",
            ),
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=120,
                end_second=240,
                status="success",
                uploaded_frame_count=120,
                last_uploaded_second=239,
                batch_s3_key="batch-1.tgz",
            ),
        ]
        db.session.add_all(segments)
        db.session.commit()
        return archive, segments

    def test_queue_text_scan_requires_successful_archive(self):
        archive, _ = self._archive_with_segments(status="partial")

        with self.assertRaisesRegex(ValueError, "successful frame archives"):
            text_scan.queue_text_scan(db.session, archive)

    def test_queue_text_scan_defaults_name_engine_to_tesseract(self):
        archive, _ = self._archive_with_segments()

        text_scan.queue_text_scan(db.session, archive)
        db.session.commit()

        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        self.assertEqual(scan.name_engine, "tesseract")

    def test_queue_and_claim_segments_sequentially(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        db.session.commit()

        first = text_scan.claim_next_text_scan_segment(db.session)
        self.assertEqual(first.start_second, 0)
        second = text_scan.claim_next_text_scan_segment(db.session)
        self.assertIsNone(second)

        text_scan.mark_text_scan_segment_success(db.session, first, [])
        db.session.commit()
        second = text_scan.claim_next_text_scan_segment(db.session)
        self.assertEqual(second.start_second, 120)

    def test_reconstruct_text_state_applies_sparse_events(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan_segment = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).first()
        events = [
            text_scan.TextEventData(
                frame_second=0,
                top_points=0,
                bottom_points=0,
                timer_state="running",
                timer_value="5:00",
            ),
            text_scan.TextEventData(frame_second=10, top_points=2),
            text_scan.TextEventData(
                frame_second=70, timer_state="blank", timer_value=None
            ),
        ]
        text_scan.mark_text_scan_segment_success(db.session, scan_segment, events)
        db.session.commit()

        state = text_scan.reconstruct_text_state(db.session, archive.id)
        self.assertEqual(state.top_points, 2)
        self.assertEqual(state.bottom_points, 0)
        self.assertEqual(state.timer_state, "blank")
        self.assertIsNone(state.timer_value)

    def test_s3_frame_batch_provider_reads_across_batches(self):
        archive, segments = self._archive_with_segments()
        fake_s3 = FakeS3(
            {
                "batch-0.tgz": make_tgz(
                    {
                        "000000119_score.jpg": "score119",
                        "000000119_timer.jpg": "timer119",
                    }
                ),
                "batch-1.tgz": make_tgz(
                    {
                        "000000120_score.jpg": "score120",
                        "000000120_timer.jpg": "timer120",
                    }
                ),
            }
        )
        provider = text_scan.S3FrameBatchProvider(segments, fake_s3, "bucket")

        self.assertEqual(provider.get_frame(119, "score"), b"score119")
        self.assertEqual(provider.get_frame(120, "timer"), b"timer120")
        self.assertEqual(
            fake_s3.keys,
            [("bucket", "batch-0.tgz"), ("bucket", "batch-1.tgz")],
        )


class ScanLivestreamFrameTextWorkerTestCase(unittest.TestCase):
    def _name_parser(self, name_engine="tesseract"):
        parser = runner.TesseractTextParser.__new__(runner.TesseractTextParser)
        parser.name_engine = name_engine
        return parser

    def _score_parser(self):
        parser = runner.TesseractTextParser.__new__(runner.TesseractTextParser)
        return parser

    def test_parse_args_defaults_name_engine_to_tesseract(self):
        args = runner.parse_args([])

        self.assertEqual(args.name_engine, "tesseract")

    def test_tesseract_parser_reads_score_rows_from_scoreboard_text(self):
        parser = self._score_parser()

        fields = parser._parse_score(
            "\n".join(
                [
                    "MARIA SILVA 0 1 0",
                    "CHECKMAT",
                    "ANA SOUZA 2 0 1",
                    "ALLIANCE",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_points": 0,
                "top_advantages": 1,
                "top_penalties": 0,
                "bottom_points": 2,
                "bottom_advantages": 0,
                "bottom_penalties": 1,
            },
        )

    def test_tesseract_parser_reads_contiguous_score_row_digits(self):
        parser = self._score_parser()

        fields = parser._parse_score("000\n210")

        self.assertEqual(fields["top_points"], 0)
        self.assertEqual(fields["top_advantages"], 0)
        self.assertEqual(fields["top_penalties"], 0)
        self.assertEqual(fields["bottom_points"], 2)
        self.assertEqual(fields["bottom_advantages"], 1)
        self.assertEqual(fields["bottom_penalties"], 0)

    def test_tesseract_parser_reads_score_cells_before_grid_fallback(self):
        parser = self._score_parser()
        values = iter([(0, "0"), (0, "0"), (0, "0"), (2, "2"), (1, "1"), (1, "1")])
        parser._template_score_digit = lambda image, cell_index: next(values)

        from PIL import Image

        fields, text = parser._parse_score_cells_from_image(
            Image.new("RGB", (320, 144))
        )

        self.assertEqual(text, "000\n211")
        self.assertEqual(fields["top_points"], 0)
        self.assertEqual(fields["bottom_points"], 2)
        self.assertEqual(fields["bottom_advantages"], 1)
        self.assertEqual(fields["bottom_penalties"], 1)

    def test_tesseract_parser_normalizes_score_ocr_digit_confusions(self):
        parser = self._score_parser()

        fields = parser._parse_score("MARIA O I O\nANA 2 O l")

        self.assertEqual(fields["top_points"], 0)
        self.assertEqual(fields["top_advantages"], 1)
        self.assertEqual(fields["top_penalties"], 0)
        self.assertEqual(fields["bottom_points"], 2)
        self.assertEqual(fields["bottom_advantages"], 0)
        self.assertEqual(fields["bottom_penalties"], 1)

    def test_tesseract_parser_reads_names_from_scoreboard_text(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "MARIA SILVA",
                    "CHECKMAT",
                    "0 0 0",
                    "ANA SOUZA",
                    "ALLIANCE",
                    "2 1 0",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "MARIA SILVA",
                "bottom_athlete_name": "ANA SOUZA",
            },
        )

    def test_tesseract_parser_skips_names_when_name_engine_disabled(self):
        parser = self._name_parser(name_engine=None)

        self.assertEqual(parser._parse_names("MARIA SILVA\n0 0 0"), {})

    def test_tesseract_parser_name_only_mode_does_not_emit_score_or_timer(self):
        parser = self._name_parser()
        parser.parser_profile = "auto"
        parser.score_engine = "none"
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser._ocr = lambda image, config="": (
            "MARIA SILVA\nCHECKMAT\n0 0 0\nANA SOUZA\nALLIANCE\n2 1 0"
        )

        reading = parser.parse(12, b"score", b"timer")

        self.assertEqual(reading.top_athlete_name, "MARIA SILVA")
        self.assertEqual(reading.bottom_athlete_name, "ANA SOUZA")
        self.assertIsNone(reading.top_points)
        self.assertIsNone(reading.timer_state)

    def test_tesseract_parser_uses_score_grid_ocr_for_score_fields(self):
        parser = self._name_parser()
        parser.parser_profile = "auto"
        parser.score_engine = "tesseract"
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser._ocr = lambda image, config="": (
            "KEANU ALIKA ORA-A. i) ~\nJOSIAH KALANI YUEN 0 . ."
        )
        parser._parse_score_from_image = lambda image: (
            {
                "top_points": 0,
                "top_advantages": 0,
                "top_penalties": 0,
                "bottom_points": 2,
                "bottom_advantages": 1,
                "bottom_penalties": 0,
            },
            "000\n210",
        )

        reading = parser.parse(548, b"score", b"timer")

        self.assertEqual(reading.top_points, 0)
        self.assertEqual(reading.bottom_points, 2)
        self.assertEqual(reading.bottom_advantages, 1)
        self.assertEqual(reading.evidence["score_grid_text"], "000\n210")

    def test_validate_ocr_engines_accepts_none_without_imports(self):
        runner.validate_ocr_engines("none", None)

    def test_validate_ocr_engines_rejects_unknown_engine(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported OCR engine"):
            runner.validate_ocr_engines("bogus", None)

    def test_validate_ocr_engines_requires_tesseract_binary(self):
        with mock.patch.dict(
            sys.modules,
            {
                "pytesseract": mock.Mock(),
                "PIL": mock.Mock(),
                "PIL.Image": mock.Mock(),
            },
        ):
            with mock.patch("shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "tesseract binary"):
                    runner.validate_ocr_engines("tesseract", None)


class LivestreamFrameTextScanAdminApiTestCase(TestDbMixin, unittest.TestCase):
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
        db.session.commit()
        self.admin_module = None

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def _admin_client(self):
        if self.admin_module is None:
            import importlib

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
        return self.admin_module.app.test_client()

    def _archive_with_segment(self):
        archive = LivestreamFrameArchive(
            youtube_video_id="HxZSos1k_MA",
            canonical_url="https://www.youtube.com/watch?v=HxZSos1k_MA",
            s3_prefix="livestream-frames/HxZSos1k_MA/",
            status="success",
            frame_rate=1.0,
            image_format="jpg",
        )
        db.session.add(archive)
        db.session.flush()
        segment = LivestreamFrameCaptureSegment(
            archive_id=archive.id,
            start_second=0,
            end_second=60,
            status="success",
            uploaded_frame_count=60,
            last_uploaded_second=59,
            batch_s3_key="batch-0.tgz",
        )
        db.session.add(segment)
        db.session.commit()
        return archive, segment

    def test_worker_claim_complete_and_initial_state_api(self):
        archive, _ = self._archive_with_segment()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        db.session.commit()
        client = self._admin_client()
        headers = {"X-Admin-Password": "admin"}

        claim = client.post(
            "/api/livestream_frame_archives/worker/text_scan_segments/claim",
            json={},
            headers=headers,
        )
        self.assertEqual(claim.status_code, 200)
        segment_payload = claim.get_json()["segment"]
        self.assertEqual(segment_payload["start_second"], 0)
        self.assertEqual(len(segment_payload["archive_capture_segments"]), 1)

        initial_state = client.get(
            "/api/livestream_frame_archives/worker/"
            f"text_scan_segments/{segment_payload['id']}/initial_state",
            headers=headers,
        )
        self.assertEqual(initial_state.status_code, 200)
        self.assertIsNone(initial_state.get_json()["state"]["timer_state"])

        complete = client.post(
            "/api/livestream_frame_archives/worker/"
            f"text_scan_segments/{segment_payload['id']}/complete",
            json={
                "events": [
                    {
                        "frame_second": 0,
                        "top_points": 2,
                        "timer_state": "running",
                        "timer_value": "5:00",
                        "evidence": {"source": "test"},
                    }
                ]
            },
            headers=headers,
        )
        self.assertEqual(complete.status_code, 200)
        body = complete.get_json()
        self.assertEqual(body["segment"]["status"], "success")
        self.assertEqual(body["events"][0]["top_points"], 2)
        self.assertEqual(body["events"][0]["evidence"], {"source": "test"})


if __name__ == "__main__":
    unittest.main()
