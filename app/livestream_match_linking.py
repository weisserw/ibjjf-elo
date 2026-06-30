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

from livestream_frame_archive import archive_usage_rows
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
TIME_MATCH_WINDOW_SECONDS = 20 * 60


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
    return (
        timer_seconds is not None
        and timer_seconds >= 4 * 60
        and timer_seconds % 60 == 0
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

    starts = []
    for index, point in enumerate(timeline):
        if not _is_start_point(point):
            continue
        if starts and _same_start_names(timeline[starts[-1]].state, point.state):
            continue
        starts.append(index)
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
        running_timer_start_second = _running_timer_start_second(points)
        windows.append(
            MatchWindow(
                start_second=points[0].event.frame_second,
                end_second=points[-1].event.frame_second,
                video_start_offset_seconds=running_timer_start_second,
                events=[point.event for point in points],
                top_names=_dedupe(names_top),
                bottom_names=_dedupe(names_bottom),
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
        return MatchChoice(candidate, first_top_score, first, second, first_top_score)
    return MatchChoice(candidate, second_top_score, second, first, second_top_score)


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
        if gap > LOOKAHEAD_MATCHES and not time_aligned:
            continue
        choice = _choice_for_candidate(window, candidate)
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


def choose_match_for_window(
    window: MatchWindow,
    candidates: list[Candidate],
    cursor: int,
    used_match_ids: set | None = None,
) -> MatchChoice | None:
    if not window.has_running_timer:
        return None
    choices = _candidate_choices(window, candidates, cursor, used_match_ids)
    if not choices:
        return None
    best = choices[0]
    second_score = choices[1].score if len(choices) > 1 else 0.0
    if best.score < MIN_NAME_SCORE:
        return None
    if second_score and best.score - second_score < MIN_SCORE_MARGIN:
        return _sequential_choice_for_ambiguous_window(window, choices, cursor)
    return best


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
            synchronize_session="fetch",
        )
    if participant_ids:
        MatchParticipant.query.filter(MatchParticipant.id.in_(participant_ids)).update(
            {"scoreboard_position": None},
            synchronize_session="fetch",
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


def _final_score_dict(state: TextState) -> dict[str, int | None]:
    return {field: getattr(state, field) for field in SCORE_FIELDS}


def _choice_debug(choice: MatchChoice) -> dict:
    match = choice.candidate.match
    return {
        "match_id": str(match.id),
        "order_index": choice.candidate.order_index,
        "expected_start_second": choice.candidate.expected_start_second,
        "stored_video_start_offset_seconds": match.video_start_offset_seconds,
        "time_delta_seconds": choice.time_delta_seconds,
        "score": round(choice.score, 2),
        "raw_name_score": round(choice.raw_score, 2),
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
    window: MatchWindow, choices: list[MatchChoice], choice: MatchChoice | None
) -> str | None:
    if choice:
        return None
    if not window.has_running_timer:
        return "no_running_clock"
    if not choices:
        return "no_candidates_in_cursor_or_time_window"
    if choices[0].score < MIN_NAME_SCORE:
        return "below_name_score_threshold"
    if len(choices) > 1 and choices[0].score - choices[1].score < MIN_SCORE_MARGIN:
        return "ambiguous_candidate_margin"
    return "not_selected"


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
    decisions = []
    for index, window in enumerate(windows, start=1):
        cursor_before = cursor
        choices = _candidate_choices(window, candidates, cursor, used_match_ids)
        choice = choose_match_for_window(window, candidates, cursor, used_match_ids)
        if choice:
            cursor = max(cursor, choice.candidate.order_index + 1)
            used_match_ids.add(choice.candidate.match.id)
            linked += 1
        decisions.append(
            {
                "window_index": index,
                "cursor_before": cursor_before,
                "start_second": window.start_second,
                "end_second": window.end_second,
                "video_start_offset_seconds": window.video_start_offset_seconds,
                "top_names": window.top_names,
                "bottom_names": window.bottom_names,
                "final_timer_seconds": window.final_timer_seconds,
                "has_running_timer": window.has_running_timer,
                "final_score": _final_score_dict(window.final_state),
                "matched": _choice_debug(choice) if choice else None,
                "rejection_reason": _rejection_reason(window, choices, choice),
                "top_candidates": [_choice_debug(item) for item in choices[:5]],
            }
        )
    return SimpleNamespace(
        linked=linked,
        windows=len(windows),
        candidates=len(candidates),
        skipped=None,
        decisions=decisions,
    )


def _store_choice(session, window: MatchWindow, choice: MatchChoice) -> None:
    match = choice.candidate.match
    match.video_start_offset_seconds = window.video_start_offset_seconds
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
    for window in windows:
        choice = choose_match_for_window(window, candidates, cursor, used_match_ids)
        if not choice:
            continue
        if not dry_run:
            _store_choice(session, window, choice)
        cursor = max(cursor, choice.candidate.order_index + 1)
        used_match_ids.add(choice.candidate.match.id)
        linked += 1
    return SimpleNamespace(
        linked=linked,
        windows=len(windows),
        candidates=len(candidates),
        skipped=None,
    )
