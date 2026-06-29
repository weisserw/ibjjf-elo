from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from rapidfuzz import fuzz
from sqlalchemy.orm import selectinload

from livestream_frame_archive import archive_usage_rows
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
    MatchParticipantTextEvent,
    RegistrationLink,
)


NO_FIGHT_NOTE_PARTS = (
    "no show",
    "overweight",
    "acima do peso",
)
MIN_NAME_SCORE = 78.0
MIN_SCORE_MARGIN = 8.0
LOOKAHEAD_MATCHES = 8


@dataclass
class TimelinePoint:
    event: LivestreamFrameTextEvent
    state: TextState


@dataclass
class MatchWindow:
    start_second: int
    end_second: int
    events: list[LivestreamFrameTextEvent]
    top_names: list[str]
    bottom_names: list[str]
    final_state: TextState
    final_timer_seconds: int | None


@dataclass
class Candidate:
    match: Match
    participants: tuple[MatchParticipant, MatchParticipant]
    stream: LiveStream
    order_index: int


@dataclass
class MatchChoice:
    candidate: Candidate
    score: float
    top_participant: MatchParticipant
    bottom_participant: MatchParticipant


def parse_timer_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})", value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9 ]+", " ", value.upper()).strip()


def _has_full_zero_score(state: TextState) -> bool:
    return all(getattr(state, field) == 0 for field in SCORE_FIELDS)


def _has_any_name(state: TextState) -> bool:
    return bool(state.top_athlete_name or state.bottom_athlete_name)


def _is_start_point(point: TimelinePoint) -> bool:
    state = point.state
    return (
        state.scoreboard_state == SCOREBOARD_STATE_VISIBLE
        and _has_full_zero_score(state)
        and _has_any_name(state)
        and state.timer_state != "running"
        and state.top_athlete_name != "Victory"
    )


def _score_state_from_window(points: list[TimelinePoint]) -> TextState:
    score_state = TextState()
    for point in points:
        if point.state.scoreboard_state == SCOREBOARD_STATE_BLANK:
            continue
        if any(getattr(point.state, field) is not None for field in SCORE_FIELDS):
            for field in SCORE_FIELDS:
                setattr(score_state, field, getattr(point.state, field))
            score_state.scoreboard_state = point.state.scoreboard_state
    return score_state


def extract_match_windows(events: list[LivestreamFrameTextEvent]) -> list[MatchWindow]:
    state = TextState()
    timeline = []
    for event in sorted(events, key=lambda item: item.frame_second):
        state = apply_event_to_state(state, event)
        timeline.append(TimelinePoint(event=event, state=state.copy()))

    starts = [index for index, point in enumerate(timeline) if _is_start_point(point)]
    windows = []
    for start_position, start_index in enumerate(starts):
        next_start_index = (
            starts[start_position + 1]
            if start_position + 1 < len(starts)
            else len(timeline)
        )
        points = timeline[start_index:next_start_index]
        if not points:
            continue

        names_top = []
        names_bottom = []
        final_timer_seconds = None
        for point in points:
            if (
                point.state.top_athlete_name
                and point.state.top_athlete_name != "Victory"
            ):
                names_top.append(point.state.top_athlete_name)
            if point.state.bottom_athlete_name:
                names_bottom.append(point.state.bottom_athlete_name)
            if point.state.timer_state == "stopped":
                parsed = parse_timer_seconds(point.state.timer_value)
                if parsed is not None:
                    final_timer_seconds = parsed

        final_state = _score_state_from_window(points)
        windows.append(
            MatchWindow(
                start_second=points[0].event.frame_second,
                end_second=points[-1].event.frame_second,
                events=[point.event for point in points],
                top_names=_dedupe(names_top),
                bottom_names=_dedupe(names_bottom),
                final_state=final_state,
                final_timer_seconds=final_timer_seconds,
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
    top_score = _best_name_score(window.top_names, top_participant.athlete.name)
    bottom_score = _best_name_score(
        window.bottom_names, bottom_participant.athlete.name
    )
    if window.top_names and window.bottom_names:
        return top_score * 0.7 + bottom_score * 0.3
    if window.top_names:
        return top_score
    if window.bottom_names:
        return bottom_score * 0.85
    return 0.0


def _choice_for_candidate(window: MatchWindow, candidate: Candidate) -> MatchChoice:
    first, second = candidate.participants
    first_top_score = _orientation_score(window, first, second)
    second_top_score = _orientation_score(window, second, first)
    if first_top_score >= second_top_score:
        return MatchChoice(candidate, first_top_score, first, second)
    return MatchChoice(candidate, second_top_score, second, first)


def choose_match_for_window(
    window: MatchWindow, candidates: list[Candidate], cursor: int
) -> MatchChoice | None:
    choices = []
    for candidate in candidates:
        if candidate.order_index < cursor:
            continue
        gap = candidate.order_index - cursor
        if gap > LOOKAHEAD_MATCHES:
            continue
        choice = _choice_for_candidate(window, candidate)
        order_penalty = min(gap * 3.0, 18.0)
        choices.append(
            MatchChoice(
                candidate=choice.candidate,
                score=choice.score - order_penalty,
                top_participant=choice.top_participant,
                bottom_participant=choice.bottom_participant,
            )
        )
    if not choices:
        return None
    choices.sort(key=lambda item: item.score, reverse=True)
    best = choices[0]
    second_score = choices[1].score if len(choices) > 1 else 0.0
    if best.score < MIN_NAME_SCORE:
        return None
    if second_score and best.score - second_score < MIN_SCORE_MARGIN:
        return None
    return best


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
    rows = RegistrationLink.query.filter(RegistrationLink.event_id.in_(event_ids)).all()
    return {
        row.event_id: row.event_start_date
        for row in rows
        if row.event_id and row.event_start_date
    }


def _match_day_number(
    match: Match, event_start_dates: dict[str, datetime]
) -> int | None:
    ibjjf_id = match.event.ibjjf_id if match.event else None
    event_start = event_start_dates.get(ibjjf_id)
    if not event_start:
        return None
    return (match.happened_at.date() - event_start.date()).days + 1


def load_candidates_for_archive(
    session, archive: LivestreamFrameArchive
) -> list[Candidate]:
    usages = archive_usage_rows(session, archive.youtube_video_id)
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
    matches = (
        Match.query.options(
            selectinload(Match.event),
            selectinload(Match.participants).selectinload(MatchParticipant.athlete),
        )
        .join(Event)
        .filter(Event.ibjjf_id.in_(event_ids))
        .order_by(Match.happened_at, Match.fight_number, Match.match_number, Match.id)
        .all()
    )

    candidates = []
    for match in matches:
        participants = list(match.participants)
        if len(participants) != 2:
            continue
        if any(_note_indicates_no_fight(participant) for participant in participants):
            continue
        mat_number = _match_mat_number(match.match_location)
        if mat_number is None:
            continue
        day_number = _match_day_number(match, event_start_dates)
        if day_number is None:
            matching_streams = [
                stream
                for (event_id, _day, mat), stream in streams_by_key.items()
                if event_id == match.event.ibjjf_id and mat == mat_number
            ]
            stream = matching_streams[0] if matching_streams else None
        else:
            stream = streams_by_key.get((match.event.ibjjf_id, day_number, mat_number))
        if not stream:
            continue
        candidates.append(
            Candidate(
                match=match,
                participants=(participants[0], participants[1]),
                stream=stream,
                order_index=len(candidates),
            )
        )
    return candidates


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
    event_ids = [event.id for event in events]
    if not event_ids:
        return {"matches": 0, "participants": 0, "associations": 0}

    associations = MatchParticipantTextEvent.query.filter(
        MatchParticipantTextEvent.livestream_frame_text_event_id.in_(event_ids)
    ).all()
    participant_ids = {association.match_participant_id for association in associations}
    match_ids = {
        participant.match_id
        for participant in MatchParticipant.query.filter(
            MatchParticipant.id.in_(participant_ids)
        ).all()
    }
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
            synchronize_session=False,
        )
    if participant_ids:
        MatchParticipant.query.filter(MatchParticipant.id.in_(participant_ids)).update(
            {"scoreboard_position": None},
            synchronize_session=False,
        )
    association_count = len(associations)
    if event_ids:
        MatchParticipantTextEvent.query.filter(
            MatchParticipantTextEvent.livestream_frame_text_event_id.in_(event_ids)
        ).delete(synchronize_session=False)
    return {
        "matches": len(match_ids),
        "participants": len(participant_ids),
        "associations": association_count,
    }


def _store_choice(session, window: MatchWindow, choice: MatchChoice) -> None:
    match = choice.candidate.match
    match.video_start_offset_seconds = window.start_second
    match.final_match_time_seconds = window.final_timer_seconds
    match.final_top_points = window.final_state.top_points
    match.final_top_advantages = window.final_state.top_advantages
    match.final_top_penalties = window.final_state.top_penalties
    match.final_bottom_points = window.final_state.bottom_points
    match.final_bottom_advantages = window.final_state.bottom_advantages
    match.final_bottom_penalties = window.final_state.bottom_penalties

    choice.top_participant.scoreboard_position = "top"
    choice.bottom_participant.scoreboard_position = "bottom"
    for event in window.events:
        for participant in (choice.top_participant, choice.bottom_participant):
            session.add(
                MatchParticipantTextEvent(
                    match_participant_id=participant.id,
                    livestream_frame_text_event_id=event.id,
                )
            )


def link_completed_text_scan(session, scan_or_archive_id) -> SimpleNamespace:
    scan = _scan_from_id(session, scan_or_archive_id)
    if not scan:
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped="not_found")
    if scan.status != "success":
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped=scan.status)

    clear_livestream_match_links(session, scan.archive_id)
    archive = session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return SimpleNamespace(linked=0, windows=0, candidates=0, skipped="no_archive")

    events = (
        LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    windows = extract_match_windows(events)
    candidates = load_candidates_for_archive(session, archive)
    cursor = 0
    linked = 0
    for window in windows:
        choice = choose_match_for_window(window, candidates, cursor)
        if not choice:
            continue
        _store_choice(session, window, choice)
        cursor = choice.candidate.order_index + 1
        linked += 1
    return SimpleNamespace(
        linked=linked,
        windows=len(windows),
        candidates=len(candidates),
        skipped=None,
    )
