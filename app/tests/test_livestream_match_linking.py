import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    RegistrationLink,
    Team,
)
from test_db import TestDbMixin

import livestream_frame_text_scan as text_scan
from livestream_match_linking import (
    extract_match_windows,
    link_completed_text_scan,
    relink_completed_text_scans_for_events,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "livestream_match_linking"


class LivestreamMatchLinkingTestCase(TestDbMixin, unittest.TestCase):
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
        LiveStream.query.delete()
        RegistrationLink.query.delete()
        Athlete.query.delete()
        Team.query.delete()
        Division.query.delete()
        Event.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def _event_data(self, second, **kwargs):
        return text_scan.TextEventData(frame_second=second, **kwargs)

    def _fixture_events(self, fixture_name):
        fixture_path = FIXTURE_DIR / fixture_name
        payload = json.loads(fixture_path.read_text())
        ignored_fields = {"id", "match_id"}
        return [
            self._event_data(
                event["frame_second"],
                **{
                    key: value
                    for key, value in event.items()
                    if key not in ignored_fields and key != "frame_second"
                },
            )
            for event in payload["events"]
        ]

    def _stored_events(self, events):
        end_second = max(
            300,
            max((event.frame_second for event in events), default=0) + 1,
        )
        archive = LivestreamFrameArchive(
            youtube_video_id="video123",
            canonical_url="https://www.youtube.com/watch?v=video123",
            s3_prefix="livestream-frames/video123/",
            status="success",
            frame_rate=1.0,
            image_format="jpg",
        )
        db.session.add(archive)
        db.session.flush()
        capture_segment = LivestreamFrameCaptureSegment(
            archive_id=archive.id,
            start_second=0,
            end_second=end_second,
            status="success",
            uploaded_frame_count=end_second,
            sampled_frame_count=end_second,
        )
        db.session.add(capture_segment)
        db.session.flush()
        scan = LivestreamFrameTextScan(
            archive_id=archive.id,
            status="success",
            total_segment_count=1,
            processed_segment_count=1,
        )
        db.session.add(scan)
        db.session.flush()
        scan_segment = LivestreamFrameTextScanSegment(
            scan_id=scan.id,
            archive_id=archive.id,
            capture_segment_id=capture_segment.id,
            start_second=0,
            end_second=end_second,
            status="success",
        )
        db.session.add(scan_segment)
        db.session.flush()
        for event in events:
            db.session.add(text_scan.create_text_event(scan_segment, event))
        db.session.commit()
        return archive, scan

    def _linked_seconds(self, match):
        return [
            second
            for (second,) in db.session.query(LivestreamFrameTextEvent.frame_second)
            .filter(LivestreamFrameTextEvent.match_id == match.id)
            .order_by(LivestreamFrameTextEvent.frame_second)
            .all()
        ]

    def _match_setup(
        self,
        extra_pairs=None,
        pairs=None,
        match_offsets=None,
        registration_start=None,
        match_start=None,
        livestream_day_number=1,
    ):
        if registration_start is None:
            registration_start = datetime(2026, 1, 1)
        if match_start is None:
            match_start = datetime(2026, 1, 1, 9, 0)
        event = Event(
            ibjjf_id="evt-1",
            name="Test Open",
            normalized_name="test open",
            slug="test-open",
        )
        division = Division(
            gi=True,
            gender="Male",
            age="Adult",
            belt="BLACK",
            weight="Middle",
        )
        team = Team(name="Team", normalized_name="team")
        if pairs is None:
            pairs = [
                ("JOHNATHAN ALPHA", "MICHAEL BETA"),
                ("JOHNATHAN ALPHA", "CARLOS GAMMA"),
            ] + list(extra_pairs or [])
        else:
            pairs = list(pairs)
        athletes = []
        for index, pair in enumerate(pairs):
            for side, name in enumerate(pair):
                athletes.append(
                    Athlete(
                        name=name,
                        normalized_name=name.lower(),
                        slug=f"athlete-{index}-{side}",
                    )
                )
        db.session.add_all([event, division, team, *athletes])
        db.session.flush()
        db.session.add(
            RegistrationLink(
                name="Test Open",
                event_id="evt-1",
                normalized_name="test open",
                updated_at=registration_start,
                link="https://example.com",
                event_start_date=registration_start,
            )
        )
        db.session.add(
            LiveStream(
                event_id="evt-1",
                platform="youtube",
                mat_number=1,
                day_number=livestream_day_number,
                start_hour=9,
                start_minute=0,
                start_seconds=0,
                end_hour=17,
                end_minute=0,
                drift_factor=1.0,
                hide_all=False,
                link="https://www.youtube.com/watch?v=video123",
            )
        )
        matches = []
        for index in range(len(pairs)):
            pair = (athletes[index * 2], athletes[index * 2 + 1])
            if match_offsets:
                happened_at = match_start + timedelta(seconds=match_offsets[index])
            else:
                happened_at = match_start + timedelta(minutes=index)
            match = Match(
                happened_at=happened_at,
                event_id=event.id,
                division_id=division.id,
                rated=True,
                match_location="Mat 1",
                match_number=index + 1,
                fight_number=index + 1,
            )
            db.session.add(match)
            db.session.flush()
            for participant_index, athlete in enumerate(pair):
                db.session.add(
                    MatchParticipant(
                        match_id=match.id,
                        athlete_id=athlete.id,
                        team_id=team.id,
                        seed=participant_index + 1,
                        red=participant_index == 0,
                        winner=participant_index == 0,
                        start_rating=1500,
                        end_rating=1510,
                        start_match_count=0,
                        end_match_count=1,
                    )
                )
            matches.append(match)
        db.session.commit()
        return matches

    def test_relink_completed_text_scans_for_events_selects_matching_archive(self):
        self._match_setup(pairs=[("ALPHA", "BETA")])
        archive, scan = self._stored_events([])
        summary = SimpleNamespace(linked=1, windows=1, candidates=1, skipped=None)

        with patch(
            "livestream_match_linking.link_completed_text_scan",
            return_value=summary,
        ) as link_scan:
            results = relink_completed_text_scans_for_events(db.session, {"evt-1"})

        link_scan.assert_called_once_with(db.session, scan)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].archive_id, archive.id)
        self.assertEqual(results[0].linked, 1)

    def test_real_joao_maycon_fixture_links_stopped_score_update(self):
        matches = self._match_setup(
            pairs=[
                (
                    "Arthur Ronny Vital Rodrigues",
                    "Gabriel Soares Luso",
                ),
                (
                    "Maycon Eduardo Veras Santana",
                    "João Pedro da Silva Teixeira",
                ),
                (
                    "Pedro Victor Pereira Fontes",
                    "Maycon Eduardo Veras Santana",
                ),
                (
                    "Francisco de Assis da Silva Júnior",
                    "Icaro Maranhão de Queiroz",
                ),
            ],
            match_start=datetime(2026, 1, 1, 9, 0),
            match_offsets=[10620, 11160, 11520, 11880],
        )
        _, scan = self._stored_events(
            self._fixture_events("joao_maycon_stopped_score_update.json")
        )

        link_completed_text_scan(db.session, scan)
        db.session.commit()

        joao_maycon = db.session.get(Match, matches[1].id)
        self.assertEqual(joao_maycon.video_start_offset_seconds, 10981)
        self.assertEqual(
            self._linked_seconds(joao_maycon),
            [10904, 10981, 10993, 11001, 11002, 11014],
        )
        self.assertEqual(joao_maycon.final_bottom_advantages, 1)

        pedro_maycon = db.session.get(Match, matches[2].id)
        self.assertEqual(
            self._linked_seconds(pedro_maycon),
            [11288, 11321, 11411, 11471, 11499, 11556, 11613],
        )

    def test_real_atlanta_jasmine_kendra_fixture_links_until_blank(self):
        matches = self._match_setup(
            pairs=[
                ("Damel T Wigfall", "James Donald Kas"),
                ("Pedro Paulo", "Enzo Yamasaki"),
                ("Jasmine Gray Sopera", "Kendra Elizabeth"),
                ("Pedro Paulo", "Enzo Yamasaki"),
            ],
            match_start=datetime(2026, 1, 1, 9, 0),
            match_offsets=[18000, 18123, 18174, 18415],
        )
        _, scan = self._stored_events(
            self._fixture_events("atlanta_jasmine_kendra.json")
        )

        link_completed_text_scan(db.session, scan)
        db.session.commit()

        jasmine_kendra = db.session.get(Match, matches[2].id)
        self.assertEqual(jasmine_kendra.video_start_offset_seconds, 18227)
        self.assertEqual(
            self._linked_seconds(jasmine_kendra),
            [
                18174,
                18227,
                18264,
                18265,
                18267,
                18288,
                18289,
                18306,
                18341,
                18385,
                18405,
            ],
        )
        self.assertEqual(jasmine_kendra.final_top_points, 2)
        self.assertEqual(jasmine_kendra.final_bottom_points, 4)
        self.assertEqual(jasmine_kendra.final_match_time_seconds, 143)

        second_pedro_enzo = db.session.get(Match, matches[3].id)
        self.assertEqual(
            self._linked_seconds(second_pedro_enzo),
            [18415, 18433, 18446],
        )

    def test_real_nashville_repeated_athletes_split_after_blank_reset(self):
        _, scan = self._stored_events(
            self._fixture_events("nashville_kayla_lauren_twice.json")
        )
        events = (
            LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
            .order_by(LivestreamFrameTextEvent.frame_second)
            .all()
        )

        windows = extract_match_windows(events)

        kayla_lauren_windows = [
            window
            for window in windows
            if any("KAYLA" in name for name in window.top_names)
            and any("LAUREN" in name for name in window.bottom_names)
        ]
        self.assertEqual(
            [
                (window.start_second, window.end_second)
                for window in kayla_lauren_windows
            ],
            [(8273, 8996), (9070, 9112)],
        )
        self.assertEqual(kayla_lauren_windows[0].video_start_offset_seconds, 8303)
        self.assertIsNone(kayla_lauren_windows[1].video_start_offset_seconds)

    def test_day_number_uses_first_match_date_instead_of_registration_start(self):
        matches = self._match_setup(
            registration_start=datetime(2026, 1, 1),
            match_start=datetime(2026, 1, 2, 9, 0),
            livestream_day_number=1,
        )
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 20)

    def test_extract_match_windows_tracks_final_score_and_submission_timer(self):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(100, top_points=2),
                self._event_data(150, timer_state="stopped", timer_value="1:26"),
                self._event_data(
                    160, scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK
                ),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start_second, 10)
        self.assertEqual(windows[0].video_start_offset_seconds, 20)
        self.assertEqual(windows[0].final_state.top_points, 2)
        self.assertEqual(windows[0].final_state.bottom_points, 0)
        self.assertEqual(windows[0].final_timer_seconds, 86)
        self.assertTrue(windows[0].has_running_timer)

    def test_extract_match_windows_ignores_final_timer_reset(self):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="6:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="5:50"),
                self._event_data(100, top_points=2),
                self._event_data(150, timer_state="stopped", timer_value="0:30"),
                self._event_data(160, timer_state="stopped", timer_value="6:00"),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].final_timer_seconds, 30)

    def test_extract_match_windows_does_not_use_opening_timer_as_final_time(self):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="6:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="5:50"),
                self._event_data(100, top_points=2),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertIsNone(windows[0].final_timer_seconds)

    def test_extract_match_windows_keeps_four_minute_stop_before_clock_drops_below_four(
        self,
    ):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(100, top_points=2),
                self._event_data(150, timer_state="stopped", timer_value="4:00"),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].final_timer_seconds, 240)

    def test_ambiguous_repeated_athlete_without_bottom_name_is_not_linked(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
            ]
        )
        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 0)
        self.assertIsNone(
            db.session.get(Match, matches[0].id).video_start_offset_seconds
        )
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter(
                LivestreamFrameTextEvent.match_id.isnot(None)
            ).count(),
            0,
        )

    def test_forward_match_with_weak_opponent_side_waits_for_both_names(self):
        matches = self._match_setup(
            pairs=[
                ("OPENING WINNER", "OPENING LOSER"),
                ("AINISA TEKEBAEVA", "MADIHA SADIK"),
                ("GUSTAVO DO AMARAL ZANINI FRANK", "PATRYK PRUCNAL"),
            ],
            match_offsets=[20, 120, 240],
        )
        _, scan = self._stored_events(
            [
                self._event_data(
                    0,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="OPENING WINNER",
                    bottom_athlete_name="OPENING LOSER",
                ),
                self._event_data(20, timer_state="running", timer_value="4:40"),
                self._event_data(50, timer_state="stopped", timer_value="0:00"),
                self._event_data(
                    100,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="PATRYK PRUCNAL",
                    bottom_athlete_name="alph Gc",
                ),
                self._event_data(110, timer_state="running", timer_value="4:45"),
                self._event_data(
                    200,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="GUSTAVO DO AMARAL",
                    bottom_athlete_name="PATRYK PRUCNAL",
                ),
                self._event_data(220, timer_state="running", timer_value="4:40"),
                self._event_data(230, top_points=2),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 2)
        target_match = db.session.get(Match, matches[2].id)
        self.assertEqual(target_match.video_start_offset_seconds, 220)
        self.assertEqual(self._linked_seconds(target_match), [200, 220, 230])
        self.assertIsNone(
            db.session.get(Match, matches[1].id).video_start_offset_seconds
        )

    def test_completed_scan_links_match_score_timer_positions_and_events(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="1:26"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 20)
        self.assertEqual(linked_match.final_match_time_seconds, 86)
        self.assertEqual(linked_match.final_top_points, 2)
        self.assertEqual(linked_match.final_bottom_points, 0)
        participants = MatchParticipant.query.filter_by(match_id=linked_match.id).all()
        self.assertEqual(
            sorted(participant.scoreboard_position for participant in participants),
            ["bottom", "top"],
        )
        self.assertEqual(
            LivestreamFrameTextEvent.query.filter_by(match_id=linked_match.id).count(),
            4,
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()
        db.session.expire_all()

        self.assertEqual(summary.linked, 1)
        participants = MatchParticipant.query.filter_by(match_id=linked_match.id).all()
        self.assertEqual(
            sorted(participant.scoreboard_position for participant in participants),
            ["bottom", "top"],
        )

    def test_over_split_same_match_window_links_as_continuation(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="1:26"),
                self._event_data(
                    110,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="4:55",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JON ALPHA",
                    bottom_athlete_name="MICHAEL BET",
                ),
                self._event_data(120, timer_state="running", timer_value="4:40"),
                self._event_data(150, top_points=2, bottom_penalties=1),
                self._event_data(160, timer_state="stopped", timer_value="0:00"),
                self._event_data(
                    200,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="MICHAEL BET",
                    bottom_athlete_name="JON ALPHA",
                ),
                self._event_data(210, timer_state="running", timer_value="4:50"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 2)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 20)
        self.assertEqual(linked_match.final_match_time_seconds, 0)
        self.assertEqual(linked_match.final_top_points, 2)
        self.assertEqual(linked_match.final_bottom_penalties, 1)
        self.assertIsNone(
            db.session.get(Match, matches[1].id).video_start_offset_seconds
        )

        linked_seconds = [
            second
            for (second,) in db.session.query(LivestreamFrameTextEvent.frame_second)
            .filter(LivestreamFrameTextEvent.match_id == linked_match.id)
            .order_by(LivestreamFrameTextEvent.frame_second)
            .all()
        ]
        self.assertEqual(linked_seconds, [10, 20, 70, 100, 110, 120, 150, 160])

    def test_duplicate_name_rematch_does_not_steal_active_continuation(self):
        matches = self._match_setup(
            pairs=[
                ("JOHNATHAN ALPHA", "MICHAEL BETA"),
                ("ALEXIS DELTA", "JOSEPH EPSILON"),
                ("JOHNATHAN ALPHA", "MICHAEL BETA"),
            ]
        )
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="1:26"),
                self._event_data(
                    110,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="4:55",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JON ALPHA",
                    bottom_athlete_name="MICHAEL BET",
                ),
                self._event_data(120, timer_state="running", timer_value="4:40"),
                self._event_data(150, top_points=2, bottom_penalties=1),
                self._event_data(160, timer_state="stopped", timer_value="0:00"),
                self._event_data(
                    200, scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK
                ),
                self._event_data(
                    500,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(510, timer_state="running", timer_value="4:50"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 3)
        first_match = db.session.get(Match, matches[0].id)
        self.assertEqual(first_match.video_start_offset_seconds, 20)
        self.assertEqual(first_match.final_match_time_seconds, 0)
        self.assertEqual(first_match.final_bottom_penalties, 1)
        self.assertEqual(
            self._linked_seconds(first_match),
            [10, 20, 70, 100, 110, 120, 150, 160, 200],
        )

        rematch = db.session.get(Match, matches[2].id)
        self.assertEqual(rematch.video_start_offset_seconds, 510)
        self.assertEqual(self._linked_seconds(rematch), [500, 510])

    def test_closed_match_is_not_resurrected_by_continuation_fallback(self):
        matches = self._match_setup(pairs=[("JOHNATHAN ALPHA", "MICHAEL BETA")])
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="0:00"),
                self._event_data(
                    110, scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK
                ),
                self._event_data(
                    200,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(210, timer_state="running", timer_value="4:50"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 20)
        self.assertEqual(self._linked_seconds(linked_match), [10, 20, 70, 100, 110])

    def test_stopped_zero_timer_without_running_clock_finalizes_continuation(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(30, timer_state="stopped", timer_value="3:42"),
                self._event_data(
                    40,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="2:26",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JON ALPHA",
                    bottom_athlete_name="MICHAEL BET",
                ),
                self._event_data(50, timer_state="running", timer_value="2:20"),
                self._event_data(
                    60,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="0:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="J ALPHA",
                    bottom_athlete_name="BETA",
                ),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 2)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 20)
        self.assertEqual(linked_match.final_match_time_seconds, 0)
        self.assertEqual(linked_match.final_top_points, 0)
        self.assertEqual(linked_match.final_bottom_points, 0)

    def test_stopped_zero_timer_continuation_preserves_nonzero_score(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="1:26"),
                self._event_data(
                    110,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="0:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="J ALPHA",
                    bottom_athlete_name="BETA",
                ),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 2)
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.final_match_time_seconds, 0)
        self.assertEqual(linked_match.final_top_points, 2)
        self.assertEqual(linked_match.final_bottom_points, 0)

    def test_zero_score_reset_after_blank_does_not_overwrite_nonzero_final_score(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(70, top_points=2),
                self._event_data(100, timer_state="stopped", timer_value="1:26"),
                self._event_data(
                    110, scoreboard_state=text_scan.SCOREBOARD_STATE_BLANK
                ),
                self._event_data(
                    120,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="",
                    bottom_athlete_name="",
                ),
                self._event_data(
                    150,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="CARLOS GAMMA",
                ),
                self._event_data(160, timer_state="running", timer_value="4:50"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 2)
        first_match = db.session.get(Match, matches[0].id)
        self.assertEqual(first_match.final_top_points, 2)
        self.assertEqual(first_match.final_top_advantages, 0)
        self.assertEqual(first_match.final_top_penalties, 0)
        self.assertEqual(first_match.final_bottom_points, 0)
        self.assertEqual(first_match.final_bottom_advantages, 0)
        self.assertEqual(first_match.final_bottom_penalties, 0)
        self.assertEqual(first_match.final_match_time_seconds, 86)
        first_linked_seconds = [
            second
            for (second,) in db.session.query(LivestreamFrameTextEvent.frame_second)
            .filter(LivestreamFrameTextEvent.match_id == first_match.id)
            .order_by(LivestreamFrameTextEvent.frame_second)
            .all()
        ]
        self.assertEqual(first_linked_seconds, [10, 20, 70, 100, 110])

    def test_zero_score_correction_without_stopped_timer_does_not_end_window(self):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(70, top_points=2),
                self._event_data(
                    90,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                    confidence=0.99,
                ),
                self._event_data(100, top_points=4),
                self._event_data(140, timer_state="stopped", timer_value="0:20"),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].end_second, 140)
        self.assertEqual(windows[0].final_state.top_points, 4)
        self.assertEqual(windows[0].final_timer_seconds, 20)

    def test_confident_matching_names_prevent_stopped_zero_score_reset_split(self):
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(70, top_points=2),
                self._event_data(
                    90,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="2:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                    confidence=0.99,
                ),
                self._event_data(140, timer_state="stopped", timer_value="0:20"),
            ]
        )
        events = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id).all()

        windows = extract_match_windows(events)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].end_second, 140)
        self.assertEqual(windows[0].final_state.top_points, 0)
        self.assertEqual(windows[0].final_timer_seconds, 20)

    def test_loaded_names_without_running_clock_are_not_linked(self):
        matches = self._match_setup()
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 0)
        self.assertIsNone(
            db.session.get(Match, matches[0].id).video_start_offset_seconds
        )

    def test_later_running_window_links_after_cancelled_name_load(self):
        matches = self._match_setup(extra_pairs=[("ALEXIS DELTA", "JOSEPH EPSILON")])
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(
                    30,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="ALEXIS DELTA",
                    bottom_athlete_name="JOSEPH EPSILON",
                ),
                self._event_data(
                    70,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN AL",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(100, timer_state="running", timer_value="4:30"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        self.assertIsNone(
            db.session.get(Match, matches[2].id).video_start_offset_seconds
        )
        linked_match = db.session.get(Match, matches[0].id)
        self.assertEqual(linked_match.video_start_offset_seconds, 70)

    def test_ambiguous_window_prefers_next_match_in_mat_order(self):
        matches = self._match_setup(
            extra_pairs=[
                ("MADISON TAGGART", "MAYRA HIDALGO"),
                ("PEDRO MONTEIRO", "THOMAS GARZA"),
                ("DYLAN GORDON", "SCOUT GILDER"),
                ("RANDY JEMINEZ", "PEDRO MONTEIRO"),
            ]
        )
        _, scan = self._stored_events(
            [
                self._event_data(
                    0,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="MICHAEL BETA",
                ),
                self._event_data(
                    60,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="CARLOS GAMMA",
                ),
                self._event_data(
                    120,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="MADISON TAGGART",
                    bottom_athlete_name="MAYRA HIDALGO",
                ),
                self._event_data(
                    180,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="running",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="DYLAN GORDON",
                    bottom_athlete_name="SCOUT GILDER",
                ),
                self._event_data(
                    181,
                    timer_state="running",
                    timer_value="4:50",
                    top_athlete_name="RANDY JEMINEZ",
                    bottom_athlete_name="PEDRO MONTEIRO",
                ),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 4)
        self.assertEqual(
            db.session.get(Match, matches[4].id).video_start_offset_seconds, 180
        )
        self.assertIsNone(
            db.session.get(Match, matches[5].id).video_start_offset_seconds
        )

    def test_time_aligned_match_can_link_beyond_cursor_lookahead(self):
        filler_pairs = [
            (f"FILLER TOP {index}", f"FILLER BOTTOM {index}") for index in range(8)
        ]
        filler_pairs.append(("DEANDRE LORONE PARIS HUGHES", "JUSTIN STEPHEN WOOD"))
        matches = self._match_setup(extra_pairs=filler_pairs)
        target_match = matches[10]
        _, scan = self._stored_events(
            [
                self._event_data(
                    600,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="DEANDRE LORONE P",
                    bottom_athlete_name="JUSTIN STEPHEN WO",
                ),
                self._event_data(620, timer_state="running", timer_value="4:40"),
                self._event_data(650, top_points=2),
                self._event_data(680, timer_state="stopped", timer_value="0:00"),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        linked_match = db.session.get(Match, target_match.id)
        self.assertEqual(linked_match.video_start_offset_seconds, 620)
        self.assertEqual(linked_match.final_top_points, 2)
        self.assertEqual(linked_match.final_match_time_seconds, 0)

    def test_time_aligned_unused_match_can_link_after_cursor_passed_it(self):
        matches = self._match_setup(
            extra_pairs=[("EARLY FALSE WINNER", "EARLY FALSE LOSER")]
        )
        target_match = matches[1]
        _, scan = self._stored_events(
            [
                self._event_data(
                    0,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="EARLY FALSE WINNER",
                    bottom_athlete_name="EARLY FALSE LOSER",
                ),
                self._event_data(20, timer_state="running", timer_value="4:40"),
                self._event_data(
                    60,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="JOHNATHAN ALPHA",
                    bottom_athlete_name="CARLOS GAMMA",
                ),
                self._event_data(70, timer_state="running", timer_value="4:50"),
                self._event_data(80, top_points=2),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 1)
        self.assertIsNone(
            db.session.get(Match, matches[2].id).video_start_offset_seconds
        )
        linked_match = db.session.get(Match, target_match.id)
        self.assertEqual(linked_match.video_start_offset_seconds, 70)
        self.assertEqual(linked_match.final_top_points, 2)

    def test_out_of_order_forward_link_can_be_reused_when_turn_arrives(self):
        matches = self._match_setup(
            pairs=[
                ("OPENING WINNER", "OPENING LOSER"),
                ("FIRST LOWER", "FIRST OPPONENT"),
                ("SECOND LOWER", "SECOND OPPONENT"),
                ("THIRD LOWER", "THIRD OPPONENT"),
                ("FUTURE WINNER", "FUTURE OPPONENT"),
            ],
            match_offsets=[20, 120, 220, 320, 420],
        )
        _, scan = self._stored_events(
            [
                self._event_data(
                    10,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="OPENING WINNER",
                    bottom_athlete_name="OPENING LOSER",
                ),
                self._event_data(20, timer_state="running", timer_value="4:50"),
                self._event_data(50, timer_state="stopped", timer_value="0:00"),
                self._event_data(
                    70,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="FUTURE WINNER",
                    bottom_athlete_name="FUTURE OPPONENT",
                ),
                self._event_data(80, timer_state="running", timer_value="4:50"),
                self._event_data(
                    110,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="FIRST LOWER",
                    bottom_athlete_name="FIRST OPPONENT",
                ),
                self._event_data(120, timer_state="running", timer_value="4:50"),
                self._event_data(
                    210,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="SECOND LOWER",
                    bottom_athlete_name="SECOND OPPONENT",
                ),
                self._event_data(220, timer_state="running", timer_value="4:50"),
                self._event_data(
                    310,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="THIRD LOWER",
                    bottom_athlete_name="THIRD OPPONENT",
                ),
                self._event_data(320, timer_state="running", timer_value="4:50"),
                self._event_data(
                    410,
                    scoreboard_state=text_scan.SCOREBOARD_STATE_VISIBLE,
                    timer_state="stopped",
                    timer_value="5:00",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                    top_athlete_name="FUTURE WINNER",
                    bottom_athlete_name="FUTURE OPPONENT",
                ),
                self._event_data(420, timer_state="running", timer_value="4:50"),
                self._event_data(450, top_points=2),
            ]
        )

        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()

        self.assertEqual(summary.linked, 5)
        future_match = db.session.get(Match, matches[4].id)
        self.assertEqual(future_match.video_start_offset_seconds, 420)
        self.assertEqual(future_match.final_top_points, 2)
        self.assertEqual(
            self._linked_seconds(future_match),
            [410, 420, 450],
        )


if __name__ == "__main__":
    unittest.main()
