import os
import sys
import unittest
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routes.matches import build_match_detail_payload  # noqa: E402


SCORE_FIELDS = (
    "top_points",
    "top_advantages",
    "top_penalties",
    "bottom_points",
    "bottom_advantages",
    "bottom_penalties",
)


def athlete(name, personal_name=None):
    return SimpleNamespace(name=name, personal_name=personal_name)


def participant(name, *, red, position, winner=False, note=None, personal_name=None):
    return SimpleNamespace(
        red=red,
        winner=winner,
        note=note,
        scoreboard_position=position,
        athlete=athlete(name, personal_name),
    )


def match(**kwargs):
    values = {
        "id": uuid.uuid4(),
        "participants": [
            participant(
                "John Silva",
                personal_name='John "Bones" Silva',
                red=True,
                position="top",
                winner=True,
            ),
            participant(
                "Maria Santos",
                personal_name="Maria Santos",
                red=False,
                position="bottom",
            ),
        ],
        "final_match_time_seconds": 0,
        "final_top_points": 2,
        "final_top_advantages": 0,
        "final_top_penalties": 0,
        "final_bottom_points": 0,
        "final_bottom_advantages": 0,
        "final_bottom_penalties": 0,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def text_event(frame_second, timer_value=None, timer_state=None, **kwargs):
    values = {field: None for field in SCORE_FIELDS}
    values.update(kwargs)
    return SimpleNamespace(
        frame_second=frame_second,
        timer_value=timer_value,
        timer_state=timer_state,
        **values,
    )


class MatchDetailEventsTestCase(unittest.TestCase):
    def test_wrong_athlete_correction_cancels_previous_score(self):
        payload = build_match_detail_payload(
            match(final_top_points=0, final_bottom_points=2),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                ),
                text_event(10, "4:50", top_points=2),
                text_event(12, "4:48", top_points=0),
                text_event(13, "4:47", bottom_points=2),
            ],
        )

        self.assertEqual(payload["matchTime"], "5:00")
        score_event = payload["events"][0]
        self.assertEqual(score_event["time"], "4:47")
        self.assertEqual(len(score_event["actions"]), 1)
        self.assertEqual(score_event["actions"][0]["athleteName"], "Maria")
        self.assertEqual(score_event["actions"][0]["category"], "points")
        self.assertEqual(score_event["actions"][0]["delta"], 2)
        self.assertEqual(score_event["totals"]["red"]["points"], 0)
        self.assertEqual(score_event["totals"]["blue"]["points"], 2)

    def test_partial_correction_rewrites_previous_score_amount(self):
        payload = build_match_detail_payload(
            match(final_top_points=2),
            [
                text_event(0, "5:00", timer_state="running", top_points=0),
                text_event(10, "4:50", top_points=3),
                text_event(15, "4:45", top_points=2),
            ],
        )

        score_event = payload["events"][0]
        self.assertEqual(score_event["actions"][0]["athleteName"], "John")
        self.assertEqual(score_event["actions"][0]["delta"], 2)
        self.assertEqual(score_event["totals"]["red"]["points"], 2)

    def test_correction_can_cancel_earlier_matching_score(self):
        payload = build_match_detail_payload(
            match(final_top_points=5),
            [
                text_event(0, "5:00", timer_state="running", top_points=0),
                text_event(161, top_points=2),
                text_event(260, top_points=4),
                text_event(263, top_points=7),
                text_event(266, top_points=5),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)
        self.assertEqual(score_events[0]["actions"][0]["delta"], 2)
        self.assertEqual(score_events[0]["totals"]["red"]["points"], 2)
        self.assertEqual(score_events[1]["actions"][0]["delta"], 3)
        self.assertEqual(score_events[1]["totals"]["red"]["points"], 5)

    def test_review_retraction_keeps_award_and_adds_retraction(self):
        payload = build_match_detail_payload(
            match(final_top_points=0),
            [
                text_event(0, "5:00", timer_state="running", top_points=0),
                text_event(10, "4:50", top_points=2),
                text_event(45, "4:15", top_points=0),
            ],
        )

        award_event = payload["events"][0]
        self.assertEqual(award_event["actions"][0]["verb"], "awarded")
        self.assertEqual(award_event["actions"][0]["delta"], 2)
        retraction_event = payload["events"][1]
        self.assertEqual(retraction_event["actions"][0]["kind"], "retraction")
        self.assertEqual(retraction_event["actions"][0]["delta"], -2)
        self.assertEqual(retraction_event["totals"]["red"]["points"], 0)

    def test_same_first_names_use_cleaned_full_names(self):
        payload = build_match_detail_payload(
            match(
                participants=[
                    participant(
                        "John Silva",
                        personal_name='John "Bones" Silva',
                        red=True,
                        position="top",
                        winner=True,
                    ),
                    participant(
                        "John Smith",
                        personal_name="John Smith",
                        red=False,
                        position="bottom",
                    ),
                ],
            ),
            [text_event(10, "4:50", top_points=2)],
        )

        self.assertEqual(payload["participants"][0]["name"], "John Silva")
        self.assertEqual(payload["participants"][0]["titleName"], 'John "Bones" Silva')
        self.assertEqual(
            payload["events"][0]["actions"][0]["athleteName"], "John Silva"
        )

    def test_same_timestamp_scores_are_combined_into_one_event(self):
        payload = build_match_detail_payload(
            match(final_top_points=2, final_top_advantages=1),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                ),
                text_event(10, "4:50", top_points=2, top_advantages=1),
            ],
        )

        self.assertEqual(len(payload["events"][0]["actions"]), 2)
        self.assertEqual(
            [action["category"] for action in payload["events"][0]["actions"]],
            ["points", "advantages"],
        )
        self.assertEqual(payload["events"][0]["totals"]["red"]["points"], 2)
        self.assertEqual(payload["events"][0]["totals"]["red"]["advantages"], 1)

    def test_event_time_uses_running_timer_anchor_and_frame_offset(self):
        payload = build_match_detail_payload(
            match(final_top_points=2),
            [
                text_event(20, "5:00", timer_state="running", top_points=0),
                text_event(37, top_points=2),
            ],
        )

        self.assertEqual(payload["matchTime"], "5:00")
        self.assertEqual(payload["events"][0]["time"], "4:43")
        self.assertEqual(payload["events"][0]["videoOffsetSeconds"], 37)

    def test_payload_includes_livestream_source_url_from_archive(self):
        archive = SimpleNamespace(
            canonical_url="https://www.youtube.com/watch?v=source123"
        )
        payload = build_match_detail_payload(
            match(final_top_points=2, video_link="https://youtu.be/fallback123"),
            [text_event(10, "4:50", top_points=2, archive=archive)],
        )

        self.assertEqual(
            payload["videoSourceUrl"], "https://www.youtube.com/watch?v=source123"
        )

    def test_final_event_includes_video_offset(self):
        payload = build_match_detail_payload(
            match(video_start_offset_seconds=100, final_match_time_seconds=63),
            [
                text_event(100, "5:00", timer_state="running", top_points=0),
                text_event(217, "1:03", timer_state="stopped", top_points=2),
                text_event(260, top_points=2),
            ],
        )

        self.assertEqual(payload["events"][-1]["videoOffsetSeconds"], 217)

    def test_final_method_classification(self):
        self.assertEqual(
            build_match_detail_payload(match(final_match_time_seconds=120), [])[
                "events"
            ][-1]["endingMethod"],
            "Submission",
        )
        points_event = build_match_detail_payload(
            match(final_top_points=4, final_bottom_points=2), []
        )["events"][-1]
        self.assertEqual(points_event["endingMethod"], "points")
        self.assertEqual(points_event["endingMethodAmount"], 2)

        advantage_event = build_match_detail_payload(
            match(
                final_top_points=2,
                final_bottom_points=2,
                final_top_advantages=1,
                final_bottom_advantages=0,
            ),
            [],
        )["events"][-1]
        self.assertEqual(advantage_event["endingMethod"], "advantages")
        self.assertEqual(advantage_event["endingMethodAmount"], 1)

        penalty_event = build_match_detail_payload(
            match(
                final_top_points=2,
                final_bottom_points=2,
                final_top_advantages=1,
                final_bottom_advantages=1,
                final_top_penalties=1,
                final_bottom_penalties=3,
            ),
            [],
        )["events"][-1]
        self.assertEqual(penalty_event["endingMethod"], "penalties")
        self.assertEqual(penalty_event["endingMethodAmount"], 2)

        decision_event = build_match_detail_payload(
            match(
                final_top_points=0,
                final_bottom_points=0,
                final_top_advantages=1,
                final_bottom_advantages=1,
                final_top_penalties=2,
                final_bottom_penalties=2,
            ),
            [],
        )["events"][-1]
        self.assertEqual(decision_event["endingMethod"], "Decision")
        self.assertIsNone(decision_event["endingMethodAmount"])
        self.assertEqual(
            build_match_detail_payload(
                match(
                    participants=[
                        participant(
                            "John Silva",
                            red=True,
                            position="top",
                            winner=True,
                        ),
                        participant(
                            "Maria Santos",
                            red=False,
                            position="bottom",
                            note="Disqualified",
                        ),
                    ],
                ),
                [],
            )["events"][-1]["endingMethod"],
            "DQ",
        )
        final_event = build_match_detail_payload(match(final_top_points=2), [])[
            "events"
        ][-1]
        self.assertEqual(final_event["athleteName"], "John")
        self.assertEqual(final_event["winnerKey"], "red")


if __name__ == "__main__":
    unittest.main()
