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

    def test_nearby_scores_for_same_competitor_form_an_indefinite_chain(self):
        payload = build_match_detail_payload(
            match(
                final_top_points=2,
                final_top_advantages=1,
                final_top_penalties=1,
            ),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                ),
                text_event(10, "4:50", top_points=2),
                text_event(16, "4:44", top_advantages=1),
                text_event(22, "4:38", top_penalties=1),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 1)
        self.assertEqual(score_events[0]["time"], "4:50")
        self.assertEqual(score_events[0]["videoOffsetSeconds"], 10)
        self.assertEqual(
            [action["category"] for action in score_events[0]["actions"]],
            ["points", "advantages", "penalties"],
        )

    def test_scores_more_than_six_seconds_apart_are_separate_events(self):
        payload = build_match_detail_payload(
            match(final_top_points=4),
            [
                text_event(0, "5:00", timer_state="running", top_points=0),
                text_event(10, "4:50", top_points=2),
                text_event(17, "4:43", top_points=4),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)

    def test_same_frame_scores_for_different_competitors_are_separate_events(self):
        payload = build_match_detail_payload(
            match(final_top_points=2, final_bottom_points=2),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_points=0,
                    bottom_points=0,
                ),
                text_event(10, "4:50", top_points=2, bottom_points=2),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)
        self.assertEqual(
            [event["actions"][0]["participantKey"] for event in score_events],
            ["red", "blue"],
        )

    def test_second_penalty_combines_with_opponent_advantage(self):
        payload = build_match_detail_payload(
            match(final_top_penalties=2, final_bottom_advantages=1),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_penalties=1,
                    bottom_advantages=0,
                ),
                text_event(10, "4:50", top_penalties=2),
                text_event(14, "4:46", bottom_advantages=1),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)
        penalty_event = score_events[-1]
        self.assertEqual(penalty_event["time"], "4:50")
        self.assertEqual(penalty_event["videoOffsetSeconds"], 10)
        self.assertEqual(
            [
                (
                    action["participantKey"],
                    action["category"],
                    action["delta"],
                )
                for action in penalty_event["actions"]
            ],
            [("red", "penalties", 1), ("blue", "advantages", 1)],
        )

    def test_third_penalty_combines_with_opponent_two_points(self):
        payload = build_match_detail_payload(
            match(final_top_penalties=3, final_bottom_points=2),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_penalties=2,
                    bottom_points=0,
                ),
                text_event(10, "4:50", top_penalties=3),
                text_event(16, "4:44", bottom_points=2),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)
        penalty_event = score_events[-1]
        self.assertEqual(
            [
                (action["participantKey"], action["category"], action["delta"])
                for action in penalty_event["actions"]
            ],
            [("red", "penalties", 1), ("blue", "points", 2)],
        )

    def test_nonqualifying_penalty_does_not_mix_competitor_events(self):
        payload = build_match_detail_payload(
            match(final_top_penalties=1, final_bottom_advantages=1),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_penalties=0,
                    bottom_advantages=0,
                ),
                text_event(10, "4:50", top_penalties=1),
                text_event(14, "4:46", bottom_advantages=1),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)

    def test_double_penalty_combines_both_automatic_awards(self):
        payload = build_match_detail_payload(
            match(
                final_top_points=2,
                final_top_penalties=2,
                final_bottom_advantages=1,
                final_bottom_penalties=3,
            ),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_points=0,
                    top_penalties=1,
                    bottom_advantages=0,
                    bottom_penalties=2,
                ),
                text_event(10, "4:50", top_penalties=2),
                text_event(13, "4:47", bottom_advantages=1),
                text_event(16, "4:44", bottom_penalties=3),
                text_event(22, "4:38", top_points=2),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 2)
        double_penalty_event = score_events[-1]
        self.assertEqual(double_penalty_event["time"], "4:50")
        self.assertEqual(double_penalty_event["videoOffsetSeconds"], 10)
        self.assertEqual(
            [
                (action["participantKey"], action["category"], action["delta"])
                for action in double_penalty_event["actions"]
            ],
            [
                ("red", "penalties", 1),
                ("blue", "advantages", 1),
                ("blue", "penalties", 1),
                ("red", "points", 2),
            ],
        )

    def test_double_penalty_combines_when_no_automatic_awards_are_due(self):
        payload = build_match_detail_payload(
            match(final_top_penalties=1, final_bottom_penalties=1),
            [
                text_event(
                    0,
                    "5:00",
                    timer_state="running",
                    top_penalties=0,
                    bottom_penalties=0,
                ),
                text_event(10, "4:50", top_penalties=1),
                text_event(15, "4:45", bottom_penalties=1),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual(len(score_events), 1)
        self.assertEqual(
            [action["participantKey"] for action in score_events[0]["actions"]],
            ["red", "blue"],
        )

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

    def test_event_time_pauses_while_timer_is_stopped(self):
        payload = build_match_detail_payload(
            match(final_top_points=2, final_top_advantages=1),
            [
                text_event(20, "5:00", timer_state="running", top_points=0),
                text_event(30, "4:50", timer_state="stopped"),
                text_event(50, top_points=2),
                text_event(60, "4:50", timer_state="running"),
                text_event(70, top_advantages=1),
            ],
        )

        score_events = [
            event for event in payload["events"] if event["kind"] == "score"
        ]
        self.assertEqual([event["time"] for event in score_events], ["4:50", "4:40"])

    def test_timer_reset_at_end_is_filtered_from_detail_events(self):
        payload = build_match_detail_payload(
            match(final_match_time_seconds=86, final_top_points=2),
            [
                text_event(20, "5:00", timer_state="running", top_points=0),
                text_event(70, "4:10", top_points=2),
                text_event(100, "1:26", timer_state="stopped"),
                text_event(
                    120,
                    "4:00",
                    timer_state="stopped",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                ),
            ],
        )

        self.assertEqual(
            [event["kind"] for event in payload["events"]], ["score", "final"]
        )
        self.assertEqual(payload["events"][0]["time"], "4:10")
        self.assertEqual(payload["events"][0]["totals"]["red"]["points"], 2)
        self.assertEqual(payload["events"][-1]["videoOffsetSeconds"], 100)

    def test_timer_reset_does_not_display_saved_starting_final_time(self):
        payload = build_match_detail_payload(
            match(final_match_time_seconds=360, final_top_points=2),
            [
                text_event(20, "6:00", timer_state="running", top_points=0),
                text_event(70, "5:10", top_points=2),
                text_event(100, "0:00", timer_state="stopped"),
                text_event(
                    120,
                    "6:00",
                    timer_state="stopped",
                    top_points=0,
                    top_advantages=0,
                    top_penalties=0,
                    bottom_points=0,
                    bottom_advantages=0,
                    bottom_penalties=0,
                ),
            ],
        )

        final_event = payload["events"][-1]
        self.assertEqual(final_event["kind"], "final")
        self.assertEqual(final_event["time"], "0:00")
        self.assertEqual(final_event["endingMethod"], "points")
        self.assertEqual(final_event["videoOffsetSeconds"], 100)

    def test_saved_opening_timer_final_time_is_ignored_after_clock_counts_down(self):
        payload = build_match_detail_payload(
            match(final_match_time_seconds=360, final_top_points=2),
            [
                text_event(10, "6:00", timer_state="stopped", top_points=0),
                text_event(20, "5:50", timer_state="running"),
                text_event(100, top_points=2),
            ],
        )

        final_event = payload["events"][-1]
        self.assertEqual(final_event["time"], "0:00")
        self.assertEqual(final_event["endingMethod"], "points")
        self.assertEqual(final_event["videoOffsetSeconds"], 100)

    def test_stopped_four_minute_timer_is_kept_before_clock_drops_below_four(self):
        payload = build_match_detail_payload(
            match(final_match_time_seconds=240, final_top_points=2),
            [
                text_event(20, "5:00", timer_state="running", top_points=0),
                text_event(70, "4:10", top_points=2),
                text_event(80, "4:00", timer_state="stopped"),
            ],
        )

        final_event = payload["events"][-1]
        self.assertEqual(final_event["time"], "4:00")
        self.assertEqual(final_event["endingMethod"], "Submission")
        self.assertEqual(final_event["videoOffsetSeconds"], 80)

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
