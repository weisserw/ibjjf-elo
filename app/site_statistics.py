from datetime import datetime

from sqlalchemy import or_, text

from livestreams import get_livestream_link, load_livestream_links
from models import (
    Athlete,
    Division,
    Event,
    FloEventTag,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameTextEvent,
    Match,
    MatchParticipant,
    SiteStatistic,
)
from youtube_utils import extract_youtube_video_id


COVERED_MATCH_COUNT_KEY = "covered_match_count"
NO_MATCH_NOTES = {
    "disqualified by no show",
    "desqualificado por no show",
    "disqualified by overweight",
    "disqualified by acima do peso",
    "disqualified by withdraw",
    "desqualificado por retirada",
}
EVENT_ID_BATCH_SIZE = 500
POSTGRES_REFRESH_LOCK_ID = 1784258214


def _empty_livestream_data():
    return {
        "tournament_days": {},
        "tournament_end_days": {},
        "live_streams": {},
        "flo_event_tags": {},
        "flo_mat_links": {},
        "special_search_names": {},
    }


def _load_coverage_link_data(session, event_ids):
    result = _empty_livestream_data()
    event_ids = sorted(event_id for event_id in event_ids if event_id)
    for start in range(0, len(event_ids), EVENT_ID_BATCH_SIZE):
        batch = event_ids[start : start + EVENT_ID_BATCH_SIZE]
        loaded = load_livestream_links(session, batch)
        for key in result:
            result[key].update(loaded.get(key, {}))
    return result


def _participant_values(row):
    return {
        "winner": row.participant_winner,
        "note": row.participant_note,
        "name": row.athlete_name,
        "personal_name": row.athlete_personal_name,
    }


def _load_visible_ocr_archive_links(session):
    visible_archive_keys = {
        (event_id, youtube_video_id)
        for event_id, link in session.query(LiveStream.event_id, LiveStream.link)
        .filter(LiveStream.hide_all.is_(False))
        .all()
        if (youtube_video_id := extract_youtube_video_id(link)) is not None
    }
    if not visible_archive_keys:
        return {}

    rows = (
        session.query(
            LivestreamFrameTextEvent.match_id,
            Event.ibjjf_id,
            LivestreamFrameArchive.youtube_video_id,
            LivestreamFrameArchive.canonical_url,
        )
        .select_from(LivestreamFrameTextEvent)
        .join(Match, Match.id == LivestreamFrameTextEvent.match_id)
        .join(Event, Event.id == Match.event_id)
        .join(
            LivestreamFrameArchive,
            LivestreamFrameArchive.id == LivestreamFrameTextEvent.archive_id,
        )
        .filter(LivestreamFrameTextEvent.match_id.isnot(None))
        .distinct()
        .order_by(
            LivestreamFrameTextEvent.match_id,
            LivestreamFrameArchive.youtube_video_id,
        )
        .all()
    )
    links_by_match_id = {}
    for match_id, event_id, youtube_video_id, canonical_url in rows:
        if (event_id, youtube_video_id) not in visible_archive_keys:
            continue
        if extract_youtube_video_id(canonical_url) is None:
            continue
        links_by_match_id.setdefault(match_id, canonical_url)
    return links_by_match_id


def _is_covered_match(match, participants, livestream_data, linked_archive_url=None):
    if len(participants) != 2:
        return False
    if any(
        (participant["note"] or "").lower() in NO_MATCH_NOTES
        for participant in participants
    ):
        return False
    if isinstance(match["video_link"], str) and match["video_link"].lower() == "none":
        return False
    if extract_youtube_video_id(linked_archive_url) is not None:
        return True

    winner = next(
        (participant for participant in participants if participant["winner"]),
        participants[0],
    )
    loser = next(
        (participant for participant in participants if participant is not winner),
        participants[1],
    )
    resolved_link = get_livestream_link(
        livestream_data,
        match["event_ibjjf_id"],
        winner["name"],
        loser["name"],
        match["happened_at"],
        match["match_location"],
        match["division_belt"],
        match["division_age"],
        match["division_size"],
        match["match_number"],
        winner["personal_name"],
        loser["personal_name"],
        match["video_link"],
        match["video_start_offset_seconds"],
    )
    return extract_youtube_video_id(resolved_link) is not None


def calculate_covered_match_count(session):
    coverage_event_ids = {
        event_id for (event_id,) in session.query(LiveStream.event_id).distinct().all()
    }
    coverage_event_ids.update(
        event_id for (event_id,) in session.query(FloEventTag.event_id).distinct().all()
    )
    livestream_data = _load_coverage_link_data(session, coverage_event_ids)
    linked_archive_urls = _load_visible_ocr_archive_links(session)

    rows = (
        session.query(
            Match.id.label("match_id"),
            Match.happened_at,
            Match.match_location,
            Match.division_size,
            Match.match_number,
            Match.video_link,
            Match.video_start_offset_seconds,
            Event.ibjjf_id.label("event_ibjjf_id"),
            Division.belt.label("division_belt"),
            Division.age.label("division_age"),
            MatchParticipant.id.label("participant_id"),
            MatchParticipant.winner.label("participant_winner"),
            MatchParticipant.note.label("participant_note"),
            Athlete.name.label("athlete_name"),
            Athlete.personal_name.label("athlete_personal_name"),
        )
        .select_from(Match)
        .join(Event, Event.id == Match.event_id)
        .join(Division, Division.id == Match.division_id)
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .join(Athlete, Athlete.id == MatchParticipant.athlete_id)
        .filter(
            or_(
                Match.video_link.isnot(None),
                Event.ibjjf_id.in_(coverage_event_ids),
            )
        )
        .order_by(Match.id, MatchParticipant.id)
        .yield_per(2000)
    )

    covered_count = 0
    current_match_id = None
    current_match = None
    participants = []

    for row in rows:
        if current_match_id is not None and row.match_id != current_match_id:
            covered_count += int(
                _is_covered_match(
                    current_match,
                    participants,
                    livestream_data,
                    linked_archive_urls.get(current_match_id),
                )
            )
            participants = []

        if row.match_id != current_match_id:
            current_match_id = row.match_id
            current_match = {
                "happened_at": row.happened_at,
                "match_location": row.match_location,
                "division_size": row.division_size,
                "match_number": row.match_number,
                "video_link": row.video_link,
                "video_start_offset_seconds": row.video_start_offset_seconds,
                "event_ibjjf_id": row.event_ibjjf_id,
                "division_belt": row.division_belt,
                "division_age": row.division_age,
            }
        participants.append(_participant_values(row))

    if current_match_id is not None:
        covered_count += int(
            _is_covered_match(
                current_match,
                participants,
                livestream_data,
                linked_archive_urls.get(current_match_id),
            )
        )

    return covered_count


def refresh_covered_match_count(session):
    session.flush()
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": POSTGRES_REFRESH_LOCK_ID},
        )
    covered_count = calculate_covered_match_count(session)
    statistic = session.get(SiteStatistic, COVERED_MATCH_COUNT_KEY)
    if statistic is None:
        statistic = SiteStatistic(key=COVERED_MATCH_COUNT_KEY, value=covered_count)
        session.add(statistic)
    else:
        statistic.value = covered_count
        statistic.updated_at = datetime.utcnow()
    return covered_count


def get_covered_match_count(session):
    statistic = session.get(SiteStatistic, COVERED_MATCH_COUNT_KEY)
    return statistic.value if statistic is not None else None
