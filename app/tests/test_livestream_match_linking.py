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
    MatchParticipantTextEvent,
    RegistrationLink,
    Team,
)
from test_db import TestDbMixin

import livestream_frame_text_scan as text_scan
from livestream_match_linking import (
    extract_match_windows,
    link_completed_text_scan,
)


class LivestreamMatchLinkingTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.app_context = self.app_module.app.app_context()
        self.app_context.push()
        MatchParticipantTextEvent.query.delete()
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

    def _stored_events(self, events):
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
            end_second=300,
            status="success",
            uploaded_frame_count=300,
            sampled_frame_count=300,
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
            end_second=300,
            status="success",
        )
        db.session.add(scan_segment)
        db.session.flush()
        for event in events:
            db.session.add(text_scan.create_text_event(scan_segment, event))
        db.session.commit()
        return archive, scan

    def _match_setup(self):
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
        athletes = [
            Athlete(
                name="JOHNATHAN ALPHA", normalized_name="johnathan alpha", slug="a"
            ),
            Athlete(name="MICHAEL BETA", normalized_name="michael beta", slug="b"),
            Athlete(
                name="JOHNATHAN ALPHA", normalized_name="johnathan alpha", slug="a2"
            ),
            Athlete(name="CARLOS GAMMA", normalized_name="carlos gamma", slug="c"),
        ]
        db.session.add_all([event, division, team, *athletes])
        db.session.flush()
        db.session.add(
            RegistrationLink(
                name="Test Open",
                event_id="evt-1",
                normalized_name="test open",
                updated_at=datetime(2026, 1, 1),
                link="https://example.com",
                event_start_date=datetime(2026, 1, 1),
            )
        )
        db.session.add(
            LiveStream(
                event_id="evt-1",
                platform="youtube",
                mat_number=1,
                day_number=1,
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
        for index, pair in enumerate(
            ((athletes[0], athletes[1]), (athletes[2], athletes[3]))
        ):
            match = Match(
                happened_at=datetime(2026, 1, 1, 9, index),
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
        self.assertEqual(windows[0].final_state.top_points, 2)
        self.assertEqual(windows[0].final_state.bottom_points, 0)
        self.assertEqual(windows[0].final_timer_seconds, 86)

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
        self.assertEqual(MatchParticipantTextEvent.query.count(), 0)

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
        self.assertEqual(linked_match.video_start_offset_seconds, 10)
        self.assertEqual(linked_match.final_match_time_seconds, 86)
        self.assertEqual(linked_match.final_top_points, 2)
        self.assertEqual(linked_match.final_bottom_points, 0)
        participants = MatchParticipant.query.filter_by(match_id=linked_match.id).all()
        self.assertEqual(
            sorted(participant.scoreboard_position for participant in participants),
            ["bottom", "top"],
        )
        self.assertEqual(MatchParticipantTextEvent.query.count(), 8)


if __name__ == "__main__":
    unittest.main()
