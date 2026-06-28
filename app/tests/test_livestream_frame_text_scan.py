import io
import json
import os
import sys
import tarfile
import unittest
import uuid
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
import livestream_frame_text_ocr as text_ocr  # noqa: E402
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
                0: {"top_athlete_name": "TEST ATHLETE ALPHA"},
                37: {"top_athlete_name": "TEST ATHLETE BETA"},
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
        self.assertIsNone(events[1].top_athlete_name)

    def test_score_events_include_complete_athlete_name_pair(self):
        provider = DictFrameProvider()

        class NamePairParser:
            def parse(self, frame_second, score_image, timer_image):
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    top_points=2 if frame_second >= 37 else 0,
                    top_athlete_name="TEST ATHLETE ALPHA",
                    bottom_athlete_name="TEST ATHLETE BETA",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            NamePairParser(),
            0,
            121,
            coarse_interval_seconds=120,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[0].top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[0].bottom_athlete_name, "TEST ATHLETE BETA")
        self.assertEqual(events[1].top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[1].bottom_athlete_name, "TEST ATHLETE BETA")

    def test_score_events_include_victory_team_line(self):
        provider = DictFrameProvider()

        class VictoryParser:
            def parse(self, frame_second, score_image, timer_image):
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    top_points=2 if frame_second >= 37 else 0,
                    top_athlete_name="Victory",
                    bottom_athlete_name="TEST ATHLETE ALPHA",
                    bottom_team_name="SAMPLE TEAM ONE",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            VictoryParser(),
            0,
            121,
            coarse_interval_seconds=120,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[0].top_athlete_name, "Victory")
        self.assertEqual(events[0].bottom_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[0].bottom_team_name, "SAMPLE TEAM ONE")
        self.assertEqual(events[1].top_athlete_name, "Victory")
        self.assertEqual(events[1].bottom_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[1].bottom_team_name, "SAMPLE TEAM ONE")

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

    def test_running_timer_tickdown_accepts_canonical_single_digit_minutes(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                remaining = 97 - frame_second
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=f"{remaining // 60}:{remaining % 60:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            61,
            coarse_interval_seconds=20,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "1:37")],
        )

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

    def test_sampled_scoreboard_blank_then_zero_zero_return_are_sparse_events(self):
        provider = DictFrameProvider()
        zero_zero = {
            "scoreboard_state": text_scan.SCOREBOARD_STATE_VISIBLE,
            "top_points": 0,
            "top_advantages": 0,
            "top_penalties": 0,
            "bottom_points": 0,
            "bottom_advantages": 0,
            "bottom_penalties": 0,
        }
        parser = TimelineParser(
            {
                0: zero_zero,
                20: {
                    "scoreboard_state": text_scan.SCOREBOARD_STATE_VISIBLE,
                    "top_points": 2,
                    "top_advantages": 0,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 0,
                    "bottom_penalties": 0,
                },
                40: {"scoreboard_state": text_scan.SCOREBOARD_STATE_BLANK},
                60: zero_zero,
            }
        )

        events = text_scan.scan_frame_text_segment(
            provider,
            parser,
            0,
            81,
            coarse_interval_seconds=20,
        )

        self.assertEqual([event.frame_second for event in events], [0, 20, 40, 60])
        self.assertEqual(events[2].scoreboard_state, text_scan.SCOREBOARD_STATE_BLANK)
        self.assertIsNone(events[2].top_points)
        self.assertEqual(events[3].scoreboard_state, text_scan.SCOREBOARD_STATE_VISIBLE)
        self.assertEqual(events[3].top_points, 0)
        self.assertEqual(events[3].bottom_points, 0)


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
                frame_second=20,
                scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK,
            ),
            text_scan.TextEventData(
                frame_second=70, timer_state="blank", timer_value=None
            ),
        ]
        text_scan.mark_text_scan_segment_success(db.session, scan_segment, events)
        db.session.commit()

        state = text_scan.reconstruct_text_state(db.session, archive.id)
        self.assertEqual(state.scoreboard_state, text_scan.SCOREBOARD_STATE_BLANK)
        self.assertIsNone(state.top_points)
        self.assertIsNone(state.bottom_points)
        self.assertEqual(state.timer_state, "blank")
        self.assertIsNone(state.timer_value)

    def test_prepare_text_scan_segment_rescan_deletes_events_and_marks_running(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan_segment = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).first()
        text_scan.mark_text_scan_segment_success(
            db.session,
            scan_segment,
            [
                text_scan.TextEventData(
                    frame_second=0,
                    timer_state="running",
                    timer_value="5:00",
                )
            ],
        )
        db.session.commit()
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter_by(
                scan_segment_id=scan_segment.id
            ).count(),
            1,
        )

        prepared = text_scan.prepare_text_scan_segment_rescan(
            db.session,
            scan_segment.id,
        )

        self.assertEqual(prepared.id, scan_segment.id)
        self.assertEqual(prepared.status, "running")
        self.assertEqual(prepared.attempt_count, 1)
        self.assertEqual(prepared.event_count, 0)
        self.assertIsNone(prepared.last_processed_second)
        self.assertIsNone(prepared.last_error)
        self.assertEqual(prepared.scan.status, "running")
        self.assertIsNone(prepared.scan.completed_at)
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter_by(
                scan_segment_id=scan_segment.id
            ).count(),
            0,
        )

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
        parser = text_ocr.FrameImageTextParser.__new__(text_ocr.FrameImageTextParser)
        parser.name_engine = name_engine
        return parser

    def test_parse_args_defaults_name_engine_to_tesseract(self):
        args = runner.parse_args([])

        self.assertEqual(args.name_engine, "tesseract")
        self.assertEqual(args.score_engine, "fixed_digit")

    def test_run_with_segment_id_rescans_specific_segment(self):
        segment_id = "11111111-1111-1111-1111-111111111111"
        segment = runner.ApiObject(
            {
                "id": segment_id,
                "archive_id": "22222222-2222-2222-2222-222222222222",
                "start_second": 0,
                "end_second": 60,
            }
        )

        class FakeState:
            def __init__(self):
                self.rescanned_segment_id = None
                self.claimed = False

            def rescan_segment(self, rescan_segment_id, background_task_id=None):
                self.rescanned_segment_id = rescan_segment_id
                return segment

            def claim_next_segment(self, **kwargs):
                self.claimed = True
                return None

        args = runner.parse_args(["--segment-id", segment_id, "--score-engine", "none"])
        state = FakeState()

        with mock.patch.object(runner, "validate_ocr_engines"), mock.patch.object(
            runner, "build_parser", return_value="parser"
        ), mock.patch.object(runner, "bucket_name", "bucket"), mock.patch.object(
            runner, "get_s3_client", return_value="s3"
        ), mock.patch.object(
            runner, "process_segment"
        ) as process_segment:
            result = runner.run(args, state=state)

        self.assertEqual(result, 0)
        self.assertEqual(str(state.rescanned_segment_id), segment_id)
        self.assertFalse(state.claimed)
        process_segment.assert_called_once_with(
            segment, state, "parser", "s3", "bucket"
        )

    def test_tesseract_parser_reads_names_from_scoreboard_text(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "TEST ATHLETE ALPHA",
                    "SAMPLE TEAM ONE",
                    "0 0 0",
                    "TEST ATHLETE BETA",
                    "SAMPLE TEAM TWO",
                    "2 1 0",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )

    def test_tesseract_parser_strips_score_junk_from_name_lines(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "TEST ATHLETE GAMMA-RAY 0 . ~",
                    "TEST ATHLETE DELTA, 8 =p ;",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )

    def test_tesseract_parser_ignores_short_junk_name_lines(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "S\ney 1\nrs PT\nTEST ATHLETE ALPHA\nTEST ATHLETE BETA"
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )

    def test_tesseract_parser_uses_blank_lines_as_name_boundaries(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "Ana Julia Samara R. Lima",
                    "CheckMat",
                    "",
                    "Roberta Graciani Medeiros",
                    "Alliance",
                    "",
                    "> = - 6 - t~isSYT - =",
                ]
            ),
            allow_two_line_fallback=False,
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "Ana Julia Samara R. Lima",
                "bottom_athlete_name": "Roberta Graciani Medeiros",
            },
        )

    def test_tesseract_parser_reads_victory_screen(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "Victory",
                    "Test Athlete Winner",
                    "Sample Team BJJ",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "Victory",
                "bottom_athlete_name": "Test Athlete Winner",
                "bottom_team_name": "Sample Team BJJ",
            },
        )

    def test_tesseract_parser_reads_cropped_victory_screen(self):
        parser = self._name_parser()

        fields = parser._parse_names(
            "\n".join(
                [
                    "ictory",
                    "Test Athlete Winner",
                    "Sample Team BJJ",
                ]
            )
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "Victory",
                "bottom_athlete_name": "Test Athlete Winner",
                "bottom_team_name": "Sample Team BJJ",
            },
        )

    def test_tesseract_parser_falls_back_to_complete_column_text(self):
        class FakeScoreImage:
            size = (320, 140)

            def __init__(self):
                self.boxes = []

            def crop(self, box):
                self.boxes.append(box)
                return f"crop-{len(self.boxes)}"

        parser = self._name_parser()
        parser._prepare_name_ocr_image = lambda image: f"prepared-{image}"
        parser._ocr = mock.Mock(
            side_effect=[
                "\n".join(
                    [
                        "TEST ATHLETE GAMMA-RAY",
                        "SAMPLE TEAM ONE",
                        "TEST ATHLETE DELTA",
                        "SAMPLE TEAM TWO",
                    ]
                ),
                "",
                "",
            ]
        )
        score_image = FakeScoreImage()

        scoreboard_text, fields = parser._ocr_name_fields(score_image)

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )
        self.assertIn("TEST ATHLETE GAMMA-RAY", scoreboard_text)
        self.assertEqual(score_image.boxes[0], (0, 0, 153, 120))
        self.assertEqual(len(score_image.boxes), 3)
        parser._ocr.assert_has_calls(
            [
                mock.call("prepared-crop-1", "--psm 6"),
                mock.call("prepared-crop-2", "--psm 7"),
                mock.call("prepared-crop-3", "--psm 7"),
            ]
        )

    def test_tesseract_parser_prefers_split_rows_over_ambiguous_column_pair(self):
        class FakeScoreImage:
            size = (320, 140)

            def __init__(self):
                self.boxes = []

            def crop(self, box):
                self.boxes.append(box)
                return f"crop-{len(self.boxes)}"

        parser = self._name_parser()
        parser._prepare_name_ocr_image = lambda image: f"prepared-{image}"
        parser._ocr = mock.Mock(
            side_effect=[
                "\n".join(["TEST ATHLETE GAMMA-RAY", "SAMPLE TEAM ONE"]),
                "TEST ATHLETE GAMMA-RAY",
                "TEST ATHLETE DELTA",
            ]
        )
        score_image = FakeScoreImage()

        scoreboard_text, fields = parser._ocr_name_fields(score_image)

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )
        self.assertIn("SAMPLE TEAM ONE", scoreboard_text)
        self.assertEqual(len(score_image.boxes), 3)

    def test_tesseract_parser_falls_back_to_split_rows(self):
        class FakeScoreImage:
            size = (320, 140)

            def __init__(self):
                self.boxes = []

            def crop(self, box):
                self.boxes.append(box)
                return f"crop-{len(self.boxes)}"

        parser = self._name_parser()
        parser._prepare_name_ocr_image = lambda image: f"prepared-{image}"
        parser._ocr = mock.Mock(
            side_effect=["", "TEST ATHLETE GAMMA-RAY", "TEST ATHLETE DELTA"]
        )
        score_image = FakeScoreImage()

        _, fields = parser._ocr_name_fields(score_image)

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )
        self.assertEqual(len(score_image.boxes), 3)
        self.assertLessEqual(max(box[2] for box in score_image.boxes), 154)
        self.assertLess(score_image.boxes[1][3], score_image.boxes[2][1])
        parser._ocr.assert_has_calls(
            [
                mock.call("prepared-crop-1", "--psm 6"),
                mock.call("prepared-crop-2", "--psm 7"),
                mock.call("prepared-crop-3", "--psm 7"),
            ]
        )

    def test_tesseract_parser_suppresses_partial_name_ocr(self):
        class FakeScoreImage:
            size = (320, 140)

            def crop(self, box):
                return box

        parser = self._name_parser()
        parser._prepare_name_ocr_image = lambda image: image
        parser._ocr = mock.Mock(side_effect=["", "TEST ATHLETE GAMMA-RAY", ""])

        _, fields = parser._ocr_name_fields(FakeScoreImage())

        self.assertEqual(fields, {})

    def test_tesseract_parser_skips_names_when_name_engine_disabled(self):
        parser = self._name_parser(name_engine=None)

        self.assertEqual(parser._parse_names("TEST ATHLETE ALPHA\n0 0 0"), {})

    def test_frame_image_parser_name_only_mode_does_not_emit_score_or_timer(self):
        parser = self._name_parser()
        parser.parser_profile = "auto"
        parser.score_engine = "none"
        parser.score_reader = None
        parser.timer_reader = None
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser._ocr = lambda image, config="": (
            "TEST ATHLETE ALPHA\nSAMPLE TEAM ONE\n0 0 0\n"
            "TEST ATHLETE BETA\nSAMPLE TEAM TWO\n2 1 0"
        )

        reading = parser.parse(12, b"score", b"timer")

        self.assertEqual(reading.top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(reading.bottom_athlete_name, "TEST ATHLETE BETA")
        self.assertIsNone(reading.top_points)
        self.assertIsNone(reading.timer_state)

    def test_frame_image_parser_uses_fixed_digit_readers_for_score_and_timer(self):
        parser = self._name_parser()
        parser.parser_profile = "auto"
        parser.score_engine = "fixed_digit"
        parser.name_engine = None
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser._ocr = mock.Mock(side_effect=AssertionError("unexpected OCR call"))
        parser.score_reader = mock.Mock()
        parser.score_reader.read.return_value = text_ocr.ScoreboardDigitReading(
            (0, 0, 0, 2, 1, 0),
            (
                text_ocr.DigitPrediction(0, 0.9, "test"),
                text_ocr.DigitPrediction(0, 0.9, "test"),
                text_ocr.DigitPrediction(0, 0.9, "test"),
                text_ocr.DigitPrediction(2, 0.9, "test"),
                text_ocr.DigitPrediction(1, 0.9, "test"),
                text_ocr.DigitPrediction(0, 0.9, "test"),
            ),
            True,
        )
        parser.timer_reader = mock.Mock()
        parser.timer_reader.read.return_value = text_ocr.TimerDigitReading(
            "stopped",
            "4:00",
            (
                text_ocr.DigitPrediction(4, 0.9, "test"),
                text_ocr.DigitPrediction(0, 0.9, "test"),
                text_ocr.DigitPrediction(0, 0.9, "test"),
            ),
        )

        reading = parser.parse(548, b"score", b"timer")

        self.assertEqual(reading.scoreboard_state, text_scan.SCOREBOARD_STATE_VISIBLE)
        self.assertEqual(reading.top_points, 0)
        self.assertEqual(reading.bottom_points, 2)
        self.assertEqual(reading.bottom_advantages, 1)
        self.assertEqual(reading.timer_state, "stopped")
        self.assertEqual(reading.timer_value, "4:00")
        self.assertEqual(reading.evidence["score_digits"], "000/210")

    def test_scoreboard_digit_reader_accepts_rendered_layout(self):
        if (
            text_ocr.cv2 is None
            or text_ocr.np is None
            or text_ocr.Image is None
            or text_ocr.ImageDraw is None
        ):
            self.skipTest("fixed digit OCR dependencies are unavailable")

        class ConstantClassifier:
            def predict(self, mask):
                return text_ocr.DigitPrediction(0, 0.99, "test")

        image = text_ocr.Image.new("RGB", (1000, 200), (0, 0, 0))
        draw = text_ocr.ImageDraw.Draw(image)
        colors = {
            "green": (40, 150, 60),
            "yellow": (190, 160, 50),
            "red": (180, 40, 50),
        }
        layout = text_ocr._score_layouts(image.size)[1]
        for box, role in zip(layout.cell_boxes, layout.background_roles):
            draw.rectangle(box, fill=colors[role])
            x1, y1, _, y2 = box
            draw.rectangle(
                (x1 + 24, y1 + 16, x1 + 34, y2 - 16),
                fill=(245, 245, 245),
            )

        reading = text_ocr.ScoreboardDigitReader(ConstantClassifier()).read(image)

        self.assertTrue(reading.has_layout)
        self.assertEqual(reading.digits, (0, 0, 0, 0, 0, 0))

    def test_score_fields_from_reading_marks_missing_layout_as_blank(self):
        reading = text_ocr.ScoreboardDigitReading(
            None,
            tuple(text_ocr.DigitPrediction(None, 0.0, "none") for _ in range(6)),
            False,
        )

        self.assertEqual(
            text_ocr.score_fields_from_reading(reading),
            {"scoreboard_state": text_scan.SCOREBOARD_STATE_BLANK},
        )

    def test_score_fields_from_reading_ignores_unreadable_visible_layout(self):
        reading = text_ocr.ScoreboardDigitReading(
            None,
            tuple(text_ocr.DigitPrediction(None, 0.0, "none") for _ in range(6)),
            True,
        )

        self.assertEqual(text_ocr.score_fields_from_reading(reading), {})

    def test_validate_ocr_engines_accepts_none_without_imports(self):
        text_ocr.validate_ocr_engines("none", None)

    def test_validate_ocr_engines_rejects_unknown_engine(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported score engine"):
            text_ocr.validate_ocr_engines("bogus", None)

    def test_validate_ocr_engines_rejects_tesseract_score_engine(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported score engine"):
            text_ocr.validate_ocr_engines("tesseract", None)

    def test_validate_ocr_engines_requires_tesseract_binary_for_names(self):
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
                    text_ocr.validate_ocr_engines("none", "tesseract")


class LivestreamFrameTextOcrFixtureTestCase(unittest.TestCase):
    fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures", "livestream_ocr")

    def test_score_and_timer_fixture_cases(self):
        cases_path = os.path.join(self.fixture_dir, "cases.json")
        self.assertTrue(
            os.path.exists(cases_path),
            "livestream OCR fixture manifest is missing",
        )

        with open(cases_path) as fileobj:
            cases = json.load(fileobj)
        self.assertTrue(cases, "livestream OCR fixture manifest has no cases")

        text_ocr.validate_ocr_engines("fixed_digit", "none")
        parser = text_ocr.FrameImageTextParser("auto", "fixed_digit", "none")

        for case in cases:
            with self.subTest(case=case["id"]):
                score_path = os.path.join(self.fixture_dir, case["score_image"])
                timer_path = os.path.join(self.fixture_dir, case["timer_image"])
                self.assertTrue(
                    os.path.exists(score_path),
                    f"missing livestream OCR score fixture: {case['score_image']}",
                )
                self.assertTrue(
                    os.path.exists(timer_path),
                    f"missing livestream OCR timer fixture: {case['timer_image']}",
                )

                with open(score_path, "rb") as fileobj:
                    score_image = fileobj.read()
                with open(timer_path, "rb") as fileobj:
                    timer_image = fileobj.read()

                reading = parser.parse(0, score_image, timer_image)

                for field_name, expected_value in case["expected"].items():
                    self.assertEqual(
                        getattr(reading, field_name),
                        expected_value,
                        field_name,
                    )

    def test_new_score_fixture_names(self):
        text_ocr.validate_ocr_engines("none", "tesseract")
        parser = text_ocr.FrameImageTextParser("auto", "none", "tesseract")
        cases = [
            (
                "new_score_200_010.jpg",
                "Carlos Wagner Rosa Pereira",
                "Ethan Roy Major",
            ),
            (
                "new_score_930_000.jpg",
                "Anabelle Pereira Dominico",
                "Rebeca de Lavor Tisatto",
            ),
            (
                "new_score_names.jpg",
                "Ana Julia Samara R. Lima",
                "Roberta Graciani Medeiros",
            ),
            (
                "new_score_names2.jpg",
                "Miranda Galban",
                "Yamé Cherici",
            ),
        ]

        for score_image, top_name, bottom_name in cases:
            with self.subTest(score_image=score_image):
                score_path = os.path.join(self.fixture_dir, score_image)
                self.assertTrue(
                    os.path.exists(score_path),
                    f"missing livestream OCR score fixture: {score_image}",
                )
                with open(score_path, "rb") as fileobj:
                    reading = parser.parse(0, fileobj.read(), None)

                self.assertEqual(reading.top_athlete_name, top_name)
                self.assertEqual(reading.bottom_athlete_name, bottom_name)

    def test_new_score_fixture_scores(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        parser = text_ocr.FrameImageTextParser("auto", "fixed_digit", "none")
        cases = [
            (
                "new_score_200_010.jpg",
                {
                    "top_points": 2,
                    "top_advantages": 0,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 1,
                    "bottom_penalties": 0,
                },
            ),
            (
                "new_score_930_000.jpg",
                {
                    "top_points": 9,
                    "top_advantages": 3,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 0,
                    "bottom_penalties": 0,
                },
            ),
        ]

        for score_image, expected_fields in cases:
            with self.subTest(score_image=score_image):
                score_path = os.path.join(self.fixture_dir, score_image)
                self.assertTrue(
                    os.path.exists(score_path),
                    f"missing livestream OCR score fixture: {score_image}",
                )
                with open(score_path, "rb") as fileobj:
                    reading = parser.parse(0, fileobj.read(), None)

                self.assertEqual(
                    reading.scoreboard_state,
                    text_scan.SCOREBOARD_STATE_VISIBLE,
                )
                for field_name, expected_value in expected_fields.items():
                    self.assertEqual(getattr(reading, field_name), expected_value)


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
                        "scoreboard_state": text_scan.SCOREBOARD_STATE_VISIBLE,
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
        self.assertEqual(
            body["events"][0]["scoreboard_state"], text_scan.SCOREBOARD_STATE_VISIBLE
        )
        self.assertEqual(body["events"][0]["top_points"], 2)
        self.assertEqual(body["events"][0]["evidence"], {"source": "test"})

        rescan = client.post(
            "/api/livestream_frame_archives/worker/"
            f"text_scan_segments/{segment_payload['id']}/rescan",
            json={},
            headers=headers,
        )
        self.assertEqual(rescan.status_code, 200)
        rescan_segment = rescan.get_json()["segment"]
        self.assertEqual(rescan_segment["status"], "running")
        self.assertEqual(rescan_segment["attempt_count"], 2)
        self.assertEqual(rescan_segment["event_count"], 0)
        self.assertEqual(len(rescan_segment["archive_capture_segments"]), 1)
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter_by(
                scan_segment_id=uuid.UUID(segment_payload["id"])
            ).count(),
            0,
        )

    def test_admin_text_event_display_rows_show_full_score_state(self):
        self._admin_client()
        admin_module = self.admin_module

        rows = admin_module._text_event_display_rows(
            [
                text_scan.TextEventData(
                    frame_second=0,
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                ),
                text_scan.TextEventData(frame_second=10, bottom_points=8),
                text_scan.TextEventData(
                    frame_second=15,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK,
                ),
                text_scan.TextEventData(
                    frame_second=18,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                ),
                text_scan.TextEventData(
                    frame_second=20,
                    timer_state="running",
                    timer_value="4:42",
                ),
                text_scan.TextEventData(frame_second=25, top_penalties=1),
            ]
        )

        self.assertTrue(rows[0].has_score_change)
        self.assertTrue(rows[1].has_score_change)
        self.assertTrue(rows[2].has_score_change)
        self.assertTrue(rows[2].is_scoreboard_blank)
        self.assertTrue(rows[3].has_score_change)
        self.assertFalse(rows[3].is_scoreboard_blank)
        self.assertFalse(rows[4].has_score_change)
        self.assertTrue(rows[5].has_score_change)
        self.assertEqual(rows[1].score.top_points, 0)
        self.assertEqual(rows[1].score.bottom_points, 8)
        self.assertEqual(rows[1].score.bottom_advantages, 0)
        self.assertIsNone(rows[2].score.bottom_points)
        self.assertEqual(rows[3].score.bottom_points, 0)
        self.assertEqual(rows[5].score.top_penalties, 1)
        self.assertEqual(rows[5].score.bottom_penalties, 0)


if __name__ == "__main__":
    unittest.main()
