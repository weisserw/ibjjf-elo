import io
import json
import os
import sys
import tarfile
import types
import unittest
import uuid
from datetime import datetime
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


def make_score_layout(name, boxes, roles=("green", "yellow", "red") * 2):
    colors = {
        "green": (38, 143, 45),
        "yellow": (158, 175, 33),
        "red": (171, 30, 49),
    }
    return text_ocr.ScoreLayout(
        name,
        tuple(
            text_ocr.ScoreCellRegion(
                row=index // 3,
                column=index % 3,
                role=role,
                bounds=box,
                region_mask=None,
                background_rgb=colors[role],
            )
            for index, (box, role) in enumerate(zip(boxes, roles))
        ),
    )


class LivestreamFrameTextScanAlgorithmTestCase(unittest.TestCase):
    def test_blank_scoreboard_event_clears_carried_names(self):
        state = text_scan.TextState(
            scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
            top_points=2,
            top_athlete_name="CAIO AYROSA MACZEY",
            top_team_name="Team Caio",
            bottom_athlete_name="PATRYK PRUCNAL",
            bottom_team_name="Team Patryk",
        )
        event = text_scan.TextEventData(
            frame_second=100,
            scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK,
        )

        next_state = text_scan.apply_event_to_state(state, event)

        self.assertIsNone(next_state.top_points)
        self.assertIsNone(next_state.top_athlete_name)
        self.assertIsNone(next_state.top_team_name)
        self.assertIsNone(next_state.bottom_athlete_name)
        self.assertIsNone(next_state.bottom_team_name)

    def test_scanner_reads_every_frame_to_find_score_change(self):
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
            debug_callback=debug_messages.append,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[1].top_points, 2)
        self.assertEqual(set(range(121)) - set(parser.calls), set())
        self.assertFalse(any("binary search" in item for item in debug_messages))
        self.assertFalse(any("coarse probe" in item for item in debug_messages))
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
            debug_callback=debug_messages.append,
        )

        self.assertEqual(events, [])
        self.assertFalse(any("binary search" in item for item in debug_messages))
        self.assertFalse(any("coarse probe" in item for item in debug_messages))

    def test_name_noise_does_not_emit_score_event_earlier(self):
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
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(events[0].top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[0].bottom_athlete_name, "TEST ATHLETE BETA")
        self.assertEqual(events[1].top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[1].bottom_athlete_name, "TEST ATHLETE BETA")

    def test_scanner_only_reads_names_for_score_timer_events(self):
        provider = DictFrameProvider()

        class SplitParser:
            def __init__(self):
                self.score_timer_calls = []
                self.full_calls = []

            def _reading(self, frame_second, include_names=False):
                fields = {
                    "top_points": 2 if frame_second >= 37 else 0,
                    "top_advantages": 0,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 0,
                    "bottom_penalties": 0,
                }
                if include_names:
                    fields.update(
                        {
                            "top_athlete_name": "TEST ATHLETE ALPHA",
                            "bottom_athlete_name": "TEST ATHLETE BETA",
                        }
                    )
                return text_scan.FrameReading(frame_second=frame_second, **fields)

            def parse_score_timer(self, frame_second, score_image, timer_image):
                self.score_timer_calls.append(frame_second)
                return self._reading(frame_second)

            def parse(self, frame_second, score_image, timer_image):
                self.full_calls.append(frame_second)
                return self._reading(frame_second, include_names=True)

        parser = SplitParser()

        events = text_scan.scan_frame_text_segment(
            provider,
            parser,
            0,
            121,
        )

        self.assertEqual([event.frame_second for event in events], [0, 37])
        self.assertEqual(parser.full_calls, [0, 37])
        self.assertEqual(parser.score_timer_calls, list(range(121)))
        self.assertEqual(events[1].top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(events[1].bottom_athlete_name, "TEST ATHLETE BETA")

    def test_initial_state_from_prior_segment_prevents_duplicate_first_frame_event(
        self,
    ):
        provider = DictFrameProvider()
        parser = TimelineParser(
            {
                120: {
                    "top_points": 2,
                    "top_advantages": 0,
                    "top_penalties": 0,
                    "bottom_points": 0,
                    "bottom_advantages": 0,
                    "bottom_penalties": 0,
                },
                125: {"top_points": 4},
            }
        )
        initial_state = text_scan.TextState(
            top_points=2,
            top_advantages=0,
            top_penalties=0,
            bottom_points=0,
            bottom_advantages=0,
            bottom_penalties=0,
            scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
        )

        events = text_scan.scan_frame_text_segment(
            provider,
            parser,
            120,
            130,
            initial_state=initial_state,
        )

        self.assertEqual([event.frame_second for event in events], [125])
        self.assertEqual(events[0].top_points, 4)

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
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "1:37")],
        )

    def test_stationary_under_one_minute_timer_emits_inferred_stop(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                remaining = 47 - frame_second if frame_second < 2 else 45
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=f"0:{remaining:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            6,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "0:47"), (4, "stopped", "0:45")],
        )
        self.assertEqual(
            events[-1].evidence["timer_state_inference"]["method"],
            "stationary_timer_digits",
        )
        self.assertEqual(
            events[-1].evidence["timer_state_inference"][
                "first_stationary_frame_second"
            ],
            2,
        )

    def test_stationary_under_one_minute_timer_emits_resume_when_digits_move(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                remaining_by_second = [48, 47, 46, 46, 46, 45, 44, 43]
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=f"0:{remaining_by_second[frame_second]:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            8,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [
                (0, "running", "0:48"),
                (4, "stopped", "0:46"),
                (5, "running", "0:45"),
            ],
        )
        self.assertEqual(
            events[-1].evidence["timer_state_inference"]["method"],
            "stationary_timer_digits_resumed",
        )

    def test_blank_boundary_estimates_stop_from_last_under_one_minute_reading(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                if frame_second == 2:
                    return text_scan.FrameReading(
                        frame_second=frame_second,
                        scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK,
                    )
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value=f"0:{47 - frame_second:02d}",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            3,
        )

        self.assertEqual(
            [
                (
                    event.frame_second,
                    event.scoreboard_state,
                    event.timer_state,
                    event.timer_value,
                )
                for event in events
            ],
            [
                (0, "visible", "running", "0:47"),
                (2, "blank", "stopped", "0:46"),
            ],
        )
        self.assertEqual(
            events[-1].evidence["timer_state_inference"]["method"],
            "terminal_boundary_extrapolation",
        )

    def test_blank_boundary_keeps_direct_stopped_zero_timer(self):
        provider = DictFrameProvider()

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                if frame_second == 1:
                    return text_scan.FrameReading(
                        frame_second=frame_second,
                        scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK,
                        timer_state="stopped",
                        timer_value="0:00",
                    )
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="0:01",
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            2,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "0:01"), (1, "stopped", "0:00")],
        )
        self.assertNotIn(
            "timer_state_inference",
            events[-1].evidence or {},
        )

    def test_running_timer_ocr_noise_does_not_emit_timer_only_events(self):
        provider = DictFrameProvider()
        noisy_values = {
            0: "2:45",
            1: "2:44",
            2: "2:48",
            3: "2:42",
            4: "2:89",
            5: "2:40",
            6: "2:39",
        }

        class TimerParser:
            def parse(self, frame_second, score_image, timer_image):
                return text_scan.FrameReading(
                    frame_second=frame_second,
                    timer_state="running",
                    timer_value=noisy_values[frame_second],
                )

        events = text_scan.scan_frame_text_segment(
            provider,
            TimerParser(),
            0,
            7,
        )

        self.assertEqual(
            [
                (event.frame_second, event.timer_state, event.timer_value)
                for event in events
            ],
            [(0, "running", "2:45")],
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

    def _archive_with_segments(self, status="success", youtube_video_id="HxZSos1k_MA"):
        archive = LivestreamFrameArchive(
            youtube_video_id=youtube_video_id,
            canonical_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            s3_prefix=f"livestream-frames/{youtube_video_id}/",
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

    def test_queue_text_scan_defaults_name_engine_to_paddle(self):
        archive, _ = self._archive_with_segments()

        text_scan.queue_text_scan(db.session, archive)
        db.session.commit()

        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        self.assertEqual(scan.name_engine, "paddle")

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

    def test_claim_next_text_scan_segment_uses_queue_requested_order(self):
        first_archive, _ = self._archive_with_segments(youtube_video_id="QueueFirst01")
        text_scan.queue_text_scan(
            db.session,
            first_archive,
            score_engine="none",
            queue_requested_at=datetime(2026, 1, 1, 12, 0, 1),
        )
        second_archive, _ = self._archive_with_segments(youtube_video_id="QueueSecond1")
        text_scan.queue_text_scan(
            db.session,
            second_archive,
            score_engine="none",
            queue_requested_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        db.session.commit()

        segment = text_scan.claim_next_text_scan_segment(db.session)

        self.assertEqual(segment.archive_id, second_archive.id)

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

    def test_reset_text_scan_for_rescan_requeues_all_segments_and_deletes_events(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        text_scan.mark_text_scan_segment_success(
            db.session,
            segments[0],
            [text_scan.TextEventData(frame_second=0, timer_state="running")],
        )
        segments[1].attempt_count = 3
        segments[1].status = "error"
        segments[1].event_count = 2
        segments[1].last_processed_second = 180
        segments[1].last_error = "ocr failed"
        db.session.commit()

        reset_scan = text_scan.reset_text_scan_for_rescan(db.session, scan.id)
        db.session.commit()

        self.assertEqual(reset_scan.id, scan.id)
        self.assertEqual(reset_scan.status, "queued")
        self.assertEqual(reset_scan.processed_segment_count, 0)
        self.assertIsNone(reset_scan.last_processed_second)
        self.assertIsNone(reset_scan.last_error)
        self.assertIsNone(reset_scan.started_at)
        self.assertIsNone(reset_scan.completed_at)
        self.assertEqual(LivestreamFrameTextEvent.query.count(), 0)
        reset_segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        self.assertEqual(
            [segment.status for segment in reset_segments],
            ["queued", "queued"],
        )
        self.assertEqual([segment.attempt_count for segment in reset_segments], [0, 0])
        self.assertEqual([segment.event_count for segment in reset_segments], [0, 0])
        self.assertEqual(
            [segment.last_processed_second for segment in reset_segments],
            [None, None],
        )
        self.assertEqual(
            [segment.last_error for segment in reset_segments],
            [None, None],
        )

    def test_reset_text_scan_for_rescan_rejects_running_segments(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segment = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).first()
        text_scan.mark_text_scan_segment_success(
            db.session,
            segment,
            [text_scan.TextEventData(frame_second=0, timer_state="running")],
        )
        segment.status = "running"
        db.session.commit()

        with self.assertRaisesRegex(ValueError, "segments are running"):
            text_scan.reset_text_scan_for_rescan(db.session, scan.id)

        self.assertEqual(LivestreamFrameTextEvent.query.count(), 1)

    def test_retry_and_cancel_text_scan_segments_accept_status_filters(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        segments[0].status = "error"
        segments[1].status = "cancelled"
        db.session.commit()

        retry_count = text_scan.retry_failed_text_scan_segments(
            db.session, [scan.id], ["error"]
        )
        db.session.commit()

        self.assertEqual(retry_count, 1)
        self.assertEqual(
            [segment.status for segment in segments],
            ["queued", "cancelled"],
        )

        cancel_count = text_scan.cancel_queued_text_scan_segments(
            db.session, [scan.id], ["queued"]
        )
        db.session.commit()

        self.assertEqual(cancel_count, 1)
        self.assertEqual(
            [segment.status for segment in segments],
            ["cancelled", "cancelled"],
        )

    def test_clear_text_scan_events_deletes_events_and_clears_match_links(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        for index, segment in enumerate(segments):
            segment.event_count = 1
            segment.status = "success" if index == 0 else "queued"
            segment.last_processed_second = segment.end_second - 1
            db.session.add(
                LivestreamFrameTextEvent(
                    scan_id=scan.id,
                    archive_id=archive.id,
                    scan_segment_id=segment.id,
                    capture_segment_id=segment.capture_segment_id,
                    frame_second=index,
                )
            )
        db.session.commit()

        with mock.patch(
            "livestream_match_linking.clear_livestream_match_links",
            return_value={"matches": 1, "participants": 2, "associations": 3},
        ) as clear_links:
            summary = text_scan.clear_text_scan_events(db.session, [scan.id])
        db.session.commit()

        self.assertEqual(
            summary,
            {
                "events": 2,
                "segments": 2,
                "matches": 1,
                "participants": 2,
                "associations": 3,
            },
        )
        clear_links.assert_called_once_with(db.session, archive.id)
        self.assertEqual(LivestreamFrameTextEvent.query.count(), 0)
        self.assertEqual([segment.event_count for segment in segments], [0, 0])
        self.assertEqual(
            [segment.status for segment in segments],
            ["pending", "pending"],
        )
        self.assertEqual(
            [segment.last_processed_second for segment in segments],
            [None, None],
        )
        self.assertEqual(scan.status, "pending")

    def test_clear_text_scan_events_creates_newly_archived_segments(self):
        archive, capture_segments = self._archive_with_segments()
        capture_segments[1].status = "queued"
        db.session.commit()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        self.assertEqual(len(scan.segments), 1)

        capture_segments[1].status = "success"
        db.session.commit()

        summary = text_scan.clear_text_scan_events(db.session, [scan.id])
        db.session.commit()

        segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        self.assertEqual(summary["segments"], 2)
        self.assertEqual(len(segments), 2)
        self.assertEqual(
            [segment.status for segment in segments], ["pending", "pending"]
        )
        self.assertEqual(scan.total_segment_count, 2)
        self.assertEqual(scan.status, "pending")

    def test_clear_text_scan_events_leaves_successful_scan_unclaimable(self):
        archive, _ = self._archive_with_segments()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segments = LivestreamFrameTextScanSegment.query.order_by(
            LivestreamFrameTextScanSegment.start_second
        ).all()
        for segment in segments:
            segment.status = "success"
        text_scan.recompute_text_scan_status(db.session, scan)
        db.session.commit()

        text_scan.clear_text_scan_events(db.session, [scan.id])
        db.session.commit()

        self.assertEqual(
            [segment.status for segment in segments], ["pending", "pending"]
        )
        self.assertEqual(scan.status, "pending")
        self.assertIsNone(text_scan.claim_next_text_scan_segment(db.session))
        self.assertEqual(
            [segment.status for segment in segments], ["pending", "pending"]
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


class ScanLivestreamFrameTextAdminApiStateTestCase(unittest.TestCase):
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
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    def test_replay_safe_update_retries_transient_connection_error(self):
        fake_session = self.FakeSession(
            [
                runner.requests.exceptions.ConnectionError("connection closed"),
                self.FakeResponse(
                    payload={
                        "segment": {
                            "id": "segment-1",
                            "status": "error",
                            "last_error": "OCR failed",
                        }
                    }
                ),
            ]
        )
        state = runner.AdminApiTextScanState(
            "https://admin.example.com", "secret", session=fake_session
        )
        segment = runner.ApiObject({"id": "segment-1", "status": "running"})

        with mock.patch("livestream_admin_api.time.sleep") as sleep:
            state.mark_error(segment, "OCR failed")

        self.assertEqual(segment.status, "error")
        self.assertEqual(len(fake_session.requests), 2)
        sleep.assert_called_once_with(1)

    def test_claim_does_not_retry_transient_connection_error(self):
        fake_session = self.FakeSession(
            [
                runner.requests.exceptions.ConnectionError("connection closed"),
                self.FakeResponse(payload={"segment": None}),
            ]
        )
        state = runner.AdminApiTextScanState(
            "https://admin.example.com", "secret", session=fake_session
        )

        with self.assertRaises(runner.requests.exceptions.ConnectionError):
            state.claim_next_segment()

        self.assertEqual(len(fake_session.requests), 1)


class ScanLivestreamFrameTextWorkerTestCase(unittest.TestCase):
    def _name_parser(self, name_engine):
        parser = text_ocr.FrameImageTextParser.__new__(text_ocr.FrameImageTextParser)
        parser.name_engine = name_engine
        return parser

    @staticmethod
    def _name_layout(image_size=(320, 140)):
        width, height = image_size
        grid_left = max(1, width // 2)
        row_height = max(1, int(height * 0.4))
        gap = max(1, int(height * 0.03))
        bottom_top = min(height - 1, row_height + gap)
        bottom_bottom = min(height, bottom_top + row_height)
        cell_width = max(1, (width - grid_left) // 3)
        boxes = tuple(
            (
                grid_left + column * cell_width,
                row_top,
                min(width, grid_left + (column + 1) * cell_width),
                row_bottom,
            )
            for row_top, row_bottom in (
                (0, row_height),
                (bottom_top, bottom_bottom),
            )
            for column in range(3)
        )
        return text_ocr._name_regions_from_score_layout(
            image_size,
            make_score_layout(
                "test",
                boxes,
                ("green", "yellow", "red") * 2,
            ),
        )

    def test_name_regions_derive_from_detected_score_rows(self):
        layout = make_score_layout(
            "synthetic",
            (
                (60, -2, 70, 28),
                (70, 0, 80, 30),
                (80, 1, 90, 29),
                (59, 34, 69, 84),
                (69, 35, 79, 82),
                (79, 36, 89, 83),
            ),
            ("green", "yellow", "red") * 2,
        )

        name_layout = text_ocr._name_regions_from_score_layout((100, 80), layout)

        self.assertEqual(name_layout.column_box, (0, 0, 59, 80))
        self.assertEqual(name_layout.row_boundary, 32)
        self.assertEqual(name_layout.reference_row_height, 46)
        self.assertFalse(name_layout.use_scaled_retry)
        for box in (
            name_layout.column_box,
            *name_layout.line_boxes,
            *name_layout.expanded_row_boxes,
        ):
            self.assertGreater(box[2], box[0])
            self.assertGreater(box[3], box[1])
            self.assertGreaterEqual(box[0], 0)
            self.assertGreaterEqual(box[1], 0)
            self.assertLessEqual(box[2], 100)
            self.assertLessEqual(box[3], 80)

    def test_name_region_compactness_uses_detected_row_height(self):
        def layout_with_height(row_height):
            boxes = tuple(
                (60 + column * 10, top, 70 + column * 10, top + row_height)
                for top in (0, row_height + 2)
                for column in range(3)
            )
            return text_ocr._name_regions_from_score_layout(
                (120, row_height * 2 + 4),
                make_score_layout(
                    "synthetic",
                    boxes,
                    ("green", "yellow", "red") * 2,
                ),
            )

        self.assertTrue(
            layout_with_height(
                text_ocr.PADDLE_SCALED_RETRY_MAX_ROW_HEIGHT
            ).use_scaled_retry
        )
        self.assertFalse(
            layout_with_height(
                text_ocr.PADDLE_SCALED_RETRY_MAX_ROW_HEIGHT + 1
            ).use_scaled_retry
        )

    def test_name_regions_reject_invalid_cell_count(self):
        layout = make_score_layout(
            "invalid",
            ((10, 10, 20, 20),),
            ("green",),
        )

        with self.assertRaisesRegex(ValueError, "exactly six"):
            text_ocr._name_regions_from_score_layout((100, 80), layout)

    def test_parse_args_defaults_name_engine_to_paddle(self):
        args = runner.parse_args([])

        self.assertEqual(args.name_engine, "paddle")
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
            segment,
            state,
            "parser",
            "s3",
            "bucket",
        )

    def test_run_with_rescan_from_start_resets_scan_before_claiming(self):
        archive_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        segment = runner.ApiObject(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "archive_id": archive_id,
                "start_second": 0,
                "end_second": 60,
            }
        )

        class FakeState:
            def __init__(self):
                self.reset_archive_id = None
                self.claim_kwargs = None

            def reset_archive(self, reset_archive_id, background_task_id=None):
                self.reset_archive_id = reset_archive_id
                return runner.ApiObject({"archive_id": str(reset_archive_id)})

            def claim_next_segment(self, **kwargs):
                self.claim_kwargs = kwargs
                return segment

        args = runner.parse_args(
            [
                "--archive-id",
                archive_id,
                "--rescan-from-start",
                "--score-engine",
                "none",
            ]
        )
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
        self.assertEqual(str(state.reset_archive_id), archive_id)
        self.assertEqual(str(state.claim_kwargs["archive_id"]), archive_id)
        process_segment.assert_called_once_with(
            segment,
            state,
            "parser",
            "s3",
            "bucket",
        )

    def test_name_parser_reads_names_from_scoreboard_text(self):
        parser = self._name_parser(name_engine="paddle")

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

    def test_name_parser_strips_score_junk_from_name_lines(self):
        parser = self._name_parser(name_engine="paddle")

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

    def test_name_parser_ignores_short_junk_name_lines(self):
        parser = self._name_parser(name_engine="paddle")

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

    def test_name_parser_keeps_accented_four_token_names(self):
        parser = self._name_parser(name_engine="paddle")

        self.assertEqual(
            parser._clean_name_line("JOÄO MANOEL DOS SA..."),
            "JOÄO MANOEL DOS SA",
        )

    def test_name_parser_uses_blank_lines_as_name_boundaries(self):
        parser = self._name_parser(name_engine="paddle")

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

    def test_name_parser_handles_split_team_lines_in_rendered_scoreboard(self):
        parser = self._name_parser(name_engine="paddle")

        cases = [
            (
                "\n".join(
                    [
                        "Carlos",
                        "Wagner Rosa Pereira",
                        "Nova União",
                        "Ethan Roy Major",
                        "Jiu-Jitsu For Life Team",
                    ]
                ),
                "Carlos Wagner Rosa Pereira",
                "Ethan Roy Major",
            ),
            (
                "\n".join(
                    [
                        "Miranda Galban",
                        "Nexo Jiu-Jitsu",
                        "Yamé Cherici",
                        "BJJ College",
                    ]
                ),
                "Miranda Galban",
                "Yamé Cherici",
            ),
            (
                "\n".join(
                    [
                        "Ana Paula Lopes de Moraes",
                        "Pro Training Brazilian Jiu Jitsu",
                        "Roberta Graciani Medeiros",
                        "Alliance",
                    ]
                ),
                "Ana Paula Lopes de Moraes",
                "Roberta Graciani Medeiros",
            ),
            (
                "\n".join(
                    [
                        "Miranda Galban",
                        "",
                        "Nexo Jiu-Jitsu",
                        "",
                        "Yamé Cherici",
                        "",
                        "BJJ College",
                    ]
                ),
                "Miranda Galban",
                "Yamé Cherici",
            ),
            (
                "\n".join(
                    [
                        "Miranda Galban",
                        "",
                        "Nexo Jiu-Jitsu",
                        "",
                        "Anabelle Pereira Dominico",
                        "Gracie Barra",
                    ]
                ),
                "Miranda Galban",
                "Anabelle Pereira Dominico",
            ),
        ]

        for text, top_name, bottom_name in cases:
            with self.subTest(bottom_name=bottom_name):
                fields = parser._parse_names(text, allow_two_line_fallback=False)

                self.assertEqual(
                    fields,
                    {
                        "top_athlete_name": top_name,
                        "bottom_athlete_name": bottom_name,
                    },
                )

    def test_name_parser_does_not_infer_rendered_scoreboard_from_three_lines(self):
        parser = self._name_parser(name_engine="paddle")

        fields = parser._parse_names(
            "\n".join(
                [
                    "Ana Paula Lopes de Moraes",
                    "Pro Training Brazilian Jiu Jitsu",
                    "Roberta Graciani Medeiros",
                ]
            ),
            allow_two_line_fallback=False,
        )

        self.assertEqual(fields, {})

    def test_name_parser_reads_victory_screen(self):
        parser = self._name_parser(name_engine="paddle")

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

    def test_name_parser_reads_cropped_victory_screen(self):
        parser = self._name_parser(name_engine="paddle")

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

        parser = self._name_parser(name_engine="tesseract")
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
                "",
                "",
            ]
        )
        score_image = FakeScoreImage()

        scoreboard_text, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )
        self.assertIn("TEST ATHLETE GAMMA-RAY", scoreboard_text)
        self.assertEqual(score_image.boxes[0], (0, 0, 160, 116))
        self.assertEqual(len(score_image.boxes), 3)
        parser._ocr.assert_has_calls(
            [
                mock.call("prepared-crop-1", "--psm 6"),
                mock.call("prepared-crop-2", "--psm 7"),
                mock.call("prepared-crop-2", "--psm 6"),
                mock.call("prepared-crop-3", "--psm 7"),
                mock.call("prepared-crop-3", "--psm 6"),
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

        parser = self._name_parser(name_engine="tesseract")
        parser._prepare_name_ocr_image = lambda image: f"prepared-{image}"
        parser._ocr = mock.Mock(
            side_effect=[
                "\n".join(["TEST ATHLETE GAMMA-RAY", "SAMPLE TEAM ONE"]),
                "TEST ATHLETE GAMMA-RAY",
                "TEST ATHLETE DELTA",
            ]
        )
        score_image = FakeScoreImage()

        scoreboard_text, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

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

        parser = self._name_parser(name_engine="tesseract")
        parser._prepare_name_ocr_image = lambda image: f"prepared-{image}"
        parser._ocr = mock.Mock(
            side_effect=["", "TEST ATHLETE GAMMA-RAY", "TEST ATHLETE DELTA"]
        )
        score_image = FakeScoreImage()

        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE GAMMA-RAY",
                "bottom_athlete_name": "TEST ATHLETE DELTA",
            },
        )
        self.assertEqual(len(score_image.boxes), 3)
        self.assertLessEqual(max(box[2] for box in score_image.boxes), 160)
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

        parser = self._name_parser(name_engine="tesseract")
        parser._prepare_name_ocr_image = lambda image: image
        parser._ocr = mock.Mock(side_effect=["", "TEST ATHLETE GAMMA-RAY", "", "", ""])

        score_image = FakeScoreImage()
        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(fields, {})

    def test_name_parser_skips_names_when_name_engine_disabled(self):
        parser = self._name_parser(name_engine=None)

        self.assertEqual(parser._parse_names("TEST ATHLETE ALPHA\n0 0 0"), {})

    def test_paddle_name_parser_keeps_particle_heavy_names(self):
        parser = self._name_parser(name_engine="paddle")

        self.assertEqual(
            parser._name_from_paddle_item_text("DAVI DE SA DA CRUZ"),
            "DAVI DE SA DA CRUZ",
        )

    def test_paddle_parser_extracts_text_from_legacy_result_shape(self):
        result = [
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], ("TEST ATHLETE ALPHA", 0.91)],
                [[[0, 30], [100, 30], [100, 50], [0, 50]], ("TEST ATHLETE BETA", 0.87)],
            ]
        ]

        self.assertEqual(
            text_ocr.FrameImageTextParser._paddle_text_items(result),
            [("TEST ATHLETE ALPHA", 0.91), ("TEST ATHLETE BETA", 0.87)],
        )

    def test_paddle_parser_extracts_text_from_dict_result_shape(self):
        result = {"rec_texts": ["TEST ATHLETE ALPHA", "TEST ATHLETE BETA"]}

        self.assertEqual(
            text_ocr.FrameImageTextParser._paddle_text_items(result),
            [("TEST ATHLETE ALPHA", None), ("TEST ATHLETE BETA", None)],
        )

    def test_paddle_parser_groups_boxed_text_by_scoreboard_rows(self):
        class FakeScoreImage:
            size = (480, 216)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_ocr_result = mock.Mock(
            return_value={
                "rec_texts": [
                    "CHRISTIAN MACEDO V. ...",
                    "G13 BJJ",
                    "MATEUS VICTOR OLIVE..",
                    "RYAN GRACIE TEAM",
                ],
                "rec_scores": [0.95, 0.98, 0.94, 0.97],
                "rec_boxes": [
                    [14, 14, 218, 31],
                    [12, 36, 66, 49],
                    [15, 107, 219, 125],
                    [15, 128, 174, 140],
                ],
            }
        )

        score_image = FakeScoreImage()
        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "CHRISTIAN MACEDO",
                "bottom_athlete_name": "MATEUS VICTOR OLIVE",
            },
        )
        parser._paddle_ocr_result.assert_called_once()

    def test_paddle_parser_prefers_upper_name_line_over_lower_team_line(self):
        parser = self._name_parser(name_engine="paddle")

        name = parser._best_paddle_row_name(
            [
                text_ocr.PaddleTextItem(
                    "VICTOR MANOEL DE OL...",
                    0.97,
                    (12.0, 108.0, 215.0, 128.0),
                ),
                text_ocr.PaddleTextItem(
                    "TRATRCS BRAZILIANJIL-JITSU",
                    0.94,
                    (15.0, 133.0, 136.0, 140.0),
                ),
            ]
        )

        self.assertEqual(name, "VICTOR MANOEL")

    def test_paddle_parser_groups_split_words_before_selecting_name_line(self):
        parser = self._name_parser(name_engine="paddle")

        name = parser._best_paddle_row_name(
            [
                text_ocr.PaddleTextItem("Stephany", 0.98, (14.0, 31.0, 91.0, 51.0)),
                text_ocr.PaddleTextItem(
                    "Oliveira",
                    0.98,
                    (149.0, 31.0, 213.0, 48.0),
                ),
                text_ocr.PaddleTextItem("Correa", 0.98, (91.0, 32.0, 148.0, 49.0)),
                text_ocr.PaddleTextItem(
                    "DKM Jiu-Jitsu",
                    0.99,
                    (13.0, 53.0, 99.0, 69.0),
                ),
            ]
        )

        self.assertEqual(name, "Stephany Correa Oliveira")

    def test_paddle_item_name_cleanup_only_drops_clipped_trailing_initials(self):
        parser = self._name_parser(name_engine="paddle")

        self.assertEqual(
            parser._name_from_paddle_item_text("CHRISTIAN MACEDO V. ..."),
            "CHRISTIAN MACEDO",
        )
        self.assertEqual(
            parser._name_from_paddle_item_text("GUSTAVO HENRIQUE B."),
            "GUSTAVO HENRIQUE B",
        )

    def test_paddle_parser_uses_paddle_reader_for_name_ocr(self):
        class FakePaddleReader:
            def __init__(self):
                self.calls = []

            def ocr(self, image, cls=True):
                self.calls.append((image, cls))
                return [[[[0, 0], [1, 0], [1, 1], [0, 1]], ("TEST ATHLETE ALPHA", 0.9)]]

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_ocr = FakePaddleReader()

        text = parser._ocr("image")

        self.assertEqual(text, "TEST ATHLETE ALPHA")
        self.assertEqual(parser._paddle_ocr.calls, [("image", True)])

    def test_paddle_parser_reads_name_column_once_when_text_detected(self):
        class FakeScoreImage:
            size = (500, 140)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_box_name_fields = mock.Mock(return_value=("", {}))
        parser._prepare_name_ocr_image = mock.Mock(
            side_effect=AssertionError("unexpected name OCR preprocessing")
        )
        parser._ocr = mock.Mock(
            return_value="TEST ATHLETE ALPHA\n0 0 0\nTEST ATHLETE BETA\n2 0 0"
        )

        score_image = FakeScoreImage()
        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        parser._ocr.assert_called_once()

    def test_paddle_parser_reuses_primary_crop_result_during_column_fallback(self):
        class FakePaddleReader:
            def __init__(self):
                self.calls = []
                self.results = [
                    {
                        "rec_texts": ["TEST ATHLETE ALPHA"],
                        "rec_scores": [0.95],
                        "rec_boxes": [[1, 1, 80, 12]],
                    },
                    {
                        "rec_texts": [
                            "TEST ATHLETE ALPHA",
                            "0 0 0",
                            "TEST ATHLETE BETA",
                            "2 0 0",
                        ],
                        "rec_scores": [0.95, 0.99, 0.96, 0.99],
                    },
                ]

            def ocr(self, image, cls=True):
                self.calls.append((image, cls))
                return self.results[len(self.calls) - 1]

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_ocr = FakePaddleReader()
        parser._paddle_row_name_fields = mock.Mock(
            return_value=(
                "TEST ATHLETE ALPHA\nTEST ATHLETE BETA",
                {
                    "top_athlete_name": "TEST ATHLETE ALPHA",
                    "bottom_athlete_name": "TEST ATHLETE BETA",
                },
            )
        )
        score_image = text_ocr.Image.new("RGB", (172, 78), "white")

        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        self.assertEqual(len(parser._paddle_ocr.calls), 1)
        parser._paddle_row_name_fields.assert_called_once()

    def test_paddle_row_parser_skips_scaled_retries_when_base_results_agree(self):
        class FakeScoreImage:
            size = (172, 78)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._prepare_paddle_retry_image = lambda image: ("gray", image)
        parser._prepare_paddle_scaled_retry_image = mock.Mock(
            side_effect=lambda image: ("scaled", image)
        )
        parser._ocr = mock.Mock(
            side_effect=[
                "TEST ATHLETE ALPHA",
                "TEST ATHLETE ALPHA",
                "TEST ATHLETE BETA",
                "TEST ATHLETE BETA",
            ]
        )

        score_image = FakeScoreImage()
        _, fields = parser._paddle_row_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        self.assertEqual(parser._ocr.call_count, 4)
        parser._prepare_paddle_scaled_retry_image.assert_not_called()

    def test_paddle_row_parser_keeps_scaled_retry_for_incomplete_base_results(self):
        class FakeScoreImage:
            size = (172, 78)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._prepare_paddle_retry_image = lambda image: ("gray", image)
        parser._prepare_paddle_scaled_retry_image = mock.Mock(
            side_effect=lambda image: ("scaled", image)
        )
        parser._ocr = mock.Mock(
            side_effect=[
                "TEST ATHLETE ALPHA",
                "",
                "TEST ATHLETE ALPHA",
                "TEST ATHLETE BETA",
                "TEST ATHLETE BETA",
            ]
        )

        score_image = FakeScoreImage()
        _, fields = parser._paddle_row_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        self.assertEqual(parser._ocr.call_count, 5)
        parser._prepare_paddle_scaled_retry_image.assert_called_once()

    def test_paddle_direct_row_parser_batches_compact_variants(self):
        recognition_calls = []

        def recognize(images):
            recognition_calls.append(images)
            return iter(
                [
                    {"rec_text": "TEST ATHLETE ALPHA", "rec_score": 0.98},
                    {"rec_text": "TEST ATHLETE ALPHA", "rec_score": 0.99},
                    {"rec_text": "TEST ATHLETE ALPHA", "rec_score": 0.99},
                    {"rec_text": "Test Athlete Beta", "rec_score": 0.90},
                    {"rec_text": "TEST ATHLETE BETA", "rec_score": 0.98},
                    {"rec_text": "TEST ATHLETE BETA", "rec_score": 0.97},
                    {"rec_text": "TEST ATHLETE BETA", "rec_score": 0.99},
                ]
            )

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_ocr = types.SimpleNamespace(
            paddlex_pipeline=types.SimpleNamespace(text_rec_model=recognize)
        )
        score_image = text_ocr.Image.new("RGB", (172, 78), "white")
        name_layout = self._name_layout(score_image.size)

        _, fields = parser._paddle_direct_row_name_fields(score_image, name_layout)

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        self.assertEqual(len(recognition_calls), 1)
        self.assertEqual(len(recognition_calls[0]), 7)
        expanded_bottom = name_layout.expanded_row_boxes[1]
        self.assertEqual(
            recognition_calls[0][5].shape[:2],
            (
                (expanded_bottom[3] - expanded_bottom[1])
                * text_ocr.PADDLE_ROW_NAME_RETRY_SCALE,
                (expanded_bottom[2] - expanded_bottom[0])
                * text_ocr.PADDLE_ROW_NAME_RETRY_SCALE,
            ),
        )

    def test_paddle_direct_row_parser_falls_back_without_recognition_model(self):
        parser = self._name_parser(name_engine="paddle")
        parser._paddle_ocr = object()
        parser._paddle_box_name_fields = mock.Mock(
            return_value=(
                "TEST ATHLETE ALPHA\nTEST ATHLETE BETA",
                {
                    "top_athlete_name": "TEST ATHLETE ALPHA",
                    "bottom_athlete_name": "TEST ATHLETE BETA",
                },
            )
        )
        score_image = text_ocr.Image.new("RGB", (172, 78), "white")

        _, fields = parser._paddle_name_fields(
            score_image,
            self._name_layout(score_image.size),
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        parser._paddle_box_name_fields.assert_called_once()

    def test_name_cache_uses_only_pixels_read_by_name_ocr(self):
        parser = self._name_parser(name_engine="paddle")
        parser._name_cache = {}
        parser._ocr_name_fields = mock.Mock(
            return_value=(
                "TEST ATHLETE ALPHA\nTEST ATHLETE BETA",
                {
                    "top_athlete_name": "TEST ATHLETE ALPHA",
                    "bottom_athlete_name": "TEST ATHLETE BETA",
                },
            )
        )
        first_image = text_ocr.Image.new("RGB", (172, 78), "white")
        score_only_change = first_image.copy()
        score_only_change.putpixel((160, 60), (0, 0, 0))

        name_layout = self._name_layout(first_image.size)
        parser._cached_name_fields(b"frame-1", first_image, name_layout)
        parser._cached_name_fields(b"frame-2", score_only_change, name_layout)

        parser._ocr_name_fields.assert_called_once()

        name_change = score_only_change.copy()
        name_change.putpixel((10, 10), (0, 0, 0))
        parser._cached_name_fields(b"frame-3", name_change, name_layout)

        self.assertEqual(parser._ocr_name_fields.call_count, 2)

        shifted_layout = text_ocr.NameRegionLayout(
            column_box=(
                name_layout.column_box[0],
                name_layout.column_box[1],
                name_layout.column_box[2] - 1,
                name_layout.column_box[3],
            ),
            line_boxes=tuple(
                (box[0], box[1], box[2] - 1, box[3]) for box in name_layout.line_boxes
            ),
            expanded_row_boxes=tuple(
                (box[0], box[1], box[2] - 1, box[3])
                for box in name_layout.expanded_row_boxes
            ),
            row_boundary=name_layout.row_boundary,
            reference_row_height=name_layout.reference_row_height,
            use_scaled_retry=name_layout.use_scaled_retry,
        )
        parser._cached_name_fields(b"frame-4", name_change, shifted_layout)

        self.assertEqual(parser._ocr_name_fields.call_count, 3)

    def test_paddle_parser_retries_incomplete_name_column_with_preprocessing(self):
        class FakeScoreImage:
            size = (500, 140)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_box_name_fields = mock.Mock(return_value=("", {}))
        parser._prepare_paddle_retry_image = lambda image: ("retry", image)
        parser._ocr = mock.Mock(
            side_effect=[
                "TEST ATHLETE ALPHA",
                "TEST ATHLETE ALPHA\n0 0 0\nTEST ATHLETE BETA\n2 0 0",
            ]
        )

        score_image = FakeScoreImage()
        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "TEST ATHLETE ALPHA",
                "bottom_athlete_name": "TEST ATHLETE BETA",
            },
        )
        self.assertEqual(parser._ocr.call_count, 2)

    def test_paddle_parser_falls_back_to_row_crops_when_column_text_has_teams(self):
        class FakeScoreImage:
            size = (480, 216)

            def crop(self, box):
                return box

        parser = self._name_parser(name_engine="paddle")
        parser._paddle_box_name_fields = mock.Mock(return_value=("", {}))
        parser._prepare_paddle_retry_image = lambda image: ("retry", image)
        parser._ocr = mock.Mock(
            side_effect=[
                "CHRISTIAN MACEDO V. ...\n"
                "G13 BJJ\n"
                "MATEUS VICTOR OLIVE..\n"
                "RYAN GRACIE TEAM",
                "",
                "CHRISTIAN MACEDO V. ..",
                "MATEUS VICTOR OLIVE..",
            ]
        )

        score_image = FakeScoreImage()
        _, fields = parser._ocr_name_fields(
            score_image, self._name_layout(score_image.size)
        )

        self.assertEqual(
            fields,
            {
                "top_athlete_name": "CHRISTIAN MACEDO",
                "bottom_athlete_name": "MATEUS VICTOR OLIVE",
            },
        )

    def test_paddle_parser_disables_mkldnn_and_uses_v5_models(self):
        created_kwargs = []

        class FakePaddleOCR:
            def __init__(self, **kwargs):
                created_kwargs.append(kwargs)

        parser = self._name_parser(name_engine="paddle")
        with mock.patch.dict(
            sys.modules,
            {"paddleocr": types.SimpleNamespace(PaddleOCR=FakePaddleOCR)},
        ):
            reader = parser._paddle_reader()

        self.assertIsInstance(reader, FakePaddleOCR)
        self.assertEqual(created_kwargs[0]["ocr_version"], "PP-OCRv5")
        self.assertFalse(created_kwargs[0]["enable_mkldnn"])
        self.assertFalse(created_kwargs[0]["use_textline_orientation"])
        self.assertEqual(os.environ["FLAGS_use_mkldnn"], "0")
        self.assertEqual(os.environ["FLAGS_use_onednn"], "0")

    def test_frame_image_parser_name_only_mode_does_not_emit_score_or_timer(self):
        parser = self._name_parser(name_engine="paddle")
        parser.parser_profile = "auto"
        parser.score_engine = "none"
        parser.score_reader = None
        parser.timer_reader = None
        parser._image_from_bytes = lambda image_bytes: image_bytes
        score_image = text_ocr.Image.new("RGB", (320, 140), "white")
        score_layout = make_score_layout(
            "test",
            tuple(
                (160 + column * 40, row_top, 200 + column * 40, row_top + 56)
                for row_top in (0, 60)
                for column in range(3)
            ),
            ("green", "yellow", "red") * 2,
        )
        parser.scoreboard_locator = mock.Mock()
        parser.scoreboard_locator.locate.return_value = score_layout
        parser._cached_name_fields = mock.Mock(
            return_value=(
                "TEST ATHLETE ALPHA\nTEST ATHLETE BETA",
                {
                    "top_athlete_name": "TEST ATHLETE ALPHA",
                    "bottom_athlete_name": "TEST ATHLETE BETA",
                },
            )
        )

        reading = parser.parse(12, score_image, b"timer")

        self.assertEqual(reading.top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(reading.bottom_athlete_name, "TEST ATHLETE BETA")
        self.assertIsNone(reading.top_points)
        self.assertIsNone(reading.timer_state)
        parser.scoreboard_locator.locate.assert_called_once_with(score_image)

    def test_frame_image_parser_rejects_ordinary_names_without_layout(self):
        parser = self._name_parser(name_engine="paddle")
        parser.parser_profile = "auto"
        parser.score_engine = "fixed_digit"
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser.score_reader = mock.Mock()
        parser.score_reader.read.return_value = text_ocr.ScoreboardDigitReading(
            None,
            tuple(text_ocr.DigitPrediction(None, 0.0, "none") for _ in range(6)),
            False,
        )
        parser.timer_reader = None
        parser.scoreboard_locator = mock.Mock()
        parser._ocr_name_fields = mock.Mock(
            side_effect=AssertionError("ordinary name OCR must be skipped")
        )
        parser._ocr = mock.Mock(return_value="TEST ATHLETE ALPHA\nTEST ATHLETE BETA")
        score_image = text_ocr.Image.new("RGB", (320, 140), "white")

        reading = parser.parse(12, score_image, None)

        self.assertEqual(reading.scoreboard_state, text_scan.SCOREBOARD_STATE_BLANK)
        self.assertIsNone(reading.top_athlete_name)
        self.assertIsNone(reading.bottom_athlete_name)
        parser._ocr_name_fields.assert_not_called()
        parser._ocr.assert_called_once_with(score_image, "--psm 6")
        parser.scoreboard_locator.locate.assert_not_called()

    def test_frame_image_parser_accepts_only_victory_names_without_layout(self):
        parser = self._name_parser(name_engine="paddle")
        parser.parser_profile = "auto"
        parser.score_engine = "none"
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser.score_reader = None
        parser.timer_reader = None
        parser.scoreboard_locator = mock.Mock()
        parser.scoreboard_locator.locate.return_value = None
        parser._ocr = mock.Mock(
            return_value="Victory\nTEST ATHLETE WINNER\nSAMPLE TEAM BJJ"
        )
        score_image = text_ocr.Image.new("RGB", (320, 140), "white")

        reading = parser.parse(12, score_image, None)

        self.assertEqual(reading.top_athlete_name, "Victory")
        self.assertEqual(reading.bottom_athlete_name, "TEST ATHLETE WINNER")
        self.assertEqual(reading.bottom_team_name, "SAMPLE TEAM BJJ")
        self.assertIsNone(reading.scoreboard_state)
        parser._ocr.assert_called_once_with(score_image, "--psm 6")

    def test_frame_image_parser_uses_fixed_digit_readers_for_score_and_timer(self):
        parser = self._name_parser(name_engine="paddle")
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

    def test_frame_image_parser_caches_score_timer_and_name_reads(self):
        parser = self._name_parser(name_engine="paddle")
        parser.parser_profile = "auto"
        parser.score_engine = "fixed_digit"
        parser._image_from_bytes = lambda image_bytes: image_bytes
        parser.scoreboard_locator = mock.Mock()
        score_image = text_ocr.Image.new("RGB", (320, 140), "white")
        score_layout = make_score_layout(
            "selected",
            tuple(
                (160 + column * 40, row_top, 200 + column * 40, row_top + 56)
                for row_top in (0, 60)
                for column in range(3)
            ),
            ("green", "yellow", "red") * 2,
        )
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
            score_layout,
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
        parser._ocr_name_fields = mock.Mock(
            return_value=(
                "TEST ATHLETE ALPHA\nTEST ATHLETE BETA",
                {
                    "top_athlete_name": "TEST ATHLETE ALPHA",
                    "bottom_athlete_name": "TEST ATHLETE BETA",
                },
            )
        )

        parser.parse_score_timer(12, score_image, b"timer")
        first_full = parser.parse(12, score_image, b"timer")
        second_full = parser.parse(13, score_image, b"timer")

        self.assertEqual(first_full.top_athlete_name, "TEST ATHLETE ALPHA")
        self.assertEqual(second_full.bottom_athlete_name, "TEST ATHLETE BETA")
        parser.score_reader.read.assert_called_once_with(score_image)
        parser.timer_reader.read.assert_called_once_with(b"timer")
        parser._ocr_name_fields.assert_called_once_with(
            score_image,
            text_ocr._name_regions_from_score_layout(score_image.size, score_layout),
        )
        parser.scoreboard_locator.locate.assert_not_called()

    def test_scoreboard_digit_reader_accepts_rendered_layout(self):
        if (
            text_ocr.cv2 is None
            or text_ocr.np is None
            or text_ocr.Image is None
            or text_ocr.ImageDraw is None
        ):
            self.skipTest("fixed digit OCR dependencies are unavailable")

        class ConstantClassifier:
            def predict(self, mask, allowed_digits=None):
                return text_ocr.DigitPrediction(0, 0.99, "test")

        image = text_ocr.Image.new("RGB", (1000, 200), (0, 0, 0))
        draw = text_ocr.ImageDraw.Draw(image)
        colors = {
            "green": (40, 150, 60),
            "yellow": (190, 160, 50),
            "red": (180, 40, 50),
        }
        cell_width = 100
        cell_height = 64
        cell_gap = 4
        left = 570
        row_tops = (15, 90)
        roles = ("green", "yellow", "red")
        boxes = tuple(
            (
                left + column * (cell_width + cell_gap),
                row_top,
                left + column * (cell_width + cell_gap) + cell_width,
                row_top + cell_height,
            )
            for row_top in row_tops
            for column in range(3)
        )
        layout = make_score_layout(
            "synthetic_rendered",
            boxes,
            roles * 2,
        )
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
        self.assertIsNotNone(reading.layout)
        self.assertEqual(len(reading.layout.cell_boxes), 6)

    def test_scoreboard_digit_reader_detects_offset_rendered_layout(self):
        if (
            text_ocr.cv2 is None
            or text_ocr.np is None
            or text_ocr.Image is None
            or text_ocr.ImageDraw is None
        ):
            self.skipTest("fixed digit OCR dependencies are unavailable")

        class ConstantClassifier:
            def predict(self, mask, allowed_digits=None):
                return text_ocr.DigitPrediction(0, 0.99, "test")

        image = text_ocr.Image.new("RGB", (360, 180), (0, 0, 0))
        draw = text_ocr.ImageDraw.Draw(image)
        colors = {
            "green": (40, 150, 60),
            "yellow": (190, 160, 50),
            "red": (180, 40, 50),
        }
        cell_width = 34
        cell_height = 38
        left = 72
        row_tops = (28, 84)
        roles = ("green", "yellow", "red")
        for row_top in row_tops:
            for column, role in enumerate(roles):
                x1 = left + column * cell_width
                box = (x1, row_top, x1 + cell_width, row_top + cell_height)
                draw.rectangle(box, fill=colors[role])
                draw.rectangle(
                    (x1 + 12, row_top + 8, x1 + 21, row_top + cell_height - 8),
                    fill=(245, 245, 245),
                )

        reading = text_ocr.ScoreboardDigitReader(ConstantClassifier()).read(image)

        self.assertTrue(reading.has_layout)
        self.assertEqual(reading.digits, (0, 0, 0, 0, 0, 0))
        self.assertIsNotNone(reading.layout)

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

    def test_validate_name_engines_require_opencv_for_scoreboard_location(self):
        with mock.patch.object(text_ocr, "cv2", None), mock.patch.dict(
            sys.modules,
            {
                "pytesseract": mock.Mock(),
                "paddleocr": mock.Mock(),
            },
        ), mock.patch("shutil.which", return_value="/usr/bin/tesseract"):
            with self.assertRaisesRegex(RuntimeError, "opencv-python"):
                text_ocr.validate_ocr_engines("none", "tesseract")
            with self.assertRaisesRegex(RuntimeError, "opencv-python"):
                text_ocr.validate_ocr_engines("none", "paddle")


class LivestreamFrameTextOcrFixtureTestCase(unittest.TestCase):
    fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures", "livestream_ocr")

    def test_fixed_digit_templates_use_bundled_fonts(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.TimerDigitReader()
        template_sources = {template.source for template in reader.classifier.templates}
        template_source_text = "\n".join(sorted(template_sources))

        self.assertNotIn("default", template_source_text)
        self.assertFalse(
            any(source.startswith("/System/") for source in template_sources)
        )
        self.assertIn("DejaVuSans-Bold.ttf", template_source_text)
        self.assertIn("Roboto-wdth-wght.ttf", template_source_text)

    def _scoreboard_manifest(self):
        manifest_path = os.path.join(self.fixture_dir, "scoreboard_cases.json")
        with open(manifest_path) as fileobj:
            return json.load(fileobj)

    def _scoreboard_image(self, fixture_name):
        return text_ocr.Image.open(
            os.path.join(self.fixture_dir, fixture_name)
        ).convert("RGB")

    def test_scoreboard_manifest_matches_fixture_filesystem(self):
        manifest = self._scoreboard_manifest()
        manifest_names = {case["fixture"] for case in manifest["cases"]}
        fixture_names = {
            name
            for name in os.listdir(self.fixture_dir)
            if name.endswith(".jpg")
            and name.startswith(("score", "new_score", "paddle_names"))
        }

        self.assertEqual(manifest["version"], 1)
        self.assertEqual(len(manifest_names), 83)
        self.assertEqual(manifest_names, fixture_names)
        self.assertEqual(len(manifest_names), len(manifest["cases"]))

    def test_scoreboard_fixture_manifest_is_corpus_wide_golden(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.ScoreboardDigitReader()

        for case in self._scoreboard_manifest()["cases"]:
            with self.subTest(fixture=case["fixture"]):
                reading = reader.read(self._scoreboard_image(case["fixture"]))
                self.assertEqual(reading.has_layout, case["expect_layout"])
                if case["expect_layout"]:
                    self.assertEqual(
                        reading.digits,
                        tuple(case["expected_digits"]),
                    )
                    self.assertEqual(len(reading.layout.cells), 6)
                else:
                    self.assertIsNone(reading.digits)
                    self.assertIsNone(reading.layout)
                    self.assertTrue(case["reason"])

    def test_combined_parser_cases_agree_with_scoreboard_manifest(self):
        manifest_cases = {
            case["fixture"]: tuple(case["expected_digits"])
            for case in self._scoreboard_manifest()["cases"]
            if case["expect_layout"]
        }
        with open(os.path.join(self.fixture_dir, "cases.json")) as fileobj:
            parser_cases = json.load(fileobj)
        score_fields = (
            "top_points",
            "top_advantages",
            "top_penalties",
            "bottom_points",
            "bottom_advantages",
            "bottom_penalties",
        )

        for case in parser_cases:
            expected = case["expected"]
            if all(field in expected for field in score_fields):
                self.assertEqual(
                    tuple(expected[field] for field in score_fields),
                    manifest_cases[case["score_image"]],
                    case["id"],
                )

    def test_scoreboard_layout_invariants_hold_across_fixture_corpus(self):
        locator = text_ocr.ScoreboardLocator()
        nonrectangular_regions = 0
        for case in self._scoreboard_manifest()["cases"]:
            image = self._scoreboard_image(case["fixture"])
            layout = locator.locate(image)
            if not case["expect_layout"]:
                self.assertIsNone(layout, case["fixture"])
                continue

            with self.subTest(fixture=case["fixture"]):
                self.assertIsNotNone(layout)
                self.assertEqual(
                    tuple(cell.role for cell in layout.cells),
                    ("green", "yellow", "red") * 2,
                )
                self.assertEqual(
                    tuple((cell.row, cell.column) for cell in layout.cells),
                    tuple((index // 3, index % 3) for index in range(6)),
                )
                for cell in layout.cells:
                    x1, y1, x2, y2 = cell.bounds
                    self.assertEqual(
                        cell.region_mask.shape,
                        (y2 - y1, x2 - x1),
                    )
                    self.assertTrue(cell.region_mask.any())
                    if not cell.region_mask.all():
                        nonrectangular_regions += 1
                for first_index, first in enumerate(layout.cells):
                    for second in layout.cells[first_index + 1 :]:
                        x_overlap = max(
                            0,
                            min(first.bounds[2], second.bounds[2])
                            - max(first.bounds[0], second.bounds[0]),
                        )
                        y_overlap = max(
                            0,
                            min(first.bounds[3], second.bounds[3])
                            - max(first.bounds[1], second.bounds[1]),
                        )
                        self.assertEqual(x_overlap * y_overlap, 0)

        self.assertGreater(nonrectangular_regions, 0)

    def test_manually_reviewed_scoreboard_layout_annotations(self):
        reviewed_bounds = {
            "new_score_010_420.jpg": (
                (122, 8, 142, 39),
                (148, 8, 167, 38),
                (174, 8, 194, 39),
                (122, 48, 142, 79),
                (148, 48, 168, 79),
                (174, 48, 194, 79),
            ),
            "new_score_010_420_2.jpg": (
                (122, 8, 142, 39),
                (148, 8, 167, 38),
                (174, 8, 194, 38),
                (122, 48, 142, 79),
                (148, 48, 168, 79),
                (174, 48, 194, 79),
            ),
            "new_score_210_2200.jpg": (
                (92, 6, 106, 27),
                (110, 6, 122, 27),
                (126, 6, 140, 27),
                (88, 33, 106, 55),
                (109, 33, 123, 54),
                (126, 33, 140, 55),
            ),
            "score_012_012.jpg": (
                (103, 0, 135, 38),
                (137, 0, 168, 38),
                (170, 0, 192, 38),
                (103, 43, 136, 80),
                (137, 43, 168, 80),
                (171, 43, 192, 80),
            ),
            "score_smaller_1210_010.jpg": (
                (77, 0, 102, 29),
                (102, 0, 126, 28),
                (128, 0, 143, 28),
                (77, 32, 101, 60),
                (102, 32, 126, 60),
                (127, 32, 143, 60),
            ),
            "paddle_names3.jpg": (
                (232, 0, 304, 87),
                (307, 0, 377, 86),
                (382, 0, 430, 86),
                (232, 95, 303, 182),
                (307, 95, 377, 182),
                (382, 95, 430, 182),
            ),
        }
        locator = text_ocr.ScoreboardLocator()

        for fixture_name, expected_bounds in reviewed_bounds.items():
            with self.subTest(fixture=fixture_name):
                layout = locator.locate(self._scoreboard_image(fixture_name))
                self.assertEqual(layout.cell_boxes, expected_bounds)

    def test_score_role_segmentation_is_disjoint_and_palette_tolerant(self):
        for palette in text_ocr.SCORE_BACKGROUND_PALETTES:
            for role_index, role in enumerate(("green", "yellow", "red")):
                color = text_ocr.np.asarray(palette[role], dtype="int16")
                for delta in ((0, 0, 0), (8, -7, 6), (-6, 7, -5)):
                    rgb = text_ocr.np.clip(color + delta, 0, 255).astype("uint8")
                    masks = text_ocr._score_role_masks_from_rgb(rgb.reshape(1, 1, 3))
                    self.assertTrue(masks[role][0, 0])
                    self.assertEqual(
                        sum(bool(mask[0, 0]) for mask in masks.values()),
                        1,
                        (role_index, delta),
                    )

    def test_score_glyph_mask_is_contained_by_cell_region(self):
        background = (243, 183, 25)
        image = text_ocr.Image.new("RGB", (15, 15), (10, 80, 160))
        draw = text_ocr.ImageDraw.Draw(image)
        draw.rectangle((3, 3, 11, 11), fill=background)
        draw.rectangle((7, 5, 8, 9), fill=(250, 250, 250))
        draw.rectangle((0, 11, 2, 14), fill=(250, 250, 250))
        region_mask = text_ocr.np.zeros((15, 15), dtype=bool)
        region_mask[3:12, 3:12] = True

        glyph = text_ocr._score_digit_threshold(
            image,
            background,
            region_mask,
        )

        self.assertTrue(glyph[6, 7])
        self.assertFalse(glyph[1, 1])
        self.assertFalse(glyph[12, 1])
        self.assertFalse(glyph[~region_mask].any())

    def test_score_glyph_mixture_rejects_saturated_off_line_color(self):
        background = (243, 183, 25)
        image = text_ocr.Image.new("RGB", (12, 12), background)
        draw = text_ocr.ImageDraw.Draw(image)
        draw.rectangle((4, 3, 7, 8), fill=(250, 250, 250))
        draw.point((2, 2), fill=(255, 80, 255))
        region_mask = text_ocr.np.ones((12, 12), dtype=bool)

        glyph = text_ocr._score_digit_threshold(image, background, region_mask)

        self.assertTrue(glyph[4, 5])
        self.assertFalse(glyph[2, 2])

    def test_local_role_seam_closure_does_not_join_neighboring_cells(self):
        mask = text_ocr.np.zeros((14, 24), dtype=bool)
        mask[2:12, 1:10] = True
        mask[2:12, 14:23] = True
        mask[2:12, 5] = False

        closed = text_ocr._close_score_role_mask(mask)
        component_count, _, _, _ = text_ocr.cv2.connectedComponentsWithStats(
            closed.astype("uint8"),
            8,
        )

        self.assertTrue(closed[6, 5])
        self.assertEqual(component_count - 1, 2)

    def test_score_role_components_do_not_join_cell_to_wider_background(self):
        image = text_ocr.Image.new("RGB", (60, 50), (8, 60, 130))
        draw = text_ocr.ImageDraw.Draw(image)
        yellow = text_ocr.SCORE_BACKGROUND_PALETTES[0]["yellow"]
        draw.rectangle((20, 2, 29, 20), fill=yellow)
        draw.rectangle((5, 23, 49, 45), fill=yellow)

        components = text_ocr._score_role_components(image, "yellow")

        self.assertEqual(
            {component.bounds for component in components},
            {(20, 2, 30, 21), (5, 23, 50, 46)},
        )

    def test_score_role_components_rejoin_small_seam_bridge(self):
        image = text_ocr.Image.new("RGB", (40, 30), (8, 60, 130))
        draw = text_ocr.ImageDraw.Draw(image)
        yellow = text_ocr.SCORE_BACKGROUND_PALETTES[0]["yellow"]
        draw.rectangle((5, 2, 24, 9), fill=yellow)
        draw.rectangle((13, 11, 14, 12), fill=yellow)
        draw.rectangle((5, 14, 24, 22), fill=yellow)

        components = text_ocr._score_role_components(image, "yellow")

        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].bounds, (5, 2, 25, 23))

    def test_score_role_components_rejoin_narrow_fragment_but_not_row_gap(self):
        image = text_ocr.Image.new("RGB", (50, 34), (8, 60, 130))
        draw = text_ocr.ImageDraw.Draw(image)
        red = text_ocr.SCORE_BACKGROUND_PALETTES[1]["red"]
        draw.rectangle((5, 2, 16, 9), fill=red)
        draw.rectangle((9, 13, 11, 17), fill=red)
        draw.rectangle((5, 20, 16, 27), fill=red)
        draw.rectangle((27, 2, 38, 13), fill=red)
        draw.rectangle((27, 18, 38, 29), fill=red)

        components = text_ocr._score_role_components(image, "red")

        self.assertEqual(
            {component.bounds for component in components},
            {(5, 2, 17, 28), (27, 2, 39, 14), (27, 18, 39, 30)},
        )

    def test_cell_region_fills_digit_hole_but_excludes_rounded_corners(self):
        image = text_ocr.Image.new("RGB", (40, 30), (8, 60, 130))
        draw = text_ocr.ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 4, 34, 25), radius=5, fill=(49, 226, 81))
        draw.rectangle((18, 9, 21, 20), fill=(250, 250, 250))

        components = text_ocr._score_role_components(image, "green")

        self.assertEqual(len(components), 1)
        cell = components[0]
        self.assertTrue(cell.region_mask[12, 14])
        self.assertFalse(cell.region_mask[0, 0])

    def test_scoreboard_locator_rejects_incomplete_and_ambiguous_grids(self):
        colors = {
            "green": (49, 226, 81),
            "yellow": (243, 183, 25),
            "red": (199, 34, 54),
        }

        def draw_grid(image, left, top, include_last=True):
            draw = text_ocr.ImageDraw.Draw(image)
            for row in range(2):
                for column, role in enumerate(("green", "yellow", "red")):
                    if not include_last and row == 1 and column == 2:
                        continue
                    x1 = left + column * 24
                    y1 = top + row * 26
                    draw.rounded_rectangle(
                        (x1, y1, x1 + 20, y1 + 20),
                        radius=3,
                        fill=colors[role],
                    )

        incomplete = text_ocr.Image.new("RGB", (180, 90), (8, 60, 130))
        draw_grid(incomplete, 10, 8, include_last=False)
        self.assertIsNone(text_ocr.ScoreboardLocator().locate(incomplete))

        ambiguous = text_ocr.Image.new("RGB", (240, 90), (8, 60, 130))
        draw_grid(ambiguous, 10, 8)
        draw_grid(ambiguous, 130, 8)
        self.assertIsNone(text_ocr.ScoreboardLocator().locate(ambiguous))

    def test_scoreboard_manifest_covers_every_digit_and_starting_regression(self):
        manifest = self._scoreboard_manifest()
        digit_characters = {
            character
            for case in manifest["cases"]
            for value in case.get("expected_digits", [])
            for character in str(value)
        }
        regression_cases = {
            case["fixture"]: tuple(case["expected_digits"])
            for case in manifest["cases"]
            if "starting_regression" in case["purposes"]
        }

        self.assertEqual(digit_characters, set("0123456789"))
        self.assertEqual(
            regression_cases,
            {
                "new_score_010_420.jpg": (0, 1, 0, 4, 2, 0),
                "new_score_010_420_2.jpg": (0, 1, 0, 4, 2, 0),
                "new_score_210_2200.jpg": (2, 1, 0, 22, 0, 0),
            },
        )

    def test_obsolete_score_architecture_is_absent(self):
        obsolete_symbols = (
            "_inner_cell",
            "_should_use_raw_score_prediction",
            "_prediction_has_leading_one_geometry",
            "_prediction_has_ambiguous_edge",
            "_score_ownership_context",
            "_score_component_ownership",
            "ScoreComponentOwnership",
        )
        for symbol in obsolete_symbols:
            self.assertFalse(hasattr(text_ocr, symbol), symbol)

    def test_scoreboard_locator_is_invariant_to_padding_and_scale(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        score_path = os.path.join(self.fixture_dir, "score_012_012.jpg")
        self.assertTrue(
            os.path.exists(score_path),
            "missing livestream OCR score fixture: score_012_012.jpg",
        )

        with open(score_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        horizontal_offset = text_ocr.Image.new(
            "RGB", (image.width + 80, image.height), (12, 12, 12)
        )
        horizontal_offset.paste(image, (55, 0))
        variants = {
            "padding": text_ocr.ImageOps.expand(
                image,
                border=(37, 11, 53, 7),
                fill=(12, 12, 12),
            ),
            "horizontal_offset": horizontal_offset,
            "scaled_down": image.resize((184, 83), text_ocr.Image.Resampling.LANCZOS),
            "scaled_up": image.resize((345, 156), text_ocr.Image.Resampling.LANCZOS),
        }
        locator = text_ocr.ScoreboardLocator()
        reader = text_ocr.ScoreboardDigitReader()
        base_layout = locator.locate(image)
        base_name_layout = text_ocr._name_regions_from_score_layout(
            image.size, base_layout
        )

        for variant_name, variant in variants.items():
            with self.subTest(variant=variant_name):
                layout = locator.locate(variant)
                self.assertIsNotNone(layout)
                self.assertEqual(len(layout.cell_boxes), 6)
                name_layout = text_ocr._name_regions_from_score_layout(
                    variant.size, layout
                )
                grid_left = min(layout.cell_boxes[0][0], layout.cell_boxes[3][0])
                self.assertEqual(name_layout.column_box[2], grid_left)
                self.assertTrue(
                    all(box[2] == grid_left for box in name_layout.line_boxes)
                )
                for row_cells, line_box in zip(
                    (layout.cell_boxes[:3], layout.cell_boxes[3:]),
                    name_layout.line_boxes,
                ):
                    row_top = min(box[1] for box in row_cells)
                    row_bottom = max(box[3] for box in row_cells)
                    self.assertGreaterEqual(line_box[1], row_top)
                    self.assertLessEqual(line_box[3], row_bottom)
                if variant_name in ("padding", "horizontal_offset"):
                    self.assertEqual(
                        name_layout.use_scaled_retry,
                        base_name_layout.use_scaled_retry,
                    )
                self.assertEqual(reader.read(variant).digits, (0, 1, 2, 0, 1, 2))

        self.assertNotEqual(
            text_ocr._name_regions_from_score_layout(
                variants["scaled_down"].size,
                locator.locate(variants["scaled_down"]),
            ).use_scaled_retry,
            text_ocr._name_regions_from_score_layout(
                variants["scaled_up"].size,
                locator.locate(variants["scaled_up"]),
            ).use_scaled_retry,
        )

    def test_scoreboard_manifest_is_context_invariant(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.ScoreboardDigitReader()

        for case in self._scoreboard_manifest()["cases"]:
            if not case["expect_layout"]:
                continue
            image = self._scoreboard_image(case["fixture"])
            expected_digits = tuple(case["expected_digits"])
            translated = text_ocr.Image.new(
                "RGB", (image.width + 30, image.height), (12, 12, 12)
            )
            translated.paste(image, (19, 0))
            encoded = io.BytesIO()
            image.save(encoded, "JPEG", quality=95)
            encoded.seek(0)
            variants = {
                "padding": text_ocr.ImageOps.expand(
                    image, border=(13, 5, 17, 3), fill=(12, 12, 12)
                ),
                "translation": translated,
                "scaled_down": image.resize(
                    (round(image.width * 0.90), round(image.height * 0.90)),
                    text_ocr.Image.Resampling.LANCZOS,
                ),
                "scaled_up": image.resize(
                    (round(image.width * 1.15), round(image.height * 1.15)),
                    text_ocr.Image.Resampling.LANCZOS,
                ),
                "jpeg": text_ocr.Image.open(encoded).convert("RGB"),
            }
            for variant_name, variant in variants.items():
                with self.subTest(fixture=case["fixture"], variant=variant_name):
                    self.assertEqual(reader.read(variant).digits, expected_digits)

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

    def test_new_timer_1000_reads_as_ten_minutes(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "new_timer_1000.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "stopped")
        self.assertEqual(reading.value, "10:00")
        self.assertEqual(reading.predictions[0].digit, 1)

    def test_small_stopped_timer_1000_ignores_dark_video_outside_display(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "timer_stopped_1000.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "stopped")
        self.assertEqual(reading.value, "10:00")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [1, 0, 0, 0],
        )

    def test_new_timer_0000_reads_as_stopped(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.TimerDigitReader()
        fixture_names = (
            "new_timer_0000.jpg",
            "new_timer_0000_2.jpg",
            "new_timer_0000_3.jpg",
        )

        for fixture_name in fixture_names:
            with self.subTest(fixture=fixture_name):
                timer_path = os.path.join(self.fixture_dir, fixture_name)
                with open(timer_path, "rb") as fileobj:
                    image = text_ocr.Image.open(fileobj).convert("RGB")

                reading = reader.read(image)

                self.assertEqual(reading.state, "stopped")
                self.assertEqual(reading.value, "0:00")
                self.assertEqual(
                    [prediction.digit for prediction in reading.predictions],
                    [0, 0, 0, 0],
                )

    def test_yellow_running_timer_reads_all_digits(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "new_timer_0058.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "running")
        self.assertEqual(reading.value, "0:58")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [0, 0, 5, 8],
        )

    def test_old_stopped_timer_600_ignores_scoreboard_frame(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "timer_stopped_600.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "stopped")
        self.assertEqual(reading.value, "6:00")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [6, 0, 0],
        )

    def test_old_stopped_timer_500_ignores_left_border(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "timer_500.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "stopped")
        self.assertEqual(reading.value, "5:00")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [5, 0, 0],
        )

    def test_exact_timer_crops_read_all_digits(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.TimerDigitReader()
        cases = (
            ("timer_exact_running_618.jpg", "running", "6:18", [6, 1, 8]),
            ("timer_exact_stopped_649.jpg", "stopped", "6:49", [6, 4, 9]),
        )

        for fixture_name, expected_state, expected_value, expected_digits in cases:
            with self.subTest(fixture=fixture_name):
                timer_path = os.path.join(self.fixture_dir, fixture_name)
                with open(timer_path, "rb") as fileobj:
                    image = text_ocr.Image.open(fileobj).convert("RGB")

                reading = reader.read(image)

                self.assertEqual(reading.state, expected_state)
                self.assertEqual(reading.value, expected_value)
                self.assertEqual(
                    [prediction.digit for prediction in reading.predictions],
                    expected_digits,
                )

    def test_timer_layout_tracks_padding_position_and_scale(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.TimerDigitReader()
        cases = (
            ("timer_exact_running_618.jpg", "running", "6:18"),
            ("timer_exact_stopped_649.jpg", "stopped", "6:49"),
            ("new_timer_1000.jpg", "stopped", "10:00"),
            ("timer_stopped_colors_346.jpg", "stopped", "3:46"),
        )

        for fixture_name, expected_state, expected_value in cases:
            timer_path = os.path.join(self.fixture_dir, fixture_name)
            with open(timer_path, "rb") as fileobj:
                image = text_ocr.Image.open(fileobj).convert("RGB")

            baseline = reader.read(image)
            self.assertIsNotNone(baseline.layout)
            rgb = text_ocr.np.asarray(image)
            red = rgb[:, :, 0]
            green = rgb[:, :, 1]
            blue = rgb[:, :, 2]
            if baseline.layout.foreground == "black":
                background_mask = (red > 130) & (green < 100) & (blue < 120)
            else:
                background_mask = (blue > 60) & (red < 60) & (green < 80)
                if not background_mask.any():
                    background_mask = (red < 60) & (green < 60) & (blue < 60)
            self.assertTrue(background_mask.any())
            background = tuple(
                int(channel)
                for channel in text_ocr.np.median(rgb[background_mask], axis=0)
            )

            canvas_size = (image.width * 2, image.height * 2)
            positions = (
                (0, 0),
                (
                    (canvas_size[0] - image.width) // 2,
                    (canvas_size[1] - image.height) // 2,
                ),
                (canvas_size[0] - image.width, canvas_size[1] - image.height),
            )
            for position in positions:
                with self.subTest(fixture=fixture_name, position=position):
                    variant = text_ocr.Image.new("RGB", canvas_size, background)
                    variant.paste(image, position)

                    reading = reader.read(variant)

                    self.assertEqual(reading.state, expected_state)
                    self.assertEqual(reading.value, expected_value)
                    self.assertIsNotNone(reading.layout)
                    self.assertGreaterEqual(
                        min(box[0] for box in reading.layout.digit_boxes),
                        position[0],
                    )
                    self.assertGreaterEqual(
                        min(box[1] for box in reading.layout.digit_boxes),
                        position[1],
                    )

            scaled = image.resize(
                (
                    max(1, int(round(image.width * 0.75))),
                    max(1, int(round(image.height * 0.75))),
                ),
                text_ocr.Image.Resampling.LANCZOS,
            )
            scaled_variant = text_ocr.Image.new("RGB", image.size, background)
            scaled_variant.paste(
                scaled,
                (
                    (image.width - scaled.width) // 2,
                    (image.height - scaled.height) // 2,
                ),
            )

            with self.subTest(fixture=fixture_name, variant="scaled"):
                reading = reader.read(scaled_variant)
                self.assertEqual(reading.state, expected_state)
                self.assertEqual(reading.value, expected_value)

    def test_timer_locator_rejects_solid_non_digit_components(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        image = text_ocr.Image.new("RGB", (180, 70), (10, 10, 80))
        draw = text_ocr.ImageDraw.Draw(image)
        for left, width in ((25, 20), (60, 12), (105, 20)):
            draw.rectangle(
                (left, 15, left + width, 55),
                fill=(20, 220, 40),
            )

        reader = text_ocr.TimerDigitReader()
        reading = reader.read(image)

        self.assertEqual(reader.locator.locate_candidates(image), ())
        self.assertEqual(reading.state, "blank")
        self.assertIsNone(reading.value)

    def test_timer_locator_rejects_diagonal_building_windows_as_blank(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        reader = text_ocr.TimerDigitReader()

        for fixture_name in ("new_timer_blank.jpg", "new_timer_blank_2.jpg"):
            with self.subTest(fixture=fixture_name):
                timer_path = os.path.join(self.fixture_dir, fixture_name)
                with open(timer_path, "rb") as fileobj:
                    image = text_ocr.Image.open(fileobj).convert("RGB")

                reading = reader.read(image)

                self.assertEqual(reader.locator.locate_candidates(image), ())
                self.assertEqual(reading.state, "blank")
                self.assertIsNone(reading.value)

    def test_running_timer_with_adjacent_white_text_prefers_green_digits(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "timer_new_running_0642.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "running")
        self.assertEqual(reading.value, "6:42")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [0, 6, 4, 2],
        )

    def test_stopped_timer_ignores_horizontal_color_artifacts(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "timer_stopped_colors_346.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.state, "stopped")
        self.assertEqual(reading.value, "3:46")
        self.assertEqual(
            [prediction.digit for prediction in reading.predictions],
            [3, 4, 6],
        )

    def test_four_digit_timer_limits_minute_tens_to_ibjjf_match_maximum(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "new_timer_1000.jpg")

        class RecordingClassifier:
            def __init__(self):
                self.allowed_digits = []

            def predict(self, mask, allowed_digits=None):
                self.allowed_digits.append(allowed_digits)
                if allowed_digits == text_ocr.TimerDigitReader.MINUTE_TENS_DIGITS:
                    return text_ocr.DigitPrediction(1, 1.0, "test-minute-tens")
                if allowed_digits == text_ocr.TimerDigitReader.SECOND_TENS_DIGITS:
                    return text_ocr.DigitPrediction(0, 1.0, "test-second-tens")
                return text_ocr.DigitPrediction(0, 1.0, "test-unrestricted")

        classifier = RecordingClassifier()
        reader = text_ocr.TimerDigitReader(classifier=classifier)

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.value, "10:00")
        self.assertEqual(
            classifier.allowed_digits,
            [
                text_ocr.TimerDigitReader.MINUTE_TENS_DIGITS,
                None,
                text_ocr.TimerDigitReader.SECOND_TENS_DIGITS,
                None,
            ],
        )

    def test_three_digit_timer_does_not_limit_leading_minute_digit(self):
        self.assertEqual(
            text_ocr.TimerDigitReader._allowed_digits_for_timer_masks(3),
            [None, text_ocr.TimerDigitReader.SECOND_TENS_DIGITS, None],
        )

    def test_cutoff_timer_three_uses_top_cropped_digit_template(self):
        text_ocr.validate_ocr_engines("fixed_digit", "none")
        timer_path = os.path.join(self.fixture_dir, "new_timer_0237.jpg")
        reader = text_ocr.TimerDigitReader()

        with open(timer_path, "rb") as fileobj:
            image = text_ocr.Image.open(fileobj).convert("RGB")

        reading = reader.read(image)

        self.assertEqual(reading.value, "2:37")
        self.assertEqual(reading.predictions[2].digit, 3)
        self.assertGreater(reading.predictions[2].similarity, 0.7)
        self.assertIn("top-crop", reading.predictions[2].source)

    def test_paddle_smaller_name_fixture_reads_both_names(self):
        try:
            text_ocr.validate_ocr_engines("none", "paddle")
        except RuntimeError as exc:
            self.skipTest(str(exc))

        parser = text_ocr.FrameImageTextParser("auto", "none", "paddle")
        score_path = os.path.join(self.fixture_dir, "score_smaller_names.jpg")
        self.assertTrue(
            os.path.exists(score_path),
            "missing livestream OCR score fixture: score_smaller_names.jpg",
        )
        with open(score_path, "rb") as fileobj:
            reading = parser.parse(0, fileobj.read(), None)

        self.assertEqual(reading.top_athlete_name, "MARTIN RAPCAN")
        self.assertEqual(reading.bottom_athlete_name, "ALEX CABANES GISBERT")

    def test_paddle_existing_name_fixtures_find_two_names(self):
        try:
            text_ocr.validate_ocr_engines("none", "paddle")
        except RuntimeError as exc:
            self.skipTest(str(exc))

        parser = text_ocr.FrameImageTextParser("auto", "none", "paddle")
        cases = [
            "new_score_200_010.jpg",
            "new_score_930_000.jpg",
            "new_score_names.jpg",
            "new_score_names2.jpg",
            "new_score_names3.jpg",
            "new_score_names4.jpg",
            "new_score_names5.jpg",
            "new_score_multi.jpg",
            "score_names2.jpg",
            "score_names3.jpg",
            "score_names4.jpg",
            "score_names5.jpg",
            "score_names6.jpg",
            "score_names7.jpg",
            "score_small_000_000.jpg",
            "score_small_names.jpg",
            "score_small_names2.jpg",
            "score_small_names3.jpg",
            "new_score_names6.jpg",
        ]

        for score_image in cases:
            with self.subTest(score_image=score_image):
                score_path = os.path.join(self.fixture_dir, score_image)
                self.assertTrue(
                    os.path.exists(score_path),
                    f"missing livestream OCR score fixture: {score_image}",
                )
                with open(score_path, "rb") as fileobj:
                    reading = parser.parse(0, fileobj.read(), None)

                self.assertTrue(reading.top_athlete_name)
                self.assertTrue(reading.bottom_athlete_name)

    def test_malformed_scoreboard_abandons_scores_and_names(self):
        try:
            text_ocr.validate_ocr_engines("fixed_digit", "paddle")
        except RuntimeError as exc:
            self.skipTest(str(exc))

        parser = text_ocr.FrameImageTextParser("auto", "fixed_digit", "paddle")
        score_path = os.path.join(self.fixture_dir, "score_malformed.jpg")
        self.assertTrue(
            os.path.exists(score_path),
            "missing malformed livestream OCR fixture: score_malformed.jpg",
        )
        with open(score_path, "rb") as fileobj:
            reading = parser.parse(0, fileobj.read(), None)

        self.assertEqual(reading.scoreboard_state, text_scan.SCOREBOARD_STATE_BLANK)
        for field_name in (
            "top_points",
            "top_advantages",
            "top_penalties",
            "bottom_points",
            "bottom_advantages",
            "bottom_penalties",
            "top_athlete_name",
            "top_team_name",
            "bottom_athlete_name",
            "bottom_team_name",
        ):
            self.assertIsNone(getattr(reading, field_name), field_name)

    def test_paddle_name_fixture_names(self):
        try:
            text_ocr.validate_ocr_engines("none", "paddle")
        except RuntimeError as exc:
            self.skipTest(str(exc))

        parser = text_ocr.FrameImageTextParser("auto", "none", "paddle")
        cases = [
            (
                "paddle_names.jpg",
                "VITOR GABRIEL NASCL",
                "GUSTAVO HENRIQUE B",
            ),
            (
                "paddle_names2.jpg",
                "VITOR CABRIEL NASCL",
                "GUSTAVO HENRIQUE B",
            ),
            (
                "paddle_names3.jpg",
                "PEDRO HENRIQUE BRIT",
                "JOÄO MANOEL DOS SA",
            ),
            (
                "paddle_names4.jpg",
                "CHRISTIAN MACEDO",
                "MATEUS VICTOR OLIVE",
            ),
            (
                "paddle_names5.jpg",
                "CARLOS RYAN OLIVEIR",
                "VICTOR MANOEL",
            ),
            (
                "paddle_names6.jpg",
                "EDISON MARTIN VINUE",
                "KAUÉ HENRIQUE RAGA",
            ),
            (
                "new_score_names6.jpg",
                "Stephany Correa Oliveira",
                "Zaian Langella",
            ),
            (
                "score_names8.jpg",
                "VANESSA MARY MARSH",
                "SHAHIRA ASADI",
            ),
            (
                "score_names9.jpg",
                "JAMES ANTHONY SPA",
                "MATTHEW GERARD",
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

    def _archive_with_segment(self, youtube_video_id="HxZSos1k_MA"):
        archive = LivestreamFrameArchive(
            youtube_video_id=youtube_video_id,
            canonical_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            s3_prefix=f"livestream-frames/{youtube_video_id}/",
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

    def test_admin_text_scan_page_passes_selected_sort(self):
        client = self._admin_client()
        with client.session_transaction() as session_data:
            session_data["logged_in"] = True

        with mock.patch.object(
            self.admin_module, "_livestream_frame_text_scan_rows", return_value=[]
        ) as rows:
            response = client.get("/livestream_frame_text_scans?sort=youtube_id")

        self.assertEqual(response.status_code, 200)
        rows.assert_called_once_with(sort="youtube_id")
        html = response.get_data(as_text=True)
        self.assertIn('id="text-scan-sort"', html)
        self.assertIn('value="youtube_id" selected', html)
        self.assertIn('name="sort" value="youtube_id"', html)

    def test_admin_queue_ready_uses_selected_dashboard_sort_order(self):
        first_archive, _ = self._archive_with_segment("QueueReady01")
        second_archive, _ = self._archive_with_segment("QueueReady02")
        client = self._admin_client()
        with client.session_transaction() as session_data:
            session_data["logged_in"] = True

        queued = []

        def fake_queue_text_scan(session, archive, **kwargs):
            queued.append((archive.youtube_video_id, kwargs["queue_requested_at"]))
            return 0

        sorted_rows = [
            {"archive": second_archive, "scan": None, "ready_to_queue": True},
            {"archive": first_archive, "scan": None, "ready_to_queue": True},
        ]
        with mock.patch.object(
            self.admin_module,
            "_livestream_frame_text_scan_rows",
            side_effect=[sorted_rows, []],
        ) as rows, mock.patch.object(
            self.admin_module,
            "queue_text_scan",
            side_effect=fake_queue_text_scan,
        ):
            response = client.post(
                "/livestream_frame_text_scans",
                data={"action": "queue_ready", "sort": "event_date_asc"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [youtube_id for youtube_id, _queued_at in queued],
            ["QueueReady02", "QueueReady01"],
        )
        self.assertLess(queued[0][1], queued[1][1])
        self.assertEqual(rows.call_args_list[0].kwargs, {"sort": "event_date_asc"})

    def test_admin_queue_selected_uses_submitted_row_order(self):
        first_archive, _ = self._archive_with_segment("QueueSelect1")
        second_archive, _ = self._archive_with_segment("QueueSelect2")
        client = self._admin_client()
        with client.session_transaction() as session_data:
            session_data["logged_in"] = True

        queued = []

        def fake_queue_text_scan(session, archive, **kwargs):
            queued.append((archive.youtube_video_id, kwargs["queue_requested_at"]))
            return 0

        with mock.patch.object(
            self.admin_module, "queue_text_scan", side_effect=fake_queue_text_scan
        ), mock.patch.object(
            self.admin_module, "_livestream_frame_text_scan_rows", return_value=[]
        ):
            response = client.post(
                "/livestream_frame_text_scans",
                data={
                    "action": "queue_selected",
                    "sort": "youtube_id",
                    "selected_archive_id": [
                        str(second_archive.id),
                        str(first_archive.id),
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [youtube_id for youtube_id, _queued_at in queued],
            ["QueueSelect2", "QueueSelect1"],
        )
        self.assertLess(queued[0][1], queued[1][1])

    def test_toggle_bad_clears_text_scan_and_hides_archive(self):
        archive, capture_segment = self._archive_with_segment()
        self._admin_client()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        db.session.flush()
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        scan_segment = LivestreamFrameTextScanSegment.query.filter_by(
            scan_id=scan.id
        ).one()
        db.session.add(
            LivestreamFrameTextEvent(
                scan_id=scan.id,
                archive_id=archive.id,
                scan_segment_id=scan_segment.id,
                capture_segment_id=capture_segment.id,
                frame_second=0,
            )
        )
        db.session.commit()

        with mock.patch(
            "livestream_match_linking.clear_livestream_match_links",
            return_value={"matches": 1, "participants": 2, "associations": 1},
        ) as clear_links:
            summary = text_scan.toggle_bad_archives(db.session, [archive.id])
            db.session.commit()

        clear_links.assert_called_once_with(db.session, archive.id)
        self.assertEqual(summary["segments"], 1)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["associations"], 1)
        self.assertTrue(db.session.get(LivestreamFrameArchive, archive.id).is_bad)
        self.assertEqual(LivestreamFrameTextScan.query.count(), 0)
        self.assertEqual(LivestreamFrameTextScanSegment.query.count(), 0)
        self.assertEqual(LivestreamFrameTextEvent.query.count(), 0)
        self.assertEqual(self.admin_module._livestream_frame_text_scan_rows(), [])

        with self.assertRaisesRegex(ValueError, "bad frame archives"):
            text_scan.queue_text_scan(db.session, archive)

        summary = text_scan.toggle_bad_archives(db.session, [archive.id])
        db.session.commit()
        self.assertEqual(summary["not_bad"], 1)
        self.assertFalse(db.session.get(LivestreamFrameArchive, archive.id).is_bad)

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

    def test_worker_reset_text_scan_api_requeues_segments_and_deletes_events(self):
        archive, _ = self._archive_with_segment()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segment = LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id).one()
        text_scan.mark_text_scan_segment_success(
            db.session,
            segment,
            [text_scan.TextEventData(frame_second=0, timer_state="running")],
        )
        db.session.commit()
        client = self._admin_client()
        headers = {"X-Admin-Password": "admin"}

        reset = client.post(
            "/api/livestream_frame_archives/worker/"
            f"archives/{archive.id}/text_scan/reset",
            json={},
            headers=headers,
        )

        self.assertEqual(reset.status_code, 200)
        body = reset.get_json()
        self.assertEqual(body["scan"]["status"], "queued")
        self.assertEqual(body["scan"]["processed_segment_count"], 0)
        self.assertEqual(body["segments"][0]["status"], "queued")
        self.assertEqual(body["segments"][0]["attempt_count"], 0)
        self.assertEqual(body["segments"][0]["event_count"], 0)
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).count(),
            0,
        )

    def test_admin_text_event_capture_download_api_reads_batch_crop(self):
        archive, _ = self._archive_with_segment()
        text_scan.queue_text_scan(db.session, archive, score_engine="none")
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        segment = LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id).one()
        text_scan.mark_text_scan_segment_success(
            db.session,
            segment,
            [
                text_scan.TextEventData(
                    frame_second=12,
                    top_points=2,
                    timer_state="running",
                    timer_value="4:48",
                )
            ],
        )
        db.session.commit()
        event = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).one()
        fake_s3 = FakeS3(
            {
                "batch-0.tgz": make_tgz(
                    {
                        "000000012_score.jpg": b"score-jpg",
                        "000000012_timer.jpg": b"timer-jpg",
                    }
                )
            }
        )
        client = self._admin_client()
        with client.session_transaction() as session_data:
            session_data["logged_in"] = True

        with mock.patch.object(
            self.admin_module, "get_s3_client", return_value=fake_s3
        ), mock.patch.object(self.admin_module, "bucket_name", "bucket"):
            scoreboard = client.get(
                "/api/livestream_frame_text_scans/"
                f"{archive.id}/events/{event.id}/captures/scoreboard"
            )
            timer = client.get(
                "/api/livestream_frame_text_scans/"
                f"{archive.id}/events/{event.id}/captures/timer"
            )

        self.assertEqual(scoreboard.status_code, 200)
        self.assertEqual(scoreboard.data, b"score-jpg")
        self.assertEqual(scoreboard.mimetype, "image/jpeg")
        self.assertIn(
            f"{archive.youtube_video_id}_000000012_scoreboard.jpg",
            scoreboard.headers["Content-Disposition"],
        )
        self.assertEqual(timer.status_code, 200)
        self.assertEqual(timer.data, b"timer-jpg")
        self.assertEqual(
            fake_s3.keys,
            [("bucket", "batch-0.tgz"), ("bucket", "batch-0.tgz")],
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
