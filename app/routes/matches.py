import os
import re
import uuid
from flask import Blueprint, request, jsonify
from datetime import datetime
from collections import defaultdict
from time import time
from sqlalchemy.sql import text
from extensions import db
from constants import (
    MALE,
    FEMALE,
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    JUVENILE_AGES,
    TEEN_1,
    TEEN_2,
    TEEN_3,
    NON_ELITE_BELTS,
    GREY,
    YELLOW,
    YELLOW_GREY,
    ORANGE,
    GREEN,
    GREEN_ORANGE,
    WHITE,
    BLUE,
    PURPLE,
    BROWN,
    BLACK,
    ROOSTER,
    LIGHT_FEATHER,
    FEATHER,
    LIGHT,
    MIDDLE,
    MEDIUM_HEAVY,
    HEAVY,
    SUPER_HEAVY,
    ULTRA_HEAVY,
    OPEN_CLASS,
    OPEN_CLASS_LIGHT,
    OPEN_CLASS_HEAVY,
)
from models import (
    Athlete,
    MatchParticipant,
    Division,
    Match,
    Event,
    LivestreamFrameTextEvent,
)
from elo import RATING_VERY_IMMATURE_COUNT
from photos import get_public_photo_url, get_s3_client
from normalize import normalize
from livestreams import (
    get_livestream_link,
    load_linked_archive_video_links,
    load_livestream_links,
)

matches_route = Blueprint("matches_route", __name__)

MATCH_PAGE_SIZE = 12
ATHLETES_MATCH_PAGE_SIZE = 100

INITIAL_RATE_LIMIT = 15
RATE_LIMIT_WINDOW = 10
PENALTY_PERIOD = 60
REVIEW_RETRACTION_SECONDS = 30
MATCH_DETAIL_RESET_TIMER_SECONDS = 4 * 60
MATCH_DETAIL_EVENT_COMBINE_SECONDS = 6
MATCH_DETAIL_TRANSIENT_SCORE_DIP_SECONDS = 6
SCORE_CATEGORIES = ("points", "advantages", "penalties")
SCORE_POSITIONS = ("top", "bottom")
DQ_TYPE_NOTES: dict[str, tuple[str, ...]] = {
    "technical": ("Disqualified by technical desc.", "Disqualified by desc técnica"),
    "disciplinary": (
        "Disqualified by disciplinary desc.",
        "Disqualified by desc disciplinar",
    ),
}
client_requests = defaultdict(list)
client_penalties = {}


def _clean_display_name(name):
    if not name:
        return ""
    return re.sub(r'\s*"[^"]*"', "", name).strip()


def _first_name(name):
    cleaned = _clean_display_name(name)
    return cleaned.split()[0] if cleaned else ""


def _format_match_time(seconds):
    if seconds is None:
        return None
    minutes, remainder = divmod(max(0, seconds), 60)
    return f"{minutes}:{remainder:02d}"


def _parse_match_time(value):
    if not value:
        return None
    parts = str(value).split(":")
    if len(parts) != 2:
        return None
    try:
        minutes = int(parts[0])
        seconds = int(parts[1])
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return minutes * 60 + seconds


def _event_match_time(timer_anchor, frame_second, fallback_time):
    if timer_anchor is None:
        return fallback_time
    anchor_seconds, anchor_frame_second = timer_anchor
    elapsed_seconds = max(0, frame_second - anchor_frame_second)
    return _format_match_time(anchor_seconds - elapsed_seconds)


def _looks_like_starting_timer_seconds(seconds):
    return (
        seconds is not None
        and seconds >= MATCH_DETAIL_RESET_TIMER_SECONDS
        and seconds % 60 == 0
    )


def _trim_match_detail_timer_reset_events(raw_events):
    min_timer_seconds = None
    saw_non_zero_score = False
    saw_blank_after_score = False
    for index, raw_event in enumerate(raw_events):
        if any(
            (getattr(raw_event, f"{position}_{category}", None) or 0) != 0
            for position in SCORE_POSITIONS
            for category in SCORE_CATEGORIES
        ):
            saw_non_zero_score = True
        if (
            saw_non_zero_score
            and getattr(raw_event, "scoreboard_state", None) == "blank"
        ):
            saw_blank_after_score = True

        timer_seconds = _parse_match_time(getattr(raw_event, "timer_value", None))
        if timer_seconds is None:
            continue
        looks_like_reset = (
            min_timer_seconds is not None
            and timer_seconds > min_timer_seconds
            and _looks_like_starting_timer_seconds(timer_seconds)
        )
        if looks_like_reset:
            if saw_blank_after_score:
                return raw_events[:index]
            min_timer_seconds = timer_seconds
            continue
        min_timer_seconds = (
            timer_seconds
            if min_timer_seconds is None
            else min(min_timer_seconds, timer_seconds)
        )
    return raw_events


def _has_dq_note(match):
    notes = " ".join(
        participant.note or "" for participant in getattr(match, "participants", [])
    ).lower()
    return "disqualified" in notes or "desqualificado" in notes


def _match_detail_participants(match):
    participants = sorted(match.participants, key=lambda p: 0 if p.red else 1)
    if len(participants) != 2:
        return [], {}

    bases = [
        _clean_display_name(
            participant.athlete.personal_name or participant.athlete.name
        )
        for participant in participants
    ]
    title_names = [
        participant.athlete.personal_name or participant.athlete.name
        for participant in participants
    ]
    first_names = [_first_name(base) for base in bases]
    use_full_names = (
        first_names[0]
        and first_names[1]
        and first_names[0].lower() == first_names[1].lower()
    )

    participant_payload = []
    participants_by_position = {}
    fallback_positions = {True: "top", False: "bottom"}

    for index, participant in enumerate(participants):
        key = "red" if participant.red else "blue"
        display_name = (
            bases[index] if use_full_names else first_names[index] or bases[index]
        )
        position = (
            participant.scoreboard_position or fallback_positions[participant.red]
        )
        payload = {
            "key": key,
            "name": display_name,
            "fullName": bases[index],
            "titleName": title_names[index],
            "scoreboardPosition": position,
        }
        participant_payload.append(payload)
        if position in SCORE_POSITIONS:
            participants_by_position[position] = payload

    return participant_payload, participants_by_position


def _empty_totals():
    return {
        "red": {"points": 0, "advantages": 0, "penalties": 0},
        "blue": {"points": 0, "advantages": 0, "penalties": 0},
    }


def _copy_totals(totals):
    return {
        side: {category: values[category] for category in SCORE_CATEGORIES}
        for side, values in totals.items()
    }


def _find_prior_score_event(events, position, category):
    for event in reversed(events):
        if (
            event["kind"] == "score"
            and not event.get("cancelled")
            and event["position"] == position
            and event["category"] == category
            and event["delta"] > 0
        ):
            return event
    return None


def _find_prior_score_event_with_delta(events, position, category, delta):
    for event in reversed(events):
        if (
            event["kind"] == "score"
            and not event.get("cancelled")
            and event["position"] == position
            and event["category"] == category
            and event["delta"] == delta
        ):
            return event
    return None


def _cancel_prior_score_events(events, position, category, amount):
    remaining = amount
    exact_event = _find_prior_score_event_with_delta(
        events, position, category, remaining
    )
    if exact_event is not None:
        exact_event["cancelled"] = True
        return

    while remaining > 0:
        event = _find_prior_score_event(events, position, category)
        if event is None:
            break
        if event["delta"] > remaining:
            event["delta"] -= remaining
            remaining = 0
        else:
            remaining -= event["delta"]
            event["cancelled"] = True


def _score_dip_recovers_quickly(
    raw_events, event_index, field, prior_value, dipped_value
):
    """Return whether a lower reading is promptly restored for one score field."""
    dip_event = raw_events[event_index]
    for later_event in raw_events[event_index + 1 :]:
        if (
            later_event.frame_second - dip_event.frame_second
            > MATCH_DETAIL_TRANSIENT_SCORE_DIP_SECONDS
        ):
            return False

        later_value = getattr(later_event, field)
        if later_value is None or later_value == dipped_value:
            continue

        return later_value >= prior_value

    return False


def _match_detail_events_are_close(first_event, second_event):
    return (
        0
        <= second_event["frameSecond"] - first_event["frameSecond"]
        <= MATCH_DETAIL_EVENT_COMBINE_SECONDS
    )


def _is_penalty_event(event):
    return (
        event["kind"] == "score"
        and event["category"] == "penalties"
        and event["delta"] > 0
    )


def _automatic_penalty_award(penalty_event):
    if not _is_penalty_event(penalty_event):
        return None
    if penalty_event["scoreTotal"] == 2:
        return "advantages", 1
    if penalty_event["scoreTotal"] == 3:
        return "points", 2
    return None


def _is_automatic_penalty_award(penalty_event, award_event):
    expected_award = _automatic_penalty_award(penalty_event)
    return (
        expected_award is not None
        and _match_detail_events_are_close(penalty_event, award_event)
        and award_event["kind"] == "score"
        and award_event["participantKey"] != penalty_event["participantKey"]
        and (award_event["category"], award_event["delta"]) == expected_award
    )


def _double_penalty_group_end(events, start):
    first_penalty = events[start]
    if not _is_penalty_event(first_penalty):
        return None

    second_penalty_index = start + 1
    if second_penalty_index < len(events) and _is_automatic_penalty_award(
        first_penalty, events[second_penalty_index]
    ):
        second_penalty_index += 1

    if second_penalty_index >= len(events):
        return None

    second_penalty = events[second_penalty_index]
    previous_event = events[second_penalty_index - 1]
    if (
        not _is_penalty_event(second_penalty)
        or second_penalty["participantKey"] == first_penalty["participantKey"]
        or not _match_detail_events_are_close(previous_event, second_penalty)
    ):
        return None

    group_end = second_penalty_index + 1
    if group_end < len(events) and _is_automatic_penalty_award(
        second_penalty, events[group_end]
    ):
        group_end += 1
    return group_end


def _group_match_detail_semantic_events(semantic_events):
    score_totals = defaultdict(int)
    events = []
    for event in semantic_events:
        if event.get("cancelled"):
            continue
        score_total_key = (event["participantKey"], event["category"])
        score_totals[score_total_key] += event["delta"]
        event["scoreTotal"] = score_totals[score_total_key]
        events.append(event)

    event_groups = []
    index = 0

    while index < len(events):
        special_group_end = _double_penalty_group_end(events, index)
        if special_group_end is None and index + 1 < len(events):
            if _is_automatic_penalty_award(events[index], events[index + 1]):
                special_group_end = index + 2

        if special_group_end is not None:
            event_groups.append(events[index:special_group_end])
            index = special_group_end
            continue

        event = events[index]
        previous_group = event_groups[-1] if event_groups else None
        previous_group_participants = (
            {item["participantKey"] for item in previous_group}
            if previous_group
            else set()
        )
        if (
            previous_group
            and len(previous_group_participants) == 1
            and event["participantKey"] in previous_group_participants
            and _match_detail_events_are_close(previous_group[-1], event)
        ):
            previous_group.append(event)
        else:
            event_groups.append([event])
        index += 1

    return event_groups


def _build_match_detail_score_events(raw_events, participants_by_position):
    score_state = {
        f"{position}_{category}": 0
        for position in SCORE_POSITIONS
        for category in SCORE_CATEGORIES
    }
    semantic_events = []
    current_timer = None
    timer_anchor = None
    match_time = None
    last_score_change_frame = None

    for raw_event_index, raw_event in enumerate(raw_events):
        timer_state = getattr(raw_event, "timer_state", None)
        if timer_state == "stopped":
            timer_anchor = None

        if raw_event.timer_value is not None:
            current_timer = raw_event.timer_value
            if timer_state == "running":
                timer_seconds = _parse_match_time(raw_event.timer_value)
                if timer_seconds is not None:
                    timer_anchor = (timer_seconds, raw_event.frame_second)
                    if match_time is None:
                        match_time = raw_event.timer_value

        for position in SCORE_POSITIONS:
            participant = participants_by_position.get(position)
            if participant is None:
                continue

            for category in SCORE_CATEGORIES:
                field = f"{position}_{category}"
                value = getattr(raw_event, field)
                if value is None:
                    continue

                old_value = score_state[field] or 0
                delta = value - old_value
                if delta == 0:
                    continue

                if delta < 0 and _score_dip_recovers_quickly(
                    raw_events, raw_event_index, field, old_value, value
                ):
                    continue

                score_state[field] = value

                prior_event = _find_prior_score_event(
                    semantic_events, position, category
                )
                review_retraction = (
                    delta < 0
                    and prior_event is not None
                    and last_score_change_frame is not None
                    and raw_event.frame_second - last_score_change_frame
                    >= REVIEW_RETRACTION_SECONDS
                )

                if delta > 0:
                    semantic_events.append(
                        {
                            "kind": "score",
                            "frameSecond": raw_event.frame_second,
                            "time": _event_match_time(
                                timer_anchor, raw_event.frame_second, current_timer
                            ),
                            "position": position,
                            "participantKey": participant["key"],
                            "athleteName": participant["name"],
                            "category": category,
                            "delta": delta,
                        }
                    )
                elif review_retraction:
                    prior_event["verb"] = "awarded"
                    semantic_events.append(
                        {
                            "kind": "retraction",
                            "frameSecond": raw_event.frame_second,
                            "time": _event_match_time(
                                timer_anchor, raw_event.frame_second, current_timer
                            ),
                            "position": position,
                            "participantKey": participant["key"],
                            "athleteName": participant["name"],
                            "category": category,
                            "delta": delta,
                        }
                    )
                else:
                    _cancel_prior_score_events(
                        semantic_events, position, category, abs(delta)
                    )

                last_score_change_frame = raw_event.frame_second

    totals = _empty_totals()
    response_events = []

    for event_group in _group_match_detail_semantic_events(semantic_events):
        first_event = event_group[0]
        response_event = {
            "kind": "score",
            "time": first_event["time"],
            "videoOffsetSeconds": first_event["frameSecond"],
            "actions": [],
            "totals": _copy_totals(totals),
        }
        for event in event_group:
            totals[event["participantKey"]][event["category"]] += event["delta"]
            response_event["actions"].append(
                {
                    "kind": event["kind"],
                    "participantKey": event["participantKey"],
                    "athleteName": event["athleteName"],
                    "category": event["category"],
                    "delta": event["delta"],
                    "verb": event.get("verb"),
                }
            )
        response_event["totals"] = _copy_totals(totals)
        response_events.append(response_event)

    return response_events, match_time


def _match_detail_video_source_url(match, raw_events):
    for raw_event in raw_events:
        archive = getattr(raw_event, "archive", None)
        canonical_url = getattr(archive, "canonical_url", None)
        if canonical_url:
            return canonical_url

    return getattr(match, "video_link", None)


def _final_totals(match, participants):
    totals = _empty_totals()
    by_position = {
        participant["scoreboardPosition"]: participant for participant in participants
    }
    for position in SCORE_POSITIONS:
        participant = by_position.get(position)
        if participant is None:
            continue
        for category in SCORE_CATEGORIES:
            value = getattr(match, f"final_{position}_{category}")
            totals[participant["key"]][category] = value or 0
    return totals


def _winner_loser_participants(match):
    winner = None
    loser = None
    for participant in match.participants:
        if participant.winner:
            winner = participant
        else:
            loser = participant
    if winner is None or loser is None:
        return None, None
    return winner, loser


def _score_for_participant(match, participant, category):
    fallback_positions = {True: "top", False: "bottom"}
    position = participant.scoreboard_position or fallback_positions[participant.red]
    if position not in SCORE_POSITIONS:
        return 0
    return getattr(match, f"final_{position}_{category}") or 0


def _ending_method(match, final_match_time_seconds):
    if _has_dq_note(match):
        return {"category": "DQ", "amount": None}
    if final_match_time_seconds is None:
        return {"category": "Final", "amount": None}
    if final_match_time_seconds > 0:
        return {"category": "Submission", "amount": None}

    winner, loser = _winner_loser_participants(match)
    if winner is None or loser is None:
        return {"category": "Final", "amount": None}

    for category in SCORE_CATEGORIES:
        winner_score = _score_for_participant(match, winner, category)
        loser_score = _score_for_participant(match, loser, category)
        if winner_score != loser_score:
            return {
                "category": category,
                "amount": abs(winner_score - loser_score),
            }

    return {"category": "Decision", "amount": None}


def _winner_key(match):
    for participant in match.participants:
        if participant.winner:
            return "red" if participant.red else "blue"
    return None


def _final_video_offset_seconds(
    raw_events, final_match_time_seconds, *, ignore_starting_timer_offsets=False
):
    if not raw_events:
        return None

    stopped_timer_offsets = []
    matching_stopped_timer_offsets = []

    for raw_event in raw_events:
        if getattr(raw_event, "timer_state", None) != "stopped":
            continue

        parsed_timer_seconds = _parse_match_time(
            getattr(raw_event, "timer_value", None)
        )
        if parsed_timer_seconds is None:
            continue

        if not (
            ignore_starting_timer_offsets
            and _looks_like_starting_timer_seconds(parsed_timer_seconds)
        ):
            stopped_timer_offsets.append(raw_event.frame_second)
        if (
            final_match_time_seconds is not None
            and parsed_timer_seconds == final_match_time_seconds
        ):
            matching_stopped_timer_offsets.append(raw_event.frame_second)

    if matching_stopped_timer_offsets:
        return matching_stopped_timer_offsets[-1]
    if stopped_timer_offsets:
        return stopped_timer_offsets[-1]

    return raw_events[-1].frame_second


def _last_non_starting_stopped_timer_seconds(raw_events):
    final_timer_seconds = None
    for raw_event in raw_events:
        if getattr(raw_event, "timer_state", None) != "stopped":
            continue
        timer_seconds = _parse_match_time(getattr(raw_event, "timer_value", None))
        if timer_seconds is None:
            continue
        if not _looks_like_starting_timer_seconds(timer_seconds):
            final_timer_seconds = timer_seconds
    return final_timer_seconds


def _min_match_detail_timer_seconds(raw_events):
    timer_values = [
        timer_seconds
        for raw_event in raw_events
        if (timer_seconds := _parse_match_time(getattr(raw_event, "timer_value", None)))
        is not None
    ]
    return min(timer_values) if timer_values else None


def _stored_final_timer_looks_like_reset(
    final_match_time_seconds, raw_events, reset_events_removed
):
    if not _looks_like_starting_timer_seconds(final_match_time_seconds):
        return False
    if reset_events_removed:
        return True
    min_timer_seconds = _min_match_detail_timer_seconds(raw_events)
    return (
        min_timer_seconds is not None and final_match_time_seconds > min_timer_seconds
    )


def _match_detail_final_match_time_seconds(
    match, raw_events, final_timer_looks_like_reset
):
    final_match_time_seconds = getattr(match, "final_match_time_seconds", None)
    if final_timer_looks_like_reset:
        final_match_time_seconds = _last_non_starting_stopped_timer_seconds(raw_events)
        if final_match_time_seconds is None:
            final_match_time_seconds = 0
    return final_match_time_seconds


def build_match_detail_payload(match, raw_events):
    original_raw_event_count = len(raw_events)
    raw_events = _trim_match_detail_timer_reset_events(raw_events)
    reset_events_removed = len(raw_events) < original_raw_event_count
    video_source_url = _match_detail_video_source_url(match, raw_events)
    participants, participants_by_position = _match_detail_participants(match)
    events, match_time = _build_match_detail_score_events(
        raw_events, participants_by_position
    )
    final_timer_looks_like_reset = _stored_final_timer_looks_like_reset(
        getattr(match, "final_match_time_seconds", None),
        raw_events,
        reset_events_removed,
    )
    final_match_time_seconds = _match_detail_final_match_time_seconds(
        match, raw_events, final_timer_looks_like_reset
    )
    ending_method = _ending_method(match, final_match_time_seconds)
    winner_key = _winner_key(match)
    winner_name = next(
        (
            participant["name"]
            for participant in participants
            if participant["key"] == winner_key
        ),
        None,
    )
    events.append(
        {
            "kind": "final",
            "time": _format_match_time(final_match_time_seconds),
            "videoOffsetSeconds": _final_video_offset_seconds(
                raw_events,
                final_match_time_seconds,
                ignore_starting_timer_offsets=final_timer_looks_like_reset,
            ),
            "endingMethod": ending_method["category"],
            "endingMethodAmount": ending_method["amount"],
            "winnerKey": winner_key,
            "athleteName": winner_name,
            "totals": _final_totals(match, participants),
        }
    )
    return {
        "matchId": str(match.id),
        "matchTime": match_time,
        "videoSourceUrl": video_source_url,
        "participants": participants,
        "events": events,
    }


def rate_limit():
    client_ip = request.headers.get("CF-Connecting-IP")
    if not client_ip:
        client_ip = request.headers.get("DO-Connecting-IP")
        if not client_ip:
            return

    current_time = time()
    request_times = client_requests[client_ip]
    penalty_info = client_penalties.get(
        client_ip, {"rate_limit": INITIAL_RATE_LIMIT, "penalty_end": 0}
    )

    if current_time > penalty_info["penalty_end"]:
        penalty_info["rate_limit"] = INITIAL_RATE_LIMIT
        penalty_info["penalty_end"] = 0
        client_penalties[client_ip] = penalty_info

    while request_times and request_times[0] < current_time - RATE_LIMIT_WINDOW:
        request_times.pop(0)

    if len(request_times) >= penalty_info["rate_limit"]:
        penalty_info["rate_limit"] = max(1, penalty_info["rate_limit"] // 2)
        penalty_info["penalty_end"] = current_time + PENALTY_PERIOD
        client_penalties[client_ip] = penalty_info
        return jsonify({"error": "Too many requests"}), 429

    request_times.append(current_time)


matches_route.before_request(rate_limit)


@matches_route.route("/api/matches/<match_id>/detail-events")
def match_detail_events(match_id):
    try:
        match_uuid = uuid.UUID(match_id)
    except ValueError:
        return jsonify({"error": "Match not found"}), 404

    match = db.session.query(Match).filter(Match.id == match_uuid).first()
    if match is None:
        return jsonify({"error": "Match not found"}), 404

    raw_events = (
        db.session.query(LivestreamFrameTextEvent)
        .filter(LivestreamFrameTextEvent.match_id == match.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    return jsonify(build_match_detail_payload(match, raw_events))


@matches_route.route("/api/matches")
def matches():
    gi = request.args.get("gi")
    athlete_id = request.args.get("athlete_id")
    athlete_name = request.args.get("athlete_name")
    athlete_name2 = request.args.get("athlete_name2")
    team_name = request.args.get("team_name")
    country = request.args.get("country")
    event_name = request.args.get("event_name")
    gender_male = request.args.get("gender_male")
    gender_female = request.args.get("gender_female")
    age_adult = request.args.get("age_adult")
    age_master1 = request.args.get("age_master1")
    age_master2 = request.args.get("age_master2")
    age_master3 = request.args.get("age_master3")
    age_master4 = request.args.get("age_master4")
    age_master5 = request.args.get("age_master5")
    age_master6 = request.args.get("age_master6")
    age_master7 = request.args.get("age_master7")
    age_juvenile = request.args.get("age_juvenile")
    age_teen = request.args.get("age_teen")
    belt_grey = request.args.get("belt_grey")
    belt_yellow = request.args.get("belt_yellow")
    belt_orange = request.args.get("belt_orange")
    belt_green = request.args.get("belt_green")
    belt_white = request.args.get("belt_white")
    belt_blue = request.args.get("belt_blue")
    belt_purple = request.args.get("belt_purple")
    belt_brown = request.args.get("belt_brown")
    belt_black = request.args.get("belt_black")
    weight_rooster = request.args.get("weight_rooster")
    weight_light_feather = request.args.get("weight_light_feather")
    weight_feather = request.args.get("weight_feather")
    weight_light = request.args.get("weight_light")
    weight_middle = request.args.get("weight_middle")
    weight_medium_heavy = request.args.get("weight_medium_heavy")
    weight_heavy = request.args.get("weight_heavy")
    weight_super_heavy = request.args.get("weight_super_heavy")
    weight_ultra_heavy = request.args.get("weight_ultra_heavy")
    weight_open_class = request.args.get("weight_open_class")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    mat_number = request.args.get("mat_number")
    dq_type_technical = request.args.get("dq_type_technical")
    dq_type_disciplinary = request.args.get("dq_type_disciplinary")
    has_score = request.args.get("has_score")
    submission = request.args.get("submission")
    comeback_submission = request.args.get("comeback_submission")
    minimum_points = request.args.get("minimum_points")
    minimum_advantages = request.args.get("minimum_advantages")
    minimum_penalties = request.args.get("minimum_penalties")
    score_differential = request.args.get("score_differential")
    referee_decision = request.args.get("referee_decision")
    rating_start = request.args.get("rating_start")
    rating_end = request.args.get("rating_end")
    elite_only = request.args.get("elite_only")
    page = request.args.get("page") or 1

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter"}), 400

    try:
        page = int(page)
        if page < 1:
            raise ValueError()
    except ValueError:
        return jsonify({"error": "Invalid page number"}), 400

    def parse_nonnegative_int(value):
        if value is None:
            return None
        parsed = int(value)
        if parsed < 0:
            raise ValueError()
        return parsed

    try:
        minimum_points = parse_nonnegative_int(minimum_points)
        minimum_advantages = parse_nonnegative_int(minimum_advantages)
        minimum_penalties = parse_nonnegative_int(minimum_penalties)
        score_differential = parse_nonnegative_int(score_differential)
    except ValueError:
        return jsonify({"error": "Invalid score filter value"}), 400

    if gi:
        gi = gi.lower() == "true"
    if gender_male:
        gender_male = gender_male.lower() == "true"
    if gender_female:
        gender_female = gender_female.lower() == "true"
    if age_adult:
        age_adult = age_adult.lower() == "true"
    if age_master1:
        age_master1 = age_master1.lower() == "true"
    if age_master2:
        age_master2 = age_master2.lower() == "true"
    if age_master3:
        age_master3 = age_master3.lower() == "true"
    if age_master4:
        age_master4 = age_master4.lower() == "true"
    if age_master5:
        age_master5 = age_master5.lower() == "true"
    if age_master6:
        age_master6 = age_master6.lower() == "true"
    if age_master7:
        age_master7 = age_master7.lower() == "true"
    if age_juvenile:
        age_juvenile = age_juvenile.lower() == "true"
    if age_teen:
        age_teen = age_teen.lower() == "true"
    if belt_grey:
        belt_grey = belt_grey.lower() == "true"
    if belt_yellow:
        belt_yellow = belt_yellow.lower() == "true"
    if belt_orange:
        belt_orange = belt_orange.lower() == "true"
    if belt_green:
        belt_green = belt_green.lower() == "true"
    if belt_white:
        belt_white = belt_white.lower() == "true"
    if belt_blue:
        belt_blue = belt_blue.lower() == "true"
    if belt_purple:
        belt_purple = belt_purple.lower() == "true"
    if belt_brown:
        belt_brown = belt_brown.lower() == "true"
    if belt_black:
        belt_black = belt_black.lower() == "true"
    if weight_rooster:
        weight_rooster = weight_rooster.lower() == "true"
    if weight_light_feather:
        weight_light_feather = weight_light_feather.lower() == "true"
    if weight_feather:
        weight_feather = weight_feather.lower() == "true"
    if weight_light:
        weight_light = weight_light.lower() == "true"
    if weight_middle:
        weight_middle = weight_middle.lower() == "true"
    if weight_medium_heavy:
        weight_medium_heavy = weight_medium_heavy.lower() == "true"
    if weight_heavy:
        weight_heavy = weight_heavy.lower() == "true"
    if weight_super_heavy:
        weight_super_heavy = weight_super_heavy.lower() == "true"
    if weight_ultra_heavy:
        weight_ultra_heavy = weight_ultra_heavy.lower() == "true"
    if weight_open_class:
        weight_open_class = weight_open_class.lower() == "true"
    dq_type_technical = (dq_type_technical or "").lower() == "true"
    dq_type_disciplinary = (dq_type_disciplinary or "").lower() == "true"
    has_score = (has_score or "").lower() == "true"
    submission = (submission or "").lower() == "true"
    comeback_submission = (comeback_submission or "").lower() == "true"
    referee_decision = (referee_decision or "").lower() == "true"
    if elite_only:
        elite_only = elite_only.lower() == "true"

    params = {"gi": gi}

    filters = ""

    if athlete_id:
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND mp.athlete_id = :athlete_id
        )
        """
        if os.environ.get("DATABASE_URL"):
            params["athlete_id"] = athlete_id
        else:
            params["athlete_id"] = athlete_id.replace("-", "")

    def get_athlete_name_clause(name, variable):
        clause = ""
        exact = name.strip().startswith('"') and name.strip().endswith('"')
        if exact:
            name = name.strip()[1:-1]
            clause = f"""EXISTS (
                SELECT 1
                FROM athletes a
                JOIN match_participants mp ON a.id = mp.athlete_id
                WHERE mp.match_id = m.id
                AND (
                    (a.hide_full_name IS TRUE AND a.normalized_personal_name = :{variable})
                    OR (a.hide_full_name IS NOT TRUE AND a.normalized_name = :{variable})
                )
            )
            """
            params[variable] = normalize(name)
        elif os.getenv("DATABASE_URL"):
            # Use full-text search
            search_terms = " & ".join([term + ":*" for term in normalize(name).split()])
            clause = f"""EXISTS (
                    SELECT 1
                    FROM athletes a
                    JOIN match_participants mp ON a.id = mp.athlete_id
                    WHERE mp.match_id = m.id
                    AND (
                        (a.hide_full_name IS TRUE AND a.normalized_personal_name_tsvector @@ to_tsquery('simple', :{variable}))
                        OR (
                            a.hide_full_name IS NOT TRUE
                            AND (
                                a.normalized_name_tsvector @@ to_tsquery('simple', :{variable})
                                OR a.normalized_personal_name_tsvector @@ to_tsquery('simple', :{variable})
                            )
                        )
                    )
                )"""
            params[variable] = search_terms
        else:
            # Fallback to LIKE search
            like_clauses = []
            for index, name_part in enumerate(normalize(name).split()):
                like_clauses.append(
                    f"""EXISTS (
                    SELECT 1
                    FROM athletes a
                    JOIN match_participants mp ON a.id = mp.athlete_id
                    WHERE mp.match_id = m.id
                    AND (
                        (a.hide_full_name IS TRUE AND a.normalized_personal_name LIKE :{variable}_{index})
                        OR (
                            a.hide_full_name IS NOT TRUE
                            AND (
                                a.normalized_name LIKE :{variable}_{index}
                                OR a.normalized_personal_name LIKE :{variable}_{index}
                            )
                        )
                    )
                )"""
                )
                params[f"{variable}_{index}"] = f"%{name_part}%"
            if like_clauses:
                clause = "(" + " AND ".join(like_clauses) + ")"
            else:
                clause = "1=1"
        return clause

    athlete_team_clauses = []

    if athlete_name:
        athlete_team_clauses.append(
            get_athlete_name_clause(athlete_name, "athlete_name")
        )
    if team_name:
        operator = "LIKE"
        exact = team_name.strip().startswith('"') and team_name.strip().endswith('"')
        if exact:
            operator = "="
            team_name = team_name.strip()[1:-1]
            params["team_name"] = normalize(team_name)
        else:
            params["team_name"] = f"%{normalize(team_name)}%"
        athlete_team_clauses.append(
            f"""EXISTS (
            SELECT 1
            FROM match_participants mp
            JOIN teams t ON t.id = mp.team_id
            WHERE mp.match_id = m.id
            AND t.normalized_name {operator} :team_name
        )"""
        )

    if country:
        country = country.strip().lower()[:2]
        athlete_team_clauses.append(
            """EXISTS (
            SELECT 1
            FROM match_participants mp
            JOIN athletes a ON a.id = mp.athlete_id
            WHERE mp.match_id = m.id
            AND LOWER(SUBSTR(TRIM(a.country), 1, 2)) = :country
        )"""
        )
        params["country"] = country

    if athlete_team_clauses:
        filters += "AND (" + " OR ".join(athlete_team_clauses) + ")\n"

    if elite_only:
        non_elite_belt_params = {
            f"non_elite_belt_{index}": belt
            for index, belt in enumerate(sorted(NON_ELITE_BELTS))
        }
        filters += f"""AND EXISTS (
            SELECT 1
            FROM match_participants mp
            JOIN athlete_ratings ar ON ar.athlete_id = mp.athlete_id
            WHERE mp.match_id = m.id
            AND ar.gi = :gi
            AND ar.rank IS NOT NULL
            AND ar.match_count > :elite_min_match_count
            AND ar.percentile IS NOT NULL
            AND ROUND(ar.percentile * 100) <= 10
            AND ar.age IN (:elite_age_adult, :elite_age_juvenile, :elite_age_juvenile_1, :elite_age_juvenile_2)
            AND ar.belt NOT IN ({", ".join(f":{key}" for key in non_elite_belt_params)})
        )
        """
        params.update(
            {
                "elite_min_match_count": RATING_VERY_IMMATURE_COUNT,
                "elite_age_adult": ADULT,
                "elite_age_juvenile": JUVENILE,
                "elite_age_juvenile_1": JUVENILE_1,
                "elite_age_juvenile_2": JUVENILE_2,
                **non_elite_belt_params,
            }
        )

    if athlete_name2:
        filters += (
            "AND " + get_athlete_name_clause(athlete_name2, "athlete_name2") + "\n"
        )

    if event_name:
        operator = "LIKE"
        exact = event_name.strip().startswith('"') and event_name.strip().endswith('"')
        if exact:
            operator = "="
            event_name = event_name.strip()[1:-1]
        filters += f"AND e.normalized_name {operator} :event_name\n"
        if exact:
            params["event_name"] = normalize(event_name)
        else:
            params["event_name"] = f"%{normalize(event_name)}%"

    genders = []
    if gender_male:
        genders.append(MALE)
    if gender_female:
        genders.append(FEMALE)
    if len(genders):
        filters += "AND d.gender IN (" + ", ".join(f"'{g}'" for g in genders) + ")\n"

    ages = []
    if age_adult:
        ages.append(ADULT)
    if age_master1:
        ages.append(MASTER_1)
    if age_master2:
        ages.append(MASTER_2)
    if age_master3:
        ages.append(MASTER_3)
    if age_master4:
        ages.append(MASTER_4)
    if age_master5:
        ages.append(MASTER_5)
    if age_master6:
        ages.append(MASTER_6)
    if age_master7:
        ages.append(MASTER_7)
    if age_juvenile:
        ages.extend(JUVENILE_AGES)
    if age_teen:
        ages.append(TEEN_1)
        ages.append(TEEN_2)
        ages.append(TEEN_3)
    if len(ages):
        filters += "AND d.age IN (" + ", ".join(f"'{a}'" for a in ages) + ")\n"

    belts = []
    if belt_grey:
        belts.append(GREY)
        belts.append(YELLOW_GREY)
    if belt_yellow:
        belts.append(YELLOW)
        belts.append(YELLOW_GREY)
    if belt_orange:
        belts.append(ORANGE)
        belts.append(GREEN_ORANGE)
    if belt_green:
        belts.append(GREEN)
        belts.append(GREEN_ORANGE)
    if belt_white:
        belts.append(WHITE)
    if belt_blue:
        belts.append(BLUE)
    if belt_purple:
        belts.append(PURPLE)
    if belt_brown:
        belts.append(BROWN)
    if belt_black:
        belts.append(BLACK)
    if len(belts):
        filters += "AND d.belt IN (" + ", ".join(f"'{b}'" for b in belts) + ")\n"

    weights = []
    if weight_rooster:
        weights.append(ROOSTER)
    if weight_light_feather:
        weights.append(LIGHT_FEATHER)
    if weight_feather:
        weights.append(FEATHER)
    if weight_light:
        weights.append(LIGHT)
    if weight_middle:
        weights.append(MIDDLE)
    if weight_medium_heavy:
        weights.append(MEDIUM_HEAVY)
    if weight_heavy:
        weights.append(HEAVY)
    if weight_super_heavy:
        weights.append(SUPER_HEAVY)
    if weight_ultra_heavy:
        weights.append(ULTRA_HEAVY)
    if weight_open_class:
        weights.append(OPEN_CLASS)
        weights.append(OPEN_CLASS_LIGHT)
        weights.append(OPEN_CLASS_HEAVY)
    if len(weights):
        filters += "AND d.weight IN (" + ", ".join(f"'{w}'" for w in weights) + ")\n"

    if date_start:
        filters += "AND m.happened_at >= :date_start\n"
        params["date_start"] = datetime.fromisoformat(date_start)
    if date_end:
        filters += "AND m.happened_at <= :date_end\n"
        params["date_end"] = datetime.fromisoformat(date_end)
    if mat_number is not None:
        filters += """AND m.match_location IS NOT NULL AND m.match_location LIKE :mat_number
        """
        params["mat_number"] = f"% {mat_number}"
    if dq_type_technical or dq_type_disciplinary:
        dq_notes = []
        if dq_type_technical:
            dq_notes.extend(DQ_TYPE_NOTES["technical"])
        if dq_type_disciplinary:
            dq_notes.extend(DQ_TYPE_NOTES["disciplinary"])
        dq_note_params = {
            f"dq_note_{index}": f"%{note}%" for index, note in enumerate(dq_notes)
        }
        dq_note_clause = " OR ".join(f"mp.note LIKE :{key}" for key in dq_note_params)
        filters += f"""AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id
            AND ({dq_note_clause})
        )
        """
        params.update(dq_note_params)

    if has_score:
        filters += """AND (
            m.final_top_points IS NOT NULL
            OR m.final_top_advantages IS NOT NULL
            OR m.final_top_penalties IS NOT NULL
            OR m.final_bottom_points IS NOT NULL
            OR m.final_bottom_advantages IS NOT NULL
            OR m.final_bottom_penalties IS NOT NULL
        )
        """

    if submission:
        filters += """AND m.final_match_time_seconds > 0
        AND NOT EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id
            AND (
                LOWER(mp.note) LIKE '%disqualified%'
                OR LOWER(mp.note) LIKE '%desqualificado%'
            )
        )
        """

    if comeback_submission:
        filters += """AND m.final_match_time_seconds > 0
        AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id
            AND mp.winner IS TRUE
            AND (
                (
                    mp.scoreboard_position = 'top'
                    AND m.final_top_points < m.final_bottom_points
                )
                OR (
                    mp.scoreboard_position = 'bottom'
                    AND m.final_bottom_points < m.final_top_points
                )
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id
            AND (
                LOWER(mp.note) LIKE '%disqualified%'
                OR LOWER(mp.note) LIKE '%desqualificado%'
            )
        )
        """

    if minimum_points is not None:
        filters += """AND (
            m.final_top_points >= :minimum_points
            OR m.final_bottom_points >= :minimum_points
        )
        """
        params["minimum_points"] = minimum_points

    if minimum_advantages is not None:
        filters += """AND (
            m.final_top_advantages >= :minimum_advantages
            OR m.final_bottom_advantages >= :minimum_advantages
        )
        """
        params["minimum_advantages"] = minimum_advantages

    if minimum_penalties is not None:
        filters += """AND (
            m.final_top_penalties >= :minimum_penalties
            OR m.final_bottom_penalties >= :minimum_penalties
        )
        """
        params["minimum_penalties"] = minimum_penalties

    if score_differential is not None:
        filters += """AND ABS(
            m.final_top_points - m.final_bottom_points
        ) >= :score_differential
        """
        params["score_differential"] = score_differential

    if referee_decision:
        filters += """AND m.final_match_time_seconds = 0
        AND m.final_top_points = m.final_bottom_points
        AND m.final_top_advantages = m.final_bottom_advantages
        AND m.final_top_penalties = m.final_bottom_penalties
        AND NOT EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id
            AND (
                LOWER(mp.note) LIKE '%disqualified%'
                OR LOWER(mp.note) LIKE '%desqualificado%'
            )
        )
        """

    if rating_start is not None:
        rating_start_int = int(rating_start)
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating >= :rating_start OR mp.end_rating >= :rating_start)
        )
        """
        params["rating_start"] = rating_start_int
    if rating_end is not None:
        rating_end_int = int(rating_end)
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating <= :rating_end OR mp.end_rating <= :rating_end)
        )
        """
        params["rating_end"] = rating_end_int

    sql = f"""
        SELECT m.id, m.happened_at, d.gi, d.gender, d.age, d.belt, d.weight, e.name as event_name, e.ibjjf_id,
            mp.id as participant_id, mp.winner, mp.start_rating, mp.end_rating,
            a.id as athlete_id, a.name, a.slug, a.country, a.country_note, a.country_note_pt, a.instagram_profile, a.personal_name, a.profile_image_saved_at, a.hide_full_name,
            mp.note, m.rated, mp.rating_note, mp.weight_for_open, mp.start_match_count, mp.end_match_count, m.match_location, m.video_link,
            mp.scoreboard_position,
            m.match_number, m.division_size, m.video_start_offset_seconds,
            m.final_match_time_seconds, m.final_top_points, m.final_top_advantages,
            m.final_top_penalties, m.final_bottom_points, m.final_bottom_advantages,
            m.final_bottom_penalties
        FROM matches m
        JOIN divisions d ON m.division_id = d.id
        JOIN events e ON m.event_id = e.id
        JOIN match_participants mp ON m.id = mp.match_id
        JOIN athletes a ON mp.athlete_id = a.id
        WHERE d.gi = :gi
        {filters}
    """

    page_size = MATCH_PAGE_SIZE
    if athlete_name and athlete_name2 and athlete_name != athlete_name2:
        page_size = ATHLETES_MATCH_PAGE_SIZE

    # get one extra match to determine if there are more pages
    params["limit"] = (page_size + 1) * 2
    params["offset"] = (page - 1) * page_size * 2

    results = db.session.execute(
        text(
            f"""
        {sql}
        ORDER BY m.happened_at DESC, m.id DESC
        LIMIT :limit OFFSET :offset
        """
        ),
        params,
    )

    s3_client = get_s3_client()

    event_ids = set()
    response = []
    current_match = None
    for result in results:
        row = result._mapping

        if current_match is None or current_match.id != row["id"]:
            division = Division(
                gi=row["gi"],
                gender=row["gender"],
                age=row["age"],
                belt=row["belt"],
                weight=row["weight"],
            )
            event = Event(name=row["event_name"], ibjjf_id=row["ibjjf_id"])

            # sqlite returns a string for datetime fields, but postgres returns a datetime object
            if isinstance(row["happened_at"], str):
                happened_at = datetime.fromisoformat(row["happened_at"])
            else:
                happened_at = row["happened_at"]

            current_match = Match(
                id=row["id"],
                happened_at=happened_at,
                division=division,
                event=event,
                rated=row["rated"],
                match_location=row["match_location"],
                video_link=row["video_link"],
                match_number=row["match_number"],
                division_size=row["division_size"],
                video_start_offset_seconds=row["video_start_offset_seconds"],
                final_match_time_seconds=row["final_match_time_seconds"],
                final_top_points=row["final_top_points"],
                final_top_advantages=row["final_top_advantages"],
                final_top_penalties=row["final_top_penalties"],
                final_bottom_points=row["final_bottom_points"],
                final_bottom_advantages=row["final_bottom_advantages"],
                final_bottom_penalties=row["final_bottom_penalties"],
            )

        current_match.participants.append(
            MatchParticipant(
                id=row["participant_id"],
                winner=row["winner"],
                start_rating=row["start_rating"],
                end_rating=row["end_rating"],
                athlete=Athlete(
                    id=row["athlete_id"],
                    name=row["name"],
                    slug=row["slug"],
                    country=row["country"],
                    country_note=row["country_note"],
                    country_note_pt=row["country_note_pt"],
                    instagram_profile=row["instagram_profile"],
                    personal_name=row["personal_name"],
                    profile_image_saved_at=row["profile_image_saved_at"],
                    hide_full_name=row["hide_full_name"],
                ),
                note=row["note"],
                weight_for_open=row["weight_for_open"],
                rating_note=row["rating_note"],
                start_match_count=row["start_match_count"],
                end_match_count=row["end_match_count"],
                scoreboard_position=row["scoreboard_position"],
            )
        )

        if len(current_match.participants) == 2:
            winner = None
            loser = None
            for participant in current_match.participants:
                if participant.winner:
                    winner = participant
                else:
                    loser = participant

            if winner is None or loser is None:
                winner = current_match.participants[0]
                loser = current_match.participants[1]

            event_ids.add(current_match.event.ibjjf_id)

            response.append(
                {
                    "id": current_match.id,
                    "videoLink": current_match.video_link,
                    "winner": (
                        winner.athlete.name
                        if not winner.athlete.hide_full_name
                        else winner.athlete.personal_name
                    ),
                    "winnerSlug": winner.athlete.slug,
                    "winnerId": winner.athlete.id,
                    "winnerStartRating": round(winner.start_rating),
                    "winnerEndRating": round(winner.end_rating),
                    "winnerWeightForOpen": winner.weight_for_open,
                    "winnerStartMatchCount": winner.start_match_count,
                    "winnerEndMatchCount": winner.end_match_count,
                    "winnerCountry": winner.athlete.country,
                    "winnerCountryNote": winner.athlete.country_note,
                    "winnerCountryNotePt": winner.athlete.country_note_pt,
                    "winnerInstagramProfile": winner.athlete.instagram_profile,
                    "winnerPersonalName": winner.athlete.personal_name,
                    "winnerProfileImageUrl": (
                        get_public_photo_url(s3_client, winner.athlete)
                        if winner.athlete.profile_image_saved_at
                        else None
                    ),
                    "loser": (
                        loser.athlete.name
                        if not loser.athlete.hide_full_name
                        else loser.athlete.personal_name
                    ),
                    "loserSlug": loser.athlete.slug,
                    "loserId": loser.athlete.id,
                    "loserStartRating": round(loser.start_rating),
                    "loserEndRating": round(loser.end_rating),
                    "loserWeightForOpen": loser.weight_for_open,
                    "loserStartMatchCount": loser.start_match_count,
                    "loserEndMatchCount": loser.end_match_count,
                    "loserCountry": loser.athlete.country,
                    "loserCountryNote": loser.athlete.country_note,
                    "loserCountryNotePt": loser.athlete.country_note_pt,
                    "loserInstagramProfile": loser.athlete.instagram_profile,
                    "loserPersonalName": loser.athlete.personal_name,
                    "loserProfileImageUrl": (
                        get_public_photo_url(s3_client, loser.athlete)
                        if loser.athlete.profile_image_saved_at
                        else None
                    ),
                    "event": current_match.event.name,
                    "age": current_match.division.age,
                    "gender": current_match.division.gender,
                    "belt": current_match.division.belt,
                    "weight": current_match.division.weight,
                    "date": current_match.happened_at.isoformat(),
                    "rated": current_match.rated,
                    "notes": loser.note or winner.note,
                    "winnerRatingNote": winner.rating_note,
                    "loserRatingNote": loser.rating_note,
                    "winnerScoreboardPosition": winner.scoreboard_position,
                    "loserScoreboardPosition": loser.scoreboard_position,
                    "matchLocation": current_match.match_location,
                    "finalTopPoints": current_match.final_top_points,
                    "finalTopAdvantages": current_match.final_top_advantages,
                    "finalTopPenalties": current_match.final_top_penalties,
                    "finalBottomPoints": current_match.final_bottom_points,
                    "finalBottomAdvantages": current_match.final_bottom_advantages,
                    "finalBottomPenalties": current_match.final_bottom_penalties,
                    "submission": (
                        None
                        if current_match.final_match_time_seconds is None
                        else current_match.final_match_time_seconds > 0
                    ),
                    "event_ibjjf_id": current_match.event.ibjjf_id,
                    "date_happened_at": current_match.happened_at,
                    "match_number": current_match.match_number,
                    "division_size": current_match.division_size,
                    "video_start_offset_seconds": (
                        current_match.video_start_offset_seconds
                    ),
                }
            )

    totalPages = page + 1
    if len(response) <= page_size:
        totalPages -= 1

    if len(response) > page_size:
        response = response[:page_size]

    # Fill query results with livestream links
    livestream_data = {}

    if len(event_ids):
        livestream_data = load_livestream_links(db.session, event_ids)

    linked_archive_urls = load_linked_archive_video_links(
        db.session, (match["id"] for match in response)
    )

    for match in response:
        resolved_link = get_livestream_link(
            livestream_data,
            match["event_ibjjf_id"],
            match["winner"],
            match["loser"],
            match["date_happened_at"],
            match["matchLocation"],
            match["belt"],
            match["age"],
            match["division_size"],
            match["match_number"],
            match["winnerPersonalName"],
            match["loserPersonalName"],
            match["videoLink"],
            match["video_start_offset_seconds"],
        )
        if not (
            isinstance(match["videoLink"], str) and match["videoLink"].lower() == "none"
        ):
            resolved_link = linked_archive_urls.get(
                uuid.UUID(str(match["id"])), resolved_link
            )
        match["videoLink"] = resolved_link

        del match["event_ibjjf_id"]
        del match["date_happened_at"]
        del match["match_number"]
        del match["division_size"]
        del match["video_start_offset_seconds"]

    return jsonify({"rows": response, "totalPages": totalPages})
