from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from rapidfuzz import fuzz
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from livestream_frame_archive import archive_usage_rows, discover_livestream_usages
from youtube_utils import extract_youtube_video_id
from livestream_frame_text_scan import (
    SCOREBOARD_STATE_BLANK,
    SCOREBOARD_STATE_VISIBLE,
    SCORE_FIELDS,
    TextState,
    apply_event_to_state,
)
from models import (
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    Match,
    MatchParticipant,
    RegistrationLink,
)


NO_FIGHT_NOTE_PARTS = (
    "no show",
    "overweight",
    "acima do peso",
)
MIN_NAME_SCORE = 78.0
MIN_SEQUENTIAL_NAME_SCORE = 75.0
MIN_SCORE_MARGIN = 8.0
MIN_NON_CURSOR_SIDE_NAME_SCORE = 60.0
MIN_RESET_NAME_CONFIDENCE = 0.9
MIN_CONTINUATION_NAME_SCORE = 82.0
STALE_PRESTART_NAME_GAP_SECONDS = 3 * 60
MIN_CONFLICTING_POSTSTART_PAIRS = 2
LOOKAHEAD_MATCHES = 8
TIME_MATCH_WINDOW_SECONDS = 20 * 60
CONTINUATION_TIME_WINDOW_SECONDS = 3 * 60
SEQUENTIAL_TIME_WINDOW_SECONDS = 3 * 60
SPECULATIVE_FORWARD_RELEASE_GAP = 2
STARTING_TIMER_RESET_SECONDS = 4 * 60


@dataclass
class TimelinePoint:
    event: LivestreamFrameTextEvent
    state: TextState


@dataclass
class MatchWindow:
    start_second: int
    end_second: int
    video_start_offset_seconds: int | None
    events: list[LivestreamFrameTextEvent]
    top_names: list[str]
    bottom_names: list[str]
    position_name_pairs: list[tuple[str | None, str | None]]
    final_state: TextState
    final_timer_seconds: int | None
    has_running_timer: bool


@dataclass
class Candidate:
    match: Match
    participants: tuple[MatchParticipant, MatchParticipant]
    stream: LiveStream
    order_index: int
    expected_start_second: int | None = None


@dataclass
class MatchChoice:
    candidate: Candidate
    score: float
    top_participant: MatchParticipant
    bottom_participant: MatchParticipant
    raw_score: float = 0.0
    time_delta_seconds: int | None = None


def parse_timer_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})", value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _looks_like_starting_timer_seconds(seconds: int | None) -> bool:
    return (
        seconds is not None
        and seconds >= STARTING_TIMER_RESET_SECONDS
        and seconds % 60 == 0
    )


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9 ]+", " ", value.upper()).strip()


def _has_full_zero_score(state: TextState) -> bool:
    return all(getattr(state, field) == 0 for field in SCORE_FIELDS)


def _event_has_full_zero_score(event: LivestreamFrameTextEvent) -> bool:
    return all(getattr(event, field) == 0 for field in SCORE_FIELDS)


def _has_non_zero_score(state: TextState) -> bool:
    return any((getattr(state, field) or 0) != 0 for field in SCORE_FIELDS)


def _has_any_name(state: TextState) -> bool:
    return bool(state.top_athlete_name or state.bottom_athlete_name)


def _event_has_any_name(event: LivestreamFrameTextEvent) -> bool:
    return bool(event.top_athlete_name or event.bottom_athlete_name)


def _is_start_point(point: TimelinePoint) -> bool:
    state = point.state
    if (
        state.scoreboard_state != SCOREBOARD_STATE_VISIBLE
        or not _has_full_zero_score(state)
        or not _has_any_name(state)
        or state.top_athlete_name == "Victory"
    ):
        return False
    if state.timer_state != "running":
        return True
    timer_seconds = parse_timer_seconds(state.timer_value)
    return timer_seconds is not None and _looks_like_starting_timer_seconds(
        timer_seconds
    )


def _running_timer_start_second(points: list[TimelinePoint]) -> int | None:
    for point in points:
        if (
            point.event.timer_state == "running"
            and parse_timer_seconds(point.event.timer_value) is not None
        ):
            return point.event.frame_second
    return None


def _names_are_similar(first: str | None, second: str | None) -> bool:
    first_norm = _norm(first)
    second_norm = _norm(second)
    if not first_norm or not second_norm:
        return first_norm == second_norm
    return fuzz.ratio(first_norm, second_norm) >= 85


def _same_start_names(first: TextState, second: TextState) -> bool:
    return _names_are_similar(
        first.top_athlete_name, second.top_athlete_name
    ) and _names_are_similar(first.bottom_athlete_name, second.bottom_athlete_name)


def _names_are_continuation_match(first: str | None, second: str | None) -> bool:
    first_norm = _norm(first)
    second_norm = _norm(second)
    if not first_norm or not second_norm:
        return False
    return (
        fuzz.ratio(first_norm, second_norm) >= MIN_CONTINUATION_NAME_SCORE
        or fuzz.partial_ratio(first_norm, second_norm) >= MIN_CONTINUATION_NAME_SCORE
    )


def _name_matches_any_continuation(value: str | None, choices: list[str]) -> bool:
    return any(_names_are_continuation_match(value, choice) for choice in choices)


def _has_terminal_boundary(points: list[TimelinePoint]) -> bool:
    return any(
        point.state.scoreboard_state == SCOREBOARD_STATE_BLANK
        or point.event.top_athlete_name == "Victory"
        for point in points
    )


def _continuation_start_matches_active_window(
    timeline: list[TimelinePoint], start_index: int, candidate_index: int
) -> bool:
    points = timeline[start_index:candidate_index]
    if not points or _has_terminal_boundary(points):
        return False

    candidate_state = timeline[candidate_index].state
    if not candidate_state.top_athlete_name or not candidate_state.bottom_athlete_name:
        return False

    top_names = [
        point.state.top_athlete_name
        for point in points
        if point.state.top_athlete_name and point.state.top_athlete_name != "Victory"
    ]
    bottom_names = [
        point.state.bottom_athlete_name
        for point in points
        if point.state.bottom_athlete_name
    ]
    return _name_matches_any_continuation(
        candidate_state.top_athlete_name, top_names
    ) and _name_matches_any_continuation(
        candidate_state.bottom_athlete_name, bottom_names
    )


def _running_timer_starts_prestart_window(
    timeline: list[TimelinePoint], start_index: int, candidate_index: int
) -> bool:
    points = timeline[start_index:candidate_index]
    if not points or _has_terminal_boundary(points):
        return False
    if any(_has_non_zero_score(point.state) for point in points):
        return False

    start_timer = parse_timer_seconds(points[0].state.timer_value)
    candidate = timeline[candidate_index]
    candidate_timer = parse_timer_seconds(candidate.state.timer_value)
    if start_timer is None or candidate_timer is None:
        return False
    if candidate_timer == 0 or candidate_timer != start_timer:
        return False

    saw_running_timer = any(point.state.timer_state == "running" for point in points)
    return candidate.state.timer_state == "running" and not saw_running_timer


def _event_confidently_matches_names(
    event: LivestreamFrameTextEvent, state: TextState
) -> bool:
    if event.confidence is None or event.confidence < MIN_RESET_NAME_CONFIDENCE:
        return False
    if not event.top_athlete_name or not event.bottom_athlete_name:
        return False
    return _names_are_similar(
        event.top_athlete_name, state.top_athlete_name
    ) and _names_are_similar(event.bottom_athlete_name, state.bottom_athlete_name)


def _score_state_from_window(points: list[TimelinePoint]) -> TextState:
    score_state = TextState()
    ignore_zero_reset = False
    for point in points:
        if point.state.scoreboard_state == SCOREBOARD_STATE_BLANK:
            ignore_zero_reset = _has_non_zero_score(score_state)
            continue
        if any(getattr(point.state, field) is not None for field in SCORE_FIELDS):
            if (
                ignore_zero_reset
                and _has_full_zero_score(point.state)
                and not _event_has_any_name(point.event)
            ):
                continue
            for field in SCORE_FIELDS:
                setattr(score_state, field, getattr(point.state, field))
            score_state.scoreboard_state = point.state.scoreboard_state
            ignore_zero_reset = False
    return score_state


def _position_name_pairs_from_window(
    points: list[TimelinePoint],
) -> list[tuple[str | None, str | None]]:
    pairs = []
    timer_started = False
    for point in points:
        if not timer_started:
            timer_started = (
                point.event.timer_state == "running"
                and parse_timer_seconds(point.event.timer_value) is not None
            )
            if not timer_started:
                continue
        if not _event_has_any_name(point.event):
            continue

        top_name = point.state.top_athlete_name
        if top_name == "Victory":
            top_name = None
        pair = (top_name, point.state.bottom_athlete_name)
        if pair != (None, None):
            pairs.append(pair)
    return pairs


def _is_stopped_zero_score(point: TimelinePoint) -> bool:
    return (
        point.event.timer_state == "stopped"
        and _event_has_full_zero_score(point.event)
        and _has_full_zero_score(point.state)
    )


def _trim_scoreboard_reset(points: list[TimelinePoint]) -> list[TimelinePoint]:
    if not points:
        return points
    start_state = points[0].state
    saw_non_zero_score = False
    for index, point in enumerate(points):
        if saw_non_zero_score and _is_stopped_zero_score(point):
            if _event_confidently_matches_names(point.event, start_state):
                continue
            return points[:index]
        if _has_non_zero_score(point.state):
            saw_non_zero_score = True
    return points


def _final_timer_seconds_from_window(points: list[TimelinePoint]) -> int | None:
    final_timer_seconds = None
    timer_values = [
        timer_seconds
        for point in points
        if (timer_seconds := parse_timer_seconds(point.state.timer_value)) is not None
    ]
    min_timer_seconds = min(timer_values) if timer_values else None

    for point in points:
        if point.event.timer_state == "running":
            final_timer_seconds = None
            continue
        if point.event.timer_state != "stopped":
            continue

        timer_seconds = parse_timer_seconds(point.event.timer_value)
        if timer_seconds is None or (
            min_timer_seconds is not None
            and timer_seconds > min_timer_seconds
            and _looks_like_starting_timer_seconds(timer_seconds)
        ):
            continue
        final_timer_seconds = timer_seconds

    return final_timer_seconds


def extract_match_windows(events: list[LivestreamFrameTextEvent]) -> list[MatchWindow]:
    state = TextState()
    timeline = []
    for event in sorted(events, key=lambda item: item.frame_second):
        state = apply_event_to_state(state, event)
        timeline.append(TimelinePoint(event=event, state=state.copy()))

    starts = []
    for index, point in enumerate(timeline):
        if not _is_start_point(point):
            continue
        if starts and _continuation_start_matches_active_window(
            timeline, starts[-1], index
        ):
            continue
        if starts and _running_timer_starts_prestart_window(
            timeline, starts[-1], index
        ):
            continue
        if (
            starts
            and not _has_terminal_boundary(timeline[starts[-1] : index])
            and _same_start_names(timeline[starts[-1]].state, point.state)
        ):
            continue
        starts.append(index)
    windows = []
    for start_position, start_index in enumerate(starts):
        next_start_index = (
            starts[start_position + 1]
            if start_position + 1 < len(starts)
            else len(timeline)
        )
        points = _trim_scoreboard_reset(timeline[start_index:next_start_index])
        if not points:
            continue

        names_top = []
        names_bottom = []
        for point in points:
            if (
                point.state.top_athlete_name
                and point.state.top_athlete_name != "Victory"
            ):
                names_top.append(point.state.top_athlete_name)
            if point.state.bottom_athlete_name:
                names_bottom.append(point.state.bottom_athlete_name)

        final_state = _score_state_from_window(points)
        running_timer_start_second = _running_timer_start_second(points)
        final_timer_seconds = _final_timer_seconds_from_window(points)
        windows.append(
            MatchWindow(
                start_second=points[0].event.frame_second,
                end_second=points[-1].event.frame_second,
                video_start_offset_seconds=running_timer_start_second,
                events=[point.event for point in points],
                top_names=_dedupe(names_top),
                bottom_names=_dedupe(names_bottom),
                position_name_pairs=_position_name_pairs_from_window(points),
                final_state=final_state,
                final_timer_seconds=final_timer_seconds,
                has_running_timer=running_timer_start_second is not None,
            )
        )
    return windows


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = _norm(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _best_name_score(ocr_names: list[str], athlete_name: str) -> float:
    normalized_athlete = _norm(athlete_name)
    if not ocr_names or not normalized_athlete:
        return 0.0
    scores = [
        fuzz.partial_ratio(_norm(ocr_name), normalized_athlete)
        for ocr_name in ocr_names
        if _norm(ocr_name)
    ]
    return max(scores, default=0.0)


def _orientation_score(
    window: MatchWindow,
    top_participant: MatchParticipant,
    bottom_participant: MatchParticipant,
) -> float:
    top_score, bottom_score = _oriented_name_scores(
        window, top_participant, bottom_participant
    )
    if window.top_names and window.bottom_names:
        return top_score * 0.7 + bottom_score * 0.3
    if window.top_names:
        return top_score
    if window.bottom_names:
        return bottom_score * 0.85
    return 0.0


def _oriented_name_scores(
    window: MatchWindow,
    top_participant: MatchParticipant,
    bottom_participant: MatchParticipant,
) -> tuple[float, float]:
    return (
        _best_name_score(window.top_names, top_participant.athlete.name),
        _best_name_score(window.bottom_names, bottom_participant.athlete.name),
    )


def _locked_participant_orientation(
    window: MatchWindow,
    first: MatchParticipant,
    second: MatchParticipant,
) -> tuple[MatchParticipant, MatchParticipant] | None:
    for top_name, bottom_name in window.position_name_pairs:
        if not top_name or not bottom_name:
            continue

        first_top_scores = (
            _best_name_score([top_name], first.athlete.name),
            _best_name_score([bottom_name], second.athlete.name),
        )
        second_top_scores = (
            _best_name_score([top_name], second.athlete.name),
            _best_name_score([bottom_name], first.athlete.name),
        )
        first_top_score = first_top_scores[0] * 0.7 + first_top_scores[1] * 0.3
        second_top_score = second_top_scores[0] * 0.7 + second_top_scores[1] * 0.3

        best_side_score = max(min(first_top_scores), min(second_top_scores))
        if best_side_score < MIN_NON_CURSOR_SIDE_NAME_SCORE:
            continue
        if abs(first_top_score - second_top_score) < MIN_SCORE_MARGIN:
            continue
        if first_top_score > second_top_score:
            return first, second
        return second, first
    return None


def _choice_for_candidate(window: MatchWindow, candidate: Candidate) -> MatchChoice:
    first, second = candidate.participants
    first_top_score = _orientation_score(window, first, second)
    second_top_score = _orientation_score(window, second, first)
    raw_score = max(first_top_score, second_top_score)
    orientation = _locked_participant_orientation(window, first, second)
    if orientation is None:
        orientation = (
            (first, second) if first_top_score >= second_top_score else (second, first)
        )
    return MatchChoice(candidate, raw_score, *orientation, raw_score)


def _has_two_sided_name_evidence(window: MatchWindow, choice: MatchChoice) -> bool:
    if not window.top_names or not window.bottom_names:
        return False
    top_score, bottom_score = _oriented_name_scores(
        window, choice.top_participant, choice.bottom_participant
    )
    return (
        top_score >= MIN_NON_CURSOR_SIDE_NAME_SCORE
        and bottom_score >= MIN_NON_CURSOR_SIDE_NAME_SCORE
    )


def _has_non_cursor_name_evidence(
    window: MatchWindow, choice: MatchChoice, cursor: int
) -> bool:
    if choice.candidate.order_index == cursor:
        return True
    return _has_two_sided_name_evidence(window, choice)


def _has_confirmed_sequential_predecessor(
    choice: MatchChoice,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set,
    speculative_match_ids: set,
) -> bool:
    if cursor <= 0 or choice.candidate.order_index != cursor:
        return False
    predecessor = next(
        (candidate for candidate in candidates if candidate.order_index == cursor - 1),
        None,
    )
    if predecessor is None:
        return False
    predecessor_id = predecessor.match.id
    return (
        predecessor_id in used_match_ids and predecessor_id not in speculative_match_ids
    )


def _is_confident_sequential_choice(
    window: MatchWindow,
    choice: MatchChoice,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set,
    speculative_match_ids: set,
) -> bool:
    time_delta = choice.time_delta_seconds
    return (
        choice.raw_score >= MIN_SEQUENTIAL_NAME_SCORE
        and time_delta is not None
        and abs(time_delta) <= SEQUENTIAL_TIME_WINDOW_SECONDS
        and _has_two_sided_name_evidence(window, choice)
        and _has_confirmed_sequential_predecessor(
            choice,
            candidates,
            cursor,
            used_match_ids,
            speculative_match_ids,
        )
    )


def _candidate_time_delta(window: MatchWindow, candidate: Candidate) -> int | None:
    if (
        candidate.expected_start_second is None
        or window.video_start_offset_seconds is None
    ):
        return None
    return window.video_start_offset_seconds - candidate.expected_start_second


def _candidate_choices(
    window: MatchWindow,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set | None = None,
    allow_stale_cursor_recovery: bool = False,
) -> list[MatchChoice]:
    used_match_ids = used_match_ids or set()
    choices = []
    for candidate in candidates:
        if candidate.match.id in used_match_ids:
            continue
        gap = candidate.order_index - cursor
        time_delta = _candidate_time_delta(window, candidate)
        time_aligned = (
            time_delta is not None and abs(time_delta) <= TIME_MATCH_WINDOW_SECONDS
        )
        if candidate.order_index < cursor and not time_aligned:
            continue
        choice = _choice_for_candidate(window, candidate)
        if gap > LOOKAHEAD_MATCHES and not time_aligned:
            if not allow_stale_cursor_recovery:
                continue
            if _best_poststart_two_sided_support_score(window, choice) < MIN_NAME_SCORE:
                continue
        if time_aligned:
            order_penalty = 0.0
            time_penalty = min(abs(time_delta) / 60.0 * 0.4, 12.0)
        else:
            order_penalty = min(gap * 3.0, 18.0)
            time_penalty = 0.0
        choices.append(
            MatchChoice(
                candidate=choice.candidate,
                score=choice.raw_score - order_penalty - time_penalty,
                top_participant=choice.top_participant,
                bottom_participant=choice.bottom_participant,
                raw_score=choice.raw_score,
                time_delta_seconds=time_delta,
            )
        )
    choices.sort(key=lambda item: item.score, reverse=True)
    return choices


def _prestart_lead_seconds(window: MatchWindow) -> int | None:
    if not window.events or window.video_start_offset_seconds is None:
        return None
    first_event = window.events[0]
    if (
        first_event.timer_state == "running"
        and parse_timer_seconds(first_event.timer_value) is not None
    ):
        return None
    return window.video_start_offset_seconds - window.start_second


def _observed_pair_candidate_scores(
    pair: tuple[str | None, str | None],
    choice: MatchChoice,
) -> tuple[tuple[float, float], tuple[float, float]]:
    top_name, bottom_name = pair
    return (
        (
            _best_name_score(
                [top_name] if top_name else [],
                choice.top_participant.athlete.name,
            ),
            _best_name_score(
                [bottom_name] if bottom_name else [],
                choice.bottom_participant.athlete.name,
            ),
        ),
        (
            _best_name_score(
                [top_name] if top_name else [],
                choice.bottom_participant.athlete.name,
            ),
            _best_name_score(
                [bottom_name] if bottom_name else [],
                choice.top_participant.athlete.name,
            ),
        ),
    )


def _observed_pair_two_sided_support_score(
    pair: tuple[str | None, str | None],
    choice: MatchChoice,
) -> float:
    return max(
        min(side_scores)
        for side_scores in _observed_pair_candidate_scores(pair, choice)
    )


def _observed_pair_supports_candidate(
    pair: tuple[str | None, str | None],
    choice: MatchChoice,
) -> bool:
    return (
        _observed_pair_two_sided_support_score(pair, choice)
        >= MIN_NON_CURSOR_SIDE_NAME_SCORE
    )


def _observed_pairs_describe_same_pair(
    first: tuple[str | None, str | None],
    second: tuple[str | None, str | None],
) -> bool:
    first_top, first_bottom = first
    second_top, second_bottom = second
    return (
        _names_are_continuation_match(first_top, second_top)
        and _names_are_continuation_match(first_bottom, second_bottom)
    ) or (
        _names_are_continuation_match(first_top, second_bottom)
        and _names_are_continuation_match(first_bottom, second_top)
    )


def _complete_poststart_name_pairs(
    window: MatchWindow,
) -> list[tuple[str, str]]:
    return [
        (top_name, bottom_name)
        for top_name, bottom_name in window.position_name_pairs
        if top_name and bottom_name
    ]


def _best_poststart_two_sided_support_score(
    window: MatchWindow,
    choice: MatchChoice,
) -> float:
    return max(
        (
            _observed_pair_two_sided_support_score(pair, choice)
            for pair in _complete_poststart_name_pairs(window)
        ),
        default=0.0,
    )


def _coherent_conflicting_poststart_pair_count(
    window: MatchWindow,
    choice: MatchChoice,
) -> int:
    conflicting_pairs = [
        pair
        for pair in _complete_poststart_name_pairs(window)
        if not _observed_pair_supports_candidate(pair, choice)
    ]
    return max(
        (
            sum(
                _observed_pairs_describe_same_pair(reference, pair)
                for pair in conflicting_pairs
            )
            for reference in conflicting_pairs
        ),
        default=0,
    )


def _has_stale_conflicting_prestart_evidence(
    window: MatchWindow,
    choice: MatchChoice,
) -> bool:
    prestart_lead_seconds = _prestart_lead_seconds(window)
    return (
        prestart_lead_seconds is not None
        and prestart_lead_seconds >= STALE_PRESTART_NAME_GAP_SECONDS
        and choice.score >= MIN_NAME_SCORE
        and _best_poststart_two_sided_support_score(window, choice)
        < MIN_NON_CURSOR_SIDE_NAME_SCORE
        and _coherent_conflicting_poststart_pair_count(window, choice)
        >= MIN_CONFLICTING_POSTSTART_PAIRS
    )


def choose_match_for_window(
    window: MatchWindow,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set | None = None,
    speculative_match_ids: set | None = None,
    allow_stale_cursor_recovery: bool = False,
) -> MatchChoice | None:
    if not window.has_running_timer:
        return None
    used_match_ids = used_match_ids or set()
    speculative_match_ids = speculative_match_ids or set()
    choices = _candidate_choices(
        window,
        candidates,
        cursor,
        used_match_ids,
        allow_stale_cursor_recovery=allow_stale_cursor_recovery,
    )
    if not choices:
        return None
    choices = [
        choice
        for choice in choices
        if not _has_stale_conflicting_prestart_evidence(window, choice)
    ]
    if not choices:
        return None
    best = choices[0]
    second_score = choices[1].score if len(choices) > 1 else 0.0
    if best.score < MIN_NAME_SCORE and not _is_confident_sequential_choice(
        window,
        best,
        candidates,
        cursor,
        used_match_ids,
        speculative_match_ids,
    ):
        return None
    if second_score and best.score - second_score < MIN_SCORE_MARGIN:
        choice = _sequential_choice_for_ambiguous_window(window, choices, cursor)
        if choice and _has_non_cursor_name_evidence(window, choice, cursor):
            return choice
        return None
    if not _has_non_cursor_name_evidence(window, best, cursor):
        return None
    return best


def _rejected_stale_cursor_choice(
    window: MatchWindow, choices: list[MatchChoice], cursor: int
) -> bool:
    return bool(
        choices
        and choices[0].candidate.order_index == cursor
        and _has_stale_conflicting_prestart_evidence(window, choices[0])
    )


def choose_active_continuation_for_window(
    window: MatchWindow, candidate: Candidate | None
) -> MatchChoice | None:
    if candidate is None:
        return None
    if not window.top_names or not window.bottom_names:
        return None
    if not window.has_running_timer and window.final_timer_seconds is None:
        return None

    choice = _choice_for_candidate(window, candidate)
    if choice.raw_score < MIN_NAME_SCORE:
        return None

    time_delta = _candidate_time_delta(window, candidate)
    return MatchChoice(
        candidate=choice.candidate,
        score=choice.raw_score,
        top_participant=choice.top_participant,
        bottom_participant=choice.bottom_participant,
        raw_score=choice.raw_score,
        time_delta_seconds=time_delta,
    )


def _continuation_time_delta(window: MatchWindow, candidate: Candidate) -> int | None:
    if (
        window.video_start_offset_seconds is None
        or candidate.match.video_start_offset_seconds is None
    ):
        return None
    return (
        window.video_start_offset_seconds - candidate.match.video_start_offset_seconds
    )


def _continuation_is_time_aligned(window: MatchWindow, candidate: Candidate) -> bool:
    expected_delta = _candidate_time_delta(window, candidate)
    if expected_delta is not None and abs(expected_delta) <= TIME_MATCH_WINDOW_SECONDS:
        return True
    stored_delta = _continuation_time_delta(window, candidate)
    return (
        stored_delta is not None
        and 0 <= stored_delta <= CONTINUATION_TIME_WINDOW_SECONDS
    )


def choose_continuation_for_window(
    window: MatchWindow,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set | None = None,
    closed_match_ids: set | None = None,
) -> MatchChoice | None:
    terminal_zero_timer = window.final_timer_seconds == 0
    if not window.has_running_timer and not terminal_zero_timer:
        return None
    used_match_ids = used_match_ids or set()
    closed_match_ids = closed_match_ids or set()
    raw_choices = []
    for candidate in candidates:
        if candidate.match.id in closed_match_ids:
            continue
        choice = _choice_for_candidate(window, candidate)
        raw_choices.append(choice)
    raw_choices.sort(key=lambda item: item.raw_score, reverse=True)
    if not raw_choices:
        return None

    best = raw_choices[0]
    second_score = raw_choices[1].raw_score if len(raw_choices) > 1 else 0.0
    if best.candidate.match.id not in used_match_ids:
        return None
    if best.raw_score < MIN_NAME_SCORE:
        return None
    if second_score and best.raw_score - second_score < MIN_SCORE_MARGIN:
        return None
    if best.candidate.order_index != cursor - 1 and not _continuation_is_time_aligned(
        window, best.candidate
    ):
        return None

    time_delta = _candidate_time_delta(window, best.candidate)
    return MatchChoice(
        candidate=best.candidate,
        score=best.raw_score,
        top_participant=best.top_participant,
        bottom_participant=best.bottom_participant,
        raw_score=best.raw_score,
        time_delta_seconds=time_delta,
    )


def _sequential_choice_for_ambiguous_window(
    window: MatchWindow, choices: list[MatchChoice], cursor: int
) -> MatchChoice | None:
    if not window.top_names or not window.bottom_names:
        return None
    strong_choices = [
        choice
        for choice in choices
        if choice.score >= MIN_NAME_SCORE and choice.candidate.order_index >= cursor
    ]
    if not strong_choices:
        return None
    next_order = min(choice.candidate.order_index for choice in strong_choices)
    next_choices = [
        choice
        for choice in strong_choices
        if choice.candidate.order_index == next_order
    ]
    return max(next_choices, key=lambda choice: choice.score)


def _note_indicates_no_fight(participant: MatchParticipant) -> bool:
    note = (participant.note or "").lower()
    return any(part in note for part in NO_FIGHT_NOTE_PARTS)


def _match_mat_number(match_location: str | None) -> int | None:
    if not match_location:
        return None
    found = re.search(r"(\d+)\s*$", match_location)
    if not found:
        return None
    return int(found.group(1))


def _event_start_dates(event_ids: set[str]) -> dict[str, datetime]:
    if not event_ids:
        return {}
    rows = (
        Event.query.with_entities(Event.ibjjf_id, func.min(Match.happened_at))
        .join(Match, Match.event_id == Event.id)
        .filter(Event.ibjjf_id.in_(event_ids))
        .group_by(Event.ibjjf_id)
        .all()
    )
    event_start_dates = {
        ibjjf_id: min_happened_at
        for ibjjf_id, min_happened_at in rows
        if ibjjf_id and min_happened_at
    }
    missing_event_ids = event_ids - set(event_start_dates)
    if not missing_event_ids:
        return event_start_dates

    rows = RegistrationLink.query.filter(RegistrationLink.event_id.in_(event_ids)).all()
    event_start_dates.update(
        {
            row.event_id: row.event_start_date
            for row in rows
            if row.event_id in missing_event_ids and row.event_start_date
        }
    )
    return event_start_dates


def _match_day_number(
    match: Match, event_start_dates: dict[str, datetime]
) -> int | None:
    ibjjf_id = match.event.ibjjf_id if match.event else None
    event_start = event_start_dates.get(ibjjf_id)
    if not event_start:
        return None
    return (match.happened_at.date() - event_start.date()).days + 1


def _time_of_day_seconds(value: datetime) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def _stream_start_seconds(stream: LiveStream) -> int:
    return (
        (stream.start_hour or 0) * 3600
        + (stream.start_minute or 0) * 60
        + (stream.start_seconds or 0)
    )


def _stream_end_seconds(stream: LiveStream) -> int:
    return (stream.end_hour or 0) * 3600 + (stream.end_minute or 0) * 60


def _expected_video_offset_seconds(
    match: Match,
    stream: LiveStream,
    streams_for_archive: list[LiveStream],
) -> int | None:
    match_seconds = _time_of_day_seconds(match.happened_at)
    stream_start = _stream_start_seconds(stream)
    stream_end = _stream_end_seconds(stream)
    if stream_end and not (stream_start <= match_seconds < stream_end):
        return None

    related_streams = sorted(
        [
            item
            for item in streams_for_archive
            if item.event_id == stream.event_id
            and item.day_number == stream.day_number
            and item.mat_number == stream.mat_number
        ],
        key=lambda item: (
            item.start_hour or 0,
            item.start_minute or 0,
            item.start_seconds or 0,
        ),
    )
    start_for_offset = stream_start
    cut_seconds = 0
    start_set = False
    for index, related_stream in enumerate(related_streams):
        if related_stream.id != stream.id:
            continue
        for previous_index in range(index):
            previous_stream = related_streams[previous_index]
            next_stream = related_streams[previous_index + 1]
            if previous_stream.link != stream.link:
                continue
            cut_seconds += _stream_start_seconds(next_stream) - _stream_end_seconds(
                previous_stream
            )
            if not start_set:
                start_for_offset = _stream_start_seconds(previous_stream)
                start_set = True
        break

    offset = match_seconds - start_for_offset - cut_seconds
    if offset <= 0:
        offset = 1
    return round(offset * (stream.drift_factor or 1.0))


def _candidate_query_for_archive(event_ids: set[str]):
    if not event_ids:
        return []
    return (
        Match.query.options(
            selectinload(Match.event),
            selectinload(Match.participants).selectinload(MatchParticipant.athlete),
        )
        .join(Event)
        .filter(Event.ibjjf_id.in_(event_ids))
        .order_by(Match.happened_at, Match.fight_number, Match.match_number, Match.id)
        .all()
    )


def _stream_for_match(match: Match, streams_by_key, event_start_dates):
    mat_number = _match_mat_number(match.match_location)
    if mat_number is None:
        return None, "no_mat_number"
    day_number = _match_day_number(match, event_start_dates)
    if day_number is None:
        matching_streams = [
            stream
            for (event_id, _day, mat), stream in streams_by_key.items()
            if event_id == match.event.ibjjf_id and mat == mat_number
        ]
        if not matching_streams:
            return None, "no_stream_for_event_mat_without_day"
        return matching_streams[0], None
    stream = streams_by_key.get((match.event.ibjjf_id, day_number, mat_number))
    if not stream:
        return None, "no_stream_for_event_day_mat"
    return stream, None


def _participant_names(participants) -> str:
    return " vs ".join(participant.athlete.name for participant in participants)


def load_candidates_for_archive(
    session, archive: LivestreamFrameArchive
) -> list[Candidate]:
    usages = archive_usage_rows(session, archive.youtube_video_id)
    streams_for_archive = [usage.stream for usage in usages]
    event_ids = {usage.stream.event_id for usage in usages if usage.stream.event_id}
    if not event_ids:
        return []

    streams_by_key = {
        (
            usage.stream.event_id,
            usage.stream.day_number,
            usage.stream.mat_number,
        ): usage.stream
        for usage in usages
    }
    event_start_dates = _event_start_dates(event_ids)
    matches = _candidate_query_for_archive(event_ids)

    candidates = []
    for match in matches:
        participants = list(match.participants)
        if len(participants) != 2:
            continue
        if any(_note_indicates_no_fight(participant) for participant in participants):
            continue
        stream, _reason = _stream_for_match(match, streams_by_key, event_start_dates)
        if not stream:
            continue
        candidates.append(
            Candidate(
                match=match,
                participants=(participants[0], participants[1]),
                stream=stream,
                order_index=len(candidates),
                expected_start_second=_expected_video_offset_seconds(
                    match, stream, streams_for_archive
                ),
            )
        )
    return candidates


def analyze_candidate_loading(session, scan_or_archive_id) -> SimpleNamespace:
    scan = _scan_from_id(session, scan_or_archive_id)
    if not scan:
        return SimpleNamespace(skipped="not_found")
    archive = session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return SimpleNamespace(skipped="no_archive")

    usages = archive_usage_rows(session, archive.youtube_video_id)
    streams_for_archive = [usage.stream for usage in usages]
    event_ids = {usage.stream.event_id for usage in usages if usage.stream.event_id}
    streams_by_key = {
        (
            usage.stream.event_id,
            usage.stream.day_number,
            usage.stream.mat_number,
        ): usage.stream
        for usage in usages
    }
    event_start_dates = _event_start_dates(event_ids)
    matches = _candidate_query_for_archive(event_ids)
    rows = []
    reason_counts = Counter()
    reason_counts_by_event = Counter()
    match_counts_by_event_day_mat = Counter()
    included_counts_by_event_day_mat = Counter()
    included = 0
    for match in matches:
        participants = list(match.participants)
        reason = None
        stream = None
        expected_start_second = None
        mat_number = _match_mat_number(match.match_location)
        day_number = _match_day_number(match, event_start_dates)
        event_ibjjf_id = match.event.ibjjf_id if match.event else None
        match_counts_by_event_day_mat[(event_ibjjf_id, day_number, mat_number)] += 1
        if len(participants) != 2:
            reason = f"participant_count_{len(participants)}"
        elif any(_note_indicates_no_fight(participant) for participant in participants):
            reason = "no_fight_note"
        else:
            stream, reason = _stream_for_match(match, streams_by_key, event_start_dates)
            if stream:
                expected_start_second = _expected_video_offset_seconds(
                    match, stream, streams_for_archive
                )
                included += 1
                included_counts_by_event_day_mat[
                    (event_ibjjf_id, day_number, mat_number)
                ] += 1
        if reason:
            reason_counts[reason] += 1
            reason_counts_by_event[(reason, event_ibjjf_id)] += 1
        rows.append(
            {
                "included": reason is None,
                "reason": reason,
                "match_id": str(match.id),
                "event_ibjjf_id": event_ibjjf_id,
                "day_number": day_number,
                "mat_number": mat_number,
                "happened_at": match.happened_at.isoformat(),
                "match_location": match.match_location,
                "match_number": match.match_number,
                "fight_number": match.fight_number,
                "expected_start_second": expected_start_second,
                "video_start_offset_seconds": match.video_start_offset_seconds,
                "participants": (
                    _participant_names(participants) if participants else ""
                ),
            }
        )
    return SimpleNamespace(
        skipped=None,
        archive_id=archive.id,
        youtube_video_id=archive.youtube_video_id,
        usage_count=len(usages),
        event_ids=sorted(event_ids),
        stream_keys=sorted(streams_by_key),
        event_start_dates={
            event_id: value.isoformat() for event_id, value in event_start_dates.items()
        },
        total_matches=len(matches),
        included=included,
        excluded=len(matches) - included,
        reason_counts=dict(reason_counts),
        reason_counts_by_event={
            f"{reason}:{event_id}": count
            for (reason, event_id), count in reason_counts_by_event.items()
        },
        match_counts_by_event_day_mat={
            f"{event_id}:day{day}:mat{mat}": count
            for (event_id, day, mat), count in match_counts_by_event_day_mat.items()
        },
        included_counts_by_event_day_mat={
            f"{event_id}:day{day}:mat{mat}": count
            for (event_id, day, mat), count in included_counts_by_event_day_mat.items()
        },
        rows=rows,
    )


def livestream_rows_for_archive(session, scan_or_archive_id) -> SimpleNamespace:
    scan = _scan_from_id(session, scan_or_archive_id)
    if not scan:
        return SimpleNamespace(skipped="not_found")
    archive = session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return SimpleNamespace(skipped="no_archive")

    streams = LiveStream.query.order_by(
        LiveStream.event_id,
        LiveStream.day_number,
        LiveStream.mat_number,
        LiveStream.start_hour,
        LiveStream.start_minute,
        LiveStream.start_seconds,
    ).all()
    rows = []
    for stream in streams:
        youtube_video_id = extract_youtube_video_id(stream.link)
        if youtube_video_id != archive.youtube_video_id:
            continue
        rows.append(
            {
                "id": str(stream.id),
                "event_id": stream.event_id,
                "day_number": stream.day_number,
                "mat_number": stream.mat_number,
                "start": (
                    f"{stream.start_hour:02d}:"
                    f"{stream.start_minute:02d}:"
                    f"{stream.start_seconds:02d}"
                ),
                "end": f"{stream.end_hour:02d}:{stream.end_minute:02d}",
                "drift_factor": stream.drift_factor,
                "hide_all": stream.hide_all,
                "link": stream.link,
            }
        )
    return SimpleNamespace(
        skipped=None,
        archive_id=archive.id,
        youtube_video_id=archive.youtube_video_id,
        rows=rows,
    )


def _scan_from_id(session, scan_or_archive_id):
    if isinstance(scan_or_archive_id, LivestreamFrameTextScan):
        return scan_or_archive_id
    value = scan_or_archive_id
    if isinstance(value, str):
        value = uuid.UUID(value)
    scan = session.get(LivestreamFrameTextScan, value)
    if scan:
        return scan
    return LivestreamFrameTextScan.query.filter_by(archive_id=value).one_or_none()


def clear_livestream_match_links(session, archive_id) -> dict[str, int]:
    if isinstance(archive_id, str):
        archive_id = uuid.UUID(archive_id)
    events = LivestreamFrameTextEvent.query.filter_by(archive_id=archive_id).all()
    if not events:
        return {"matches": 0, "participants": 0, "associations": 0}

    linked_events = [event for event in events if event.match_id is not None]
    match_ids = {event.match_id for event in linked_events}
    participants = (
        MatchParticipant.query.filter(MatchParticipant.match_id.in_(match_ids)).all()
        if match_ids
        else []
    )
    participant_ids = {participant.id for participant in participants}
    if match_ids:
        Match.query.filter(Match.id.in_(match_ids)).update(
            {
                "video_start_offset_seconds": None,
                "final_match_time_seconds": None,
                "final_top_points": None,
                "final_top_advantages": None,
                "final_top_penalties": None,
                "final_bottom_points": None,
                "final_bottom_advantages": None,
                "final_bottom_penalties": None,
            },
            synchronize_session="fetch",
        )
    if participant_ids:
        MatchParticipant.query.filter(MatchParticipant.id.in_(participant_ids)).update(
            {"scoreboard_position": None},
            synchronize_session="fetch",
        )
    for event in linked_events:
        event.match_id = None
    return {
        "matches": len(match_ids),
        "participants": len(participant_ids),
        "associations": len(linked_events),
    }


def _final_score_dict(state: TextState) -> dict[str, int | None]:
    return {field: getattr(state, field) for field in SCORE_FIELDS}


def _choice_debug(window: MatchWindow, choice: MatchChoice) -> dict:
    match = choice.candidate.match
    return {
        "match_id": str(match.id),
        "order_index": choice.candidate.order_index,
        "expected_start_second": choice.candidate.expected_start_second,
        "stored_video_start_offset_seconds": match.video_start_offset_seconds,
        "time_delta_seconds": choice.time_delta_seconds,
        "score": round(choice.score, 2),
        "raw_name_score": round(choice.raw_score, 2),
        "prestart_lead_seconds": _prestart_lead_seconds(window),
        "poststart_two_sided_support_score": round(
            _best_poststart_two_sided_support_score(window, choice), 2
        ),
        "coherent_conflicting_poststart_pairs": (
            _coherent_conflicting_poststart_pair_count(window, choice)
        ),
        "stale_prestart_evidence": _has_stale_conflicting_prestart_evidence(
            window, choice
        ),
        "top_participant": choice.top_participant.athlete.name,
        "bottom_participant": choice.bottom_participant.athlete.name,
        "winner": next(
            (
                participant.athlete.name
                for participant in choice.candidate.participants
                if participant.winner
            ),
            None,
        ),
        "loser": next(
            (
                participant.athlete.name
                for participant in choice.candidate.participants
                if not participant.winner
            ),
            None,
        ),
        "match_time": match.happened_at.isoformat(),
        "match_location": match.match_location,
    }


def _rejection_reason(
    window: MatchWindow,
    choices: list[MatchChoice],
    choice: MatchChoice | None,
    cursor: int,
) -> str | None:
    if choice:
        return None
    if not window.has_running_timer:
        return "no_running_clock"
    if not choices:
        return "no_candidates_in_cursor_or_time_window"
    if _has_stale_conflicting_prestart_evidence(window, choices[0]):
        return "stale_conflicting_prestart_names"
    if choices[0].score < MIN_NAME_SCORE:
        return "below_name_score_threshold"
    if not any(
        _has_non_cursor_name_evidence(window, item, cursor)
        for item in choices
        if item.score >= MIN_NAME_SCORE
    ):
        return "missing_non_cursor_name_evidence"
    if len(choices) > 1 and choices[0].score - choices[1].score < MIN_SCORE_MARGIN:
        return "ambiguous_candidate_margin"
    return "not_selected"


def _window_has_terminal_boundary(window: MatchWindow) -> bool:
    return any(
        event.scoreboard_state == SCOREBOARD_STATE_BLANK
        or event.top_athlete_name == "Victory"
        for event in window.events
    )


def _window_has_stopped_zero_timer(window: MatchWindow) -> bool:
    return any(
        event.timer_state == "stopped" and parse_timer_seconds(event.timer_value) == 0
        for event in window.events
    )


def _window_closes_active_match(window: MatchWindow) -> bool:
    return _window_has_terminal_boundary(window) or _window_has_stopped_zero_timer(
        window
    )


def _release_speculative_forward_links(
    used_match_ids: set,
    closed_match_ids: set,
    speculative_forward_links: dict,
    linked_order_index: int,
) -> list:
    released_ids = [
        match_id
        for match_id, order_index in speculative_forward_links.items()
        if order_index > linked_order_index
    ]
    for match_id in released_ids:
        used_match_ids.discard(match_id)
        closed_match_ids.discard(match_id)
        speculative_forward_links.pop(match_id, None)
    return released_ids


def _clear_stored_choice(window: MatchWindow, choice: MatchChoice) -> None:
    match = choice.candidate.match
    match.video_start_offset_seconds = None
    match.final_match_time_seconds = None
    match.final_top_points = None
    match.final_top_advantages = None
    match.final_top_penalties = None
    match.final_bottom_points = None
    match.final_bottom_advantages = None
    match.final_bottom_penalties = None
    choice.top_participant.scoreboard_position = None
    choice.bottom_participant.scoreboard_position = None
    for event in window.events:
        if event.match_id == match.id:
            event.match_id = None


def analyze_text_scan_links(session, scan_or_archive_id) -> SimpleNamespace:
    scan = _scan_from_id(session, scan_or_archive_id)
    if not scan:
        return SimpleNamespace(
            linked=0,
            windows=0,
            candidates=0,
            skipped="not_found",
            decisions=[],
        )
    if scan.status != "success":
        return SimpleNamespace(
            linked=0,
            windows=0,
            candidates=0,
            skipped=scan.status,
            decisions=[],
        )

    archive = session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return SimpleNamespace(
            linked=0,
            windows=0,
            candidates=0,
            skipped="no_archive",
            decisions=[],
        )

    events = (
        LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    windows = extract_match_windows(events)
    candidates = load_candidates_for_archive(session, archive)
    cursor = 0
    linked = 0
    used_match_ids = set()
    closed_match_ids = set()
    speculative_forward_links = {}
    speculative_forward_decisions = {}
    active_candidate = None
    allow_stale_cursor_recovery = False
    decisions = []
    for index, window in enumerate(windows, start=1):
        cursor_before = cursor
        choices = _candidate_choices(
            window,
            candidates,
            cursor,
            used_match_ids,
            allow_stale_cursor_recovery=allow_stale_cursor_recovery,
        )
        choice = choose_active_continuation_for_window(window, active_candidate)
        continuation = choice is not None
        if not choice:
            choice = choose_match_for_window(
                window,
                candidates,
                cursor,
                used_match_ids,
                set(speculative_forward_links),
                allow_stale_cursor_recovery=allow_stale_cursor_recovery,
            )
        if not choice:
            choice = choose_continuation_for_window(
                window, candidates, cursor, used_match_ids, closed_match_ids
            )
            continuation = choice is not None
        if choice:
            if not continuation:
                if choice.candidate.order_index < cursor_before:
                    released_ids = _release_speculative_forward_links(
                        used_match_ids,
                        closed_match_ids,
                        speculative_forward_links,
                        choice.candidate.order_index,
                    )
                    for match_id in released_ids:
                        decision_index = speculative_forward_decisions.pop(
                            match_id, None
                        )
                        if decision_index is None:
                            continue
                        decisions[decision_index]["matched"] = None
                        decisions[decision_index][
                            "rejection_reason"
                        ] = "released_out_of_order"
                        linked -= 1
                cursor = max(cursor, choice.candidate.order_index + 1)
                allow_stale_cursor_recovery = False
                used_match_ids.add(choice.candidate.match.id)
                if (
                    choice.candidate.order_index - cursor_before
                    >= SPECULATIVE_FORWARD_RELEASE_GAP
                ):
                    speculative_forward_links[choice.candidate.match.id] = (
                        choice.candidate.order_index
                    )
                    speculative_forward_decisions[choice.candidate.match.id] = len(
                        decisions
                    )
            if _window_closes_active_match(window):
                closed_match_ids.add(choice.candidate.match.id)
            active_candidate = (
                None if _window_closes_active_match(window) else choice.candidate
            )
            linked += 1
        else:
            if _rejected_stale_cursor_choice(window, choices, cursor_before):
                allow_stale_cursor_recovery = True
            if _window_closes_active_match(window):
                active_candidate = None
        decisions.append(
            {
                "window_index": index,
                "cursor_before": cursor_before,
                "start_second": window.start_second,
                "end_second": window.end_second,
                "video_start_offset_seconds": window.video_start_offset_seconds,
                "top_names": window.top_names,
                "bottom_names": window.bottom_names,
                "position_name_pairs": window.position_name_pairs,
                "final_timer_seconds": window.final_timer_seconds,
                "has_running_timer": window.has_running_timer,
                "final_score": _final_score_dict(window.final_state),
                "matched": _choice_debug(window, choice) if choice else None,
                "continuation": continuation,
                "rejection_reason": _rejection_reason(
                    window, choices, choice, cursor_before
                ),
                "top_candidates": [_choice_debug(window, item) for item in choices[:5]],
            }
        )
    return SimpleNamespace(
        linked=linked,
        windows=len(windows),
        candidates=len(candidates),
        skipped=None,
        decisions=decisions,
    )


def _match_has_non_zero_final_score(match: Match) -> bool:
    return any((getattr(match, f"final_{field}") or 0) != 0 for field in SCORE_FIELDS)


def _should_preserve_existing_final_score(match: Match, window: MatchWindow) -> bool:
    return (
        not window.has_running_timer
        and window.final_timer_seconds == 0
        and _has_full_zero_score(window.final_state)
        and _match_has_non_zero_final_score(match)
    )


def _store_choice(
    session,
    window: MatchWindow,
    choice: MatchChoice,
    update_start_offset: bool = True,
) -> None:
    match = choice.candidate.match
    if update_start_offset:
        match.video_start_offset_seconds = window.video_start_offset_seconds
    if update_start_offset or window.final_timer_seconds is not None:
        match.final_match_time_seconds = window.final_timer_seconds
        if not _should_preserve_existing_final_score(match, window):
            match.final_top_points = window.final_state.top_points
            match.final_top_advantages = window.final_state.top_advantages
            match.final_top_penalties = window.final_state.top_penalties
            match.final_bottom_points = window.final_state.bottom_points
            match.final_bottom_advantages = window.final_state.bottom_advantages
            match.final_bottom_penalties = window.final_state.bottom_penalties

    if update_start_offset:
        choice.top_participant.scoreboard_position = "top"
        choice.bottom_participant.scoreboard_position = "bottom"
    for event in window.events:
        event.match_id = match.id


def link_completed_text_scan(
    session, scan_or_archive_id, dry_run: bool = False
) -> SimpleNamespace:
    scan = _scan_from_id(session, scan_or_archive_id)
    if not scan:
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped="not_found")
    if scan.status != "success":
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped=scan.status)

    archive = session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped="no_archive")

    events = (
        LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    windows = extract_match_windows(events)
    if not dry_run:
        clear_livestream_match_links(session, scan.archive_id)
    candidates = load_candidates_for_archive(session, archive)
    cursor = 0
    linked = 0
    used_match_ids = set()
    closed_match_ids = set()
    speculative_forward_links = {}
    speculative_forward_windows = {}
    active_candidate = None
    allow_stale_cursor_recovery = False
    for window in windows:
        cursor_before = cursor
        choices = _candidate_choices(
            window,
            candidates,
            cursor,
            used_match_ids,
            allow_stale_cursor_recovery=allow_stale_cursor_recovery,
        )
        choice = choose_active_continuation_for_window(window, active_candidate)
        continuation = choice is not None
        if not choice:
            choice = choose_match_for_window(
                window,
                candidates,
                cursor,
                used_match_ids,
                set(speculative_forward_links),
                allow_stale_cursor_recovery=allow_stale_cursor_recovery,
            )
        if not choice:
            choice = choose_continuation_for_window(
                window, candidates, cursor, used_match_ids, closed_match_ids
            )
            continuation = choice is not None
        if not choice:
            if _rejected_stale_cursor_choice(window, choices, cursor_before):
                allow_stale_cursor_recovery = True
            if _window_closes_active_match(window):
                active_candidate = None
            continue
        if not dry_run:
            _store_choice(
                session,
                window,
                choice,
                update_start_offset=not continuation,
            )
        if not continuation:
            if choice.candidate.order_index < cursor_before:
                released_ids = _release_speculative_forward_links(
                    used_match_ids,
                    closed_match_ids,
                    speculative_forward_links,
                    choice.candidate.order_index,
                )
                for match_id in released_ids:
                    stored = speculative_forward_windows.pop(match_id, None)
                    if stored is None:
                        continue
                    stored_window, stored_choice = stored
                    if not dry_run:
                        _clear_stored_choice(stored_window, stored_choice)
                    linked -= 1
            cursor = max(cursor, choice.candidate.order_index + 1)
            allow_stale_cursor_recovery = False
            used_match_ids.add(choice.candidate.match.id)
            if (
                choice.candidate.order_index - cursor_before
                >= SPECULATIVE_FORWARD_RELEASE_GAP
            ):
                speculative_forward_links[choice.candidate.match.id] = (
                    choice.candidate.order_index
                )
                speculative_forward_windows[choice.candidate.match.id] = (
                    window,
                    choice,
                )
        if _window_closes_active_match(window):
            closed_match_ids.add(choice.candidate.match.id)
        active_candidate = (
            None if _window_closes_active_match(window) else choice.candidate
        )
        linked += 1
    return SimpleNamespace(
        linked=linked,
        windows=len(windows),
        candidates=len(candidates),
        skipped=None,
    )


def relink_completed_text_scans_for_events(session, event_ids) -> list[SimpleNamespace]:
    event_ids = {str(event_id) for event_id in event_ids if event_id}
    if not event_ids:
        return []

    results = []
    usages_by_video_id = discover_livestream_usages(session)
    scans = (
        LivestreamFrameTextScan.query.filter_by(status="success")
        .order_by(LivestreamFrameTextScan.created_at, LivestreamFrameTextScan.id)
        .all()
    )
    for scan in scans:
        archive = session.get(LivestreamFrameArchive, scan.archive_id)
        if not archive:
            continue
        usage_event_ids = {
            usage.stream.event_id
            for usage in usages_by_video_id.get(archive.youtube_video_id, [])
            if usage.stream.event_id
        }
        if event_ids.isdisjoint(usage_event_ids):
            continue

        summary = link_completed_text_scan(session, scan)
        results.append(
            SimpleNamespace(
                scan_id=scan.id,
                archive_id=archive.id,
                linked=summary.linked,
                windows=summary.windows,
                candidates=summary.candidates,
                skipped=summary.skipped,
            )
        )
    return results
