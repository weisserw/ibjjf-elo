from datetime import datetime
import re
import uuid
from urllib.parse import quote

from constants import ADULT, BLACK
from models import (
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameTextEvent,
    Match,
)
from normalize import normalize
from sqlalchemy import func
from sqlalchemy.sql import text
from youtube_utils import canonical_youtube_url, extract_youtube_video_id


def _youtube_url_with_offset(url, offset_seconds):
    youtube_video_id = extract_youtube_video_id(url)
    if youtube_video_id is None:
        return None
    result = canonical_youtube_url(youtube_video_id)
    if offset_seconds is not None:
        result += f"&t={max(1, offset_seconds)}s"
    return result


def _stream_time_seconds(stream):
    return (
        stream.start_hour * 3600 + stream.start_minute * 60 + stream.start_seconds,
        stream.end_hour * 3600 + stream.end_minute * 60,
    )


def _match_mat_number(match_location):
    if not match_location:
        return None
    try:
        return int(match_location.split()[-1])
    except (TypeError, ValueError):
        return None


def _stream_contains_video_second(stream, related_streams, video_second):
    """Return whether a source-video second falls inside one stream segment."""
    youtube_video_id = extract_youtube_video_id(stream.link)
    if youtube_video_id is None:
        return False

    same_video_streams = sorted(
        (
            related_stream
            for related_stream in related_streams
            if extract_youtube_video_id(related_stream.link) == youtube_video_id
        ),
        key=lambda item: (
            item.start_hour,
            item.start_minute,
            item.start_seconds,
        ),
    )
    preceding_duration = 0
    for related_stream in same_video_streams:
        start_seconds, end_seconds = _stream_time_seconds(related_stream)
        duration = max(0, end_seconds - start_seconds)
        if related_stream.id == stream.id:
            drift_factor = stream.drift_factor or 1.0
            video_start = round(preceding_duration * drift_factor)
            video_end = round((preceding_duration + duration) * drift_factor)
            return video_start <= video_second < video_end
        preceding_duration += duration
    return False


def _linked_archive_segment_is_visible(
    entry,
    streams,
    event_start_date,
):
    """Resolve hide_all for the exact stream segment containing a linked match."""
    happened_at = entry["happened_at"]
    match_mat_number = _match_mat_number(entry["match_location"])
    match_day_number = None
    if event_start_date is not None:
        match_day_number = (happened_at.date() - event_start_date.date()).days + 1

    candidate_streams = streams
    if match_day_number is not None:
        day_streams = [
            stream
            for stream in candidate_streams
            if stream.day_number == match_day_number
        ]
        if day_streams:
            candidate_streams = day_streams
        elif match_mat_number is not None:
            return False

    if match_mat_number is not None:
        candidate_streams = [
            stream
            for stream in candidate_streams
            if stream.mat_number == match_mat_number
        ]
        if not candidate_streams:
            return False

    match_seconds = happened_at.hour * 3600 + happened_at.minute * 60
    time_matches = []
    for stream in candidate_streams:
        start_seconds, end_seconds = _stream_time_seconds(stream)
        if start_seconds <= match_seconds < end_seconds:
            time_matches.append(stream)

    linked_seconds = set(entry["frame_seconds"])
    if entry["video_start_offset_seconds"] is not None:
        linked_seconds.add(entry["video_start_offset_seconds"])
    offset_matches = []
    streams_by_day_mat = {}
    for stream in candidate_streams:
        streams_by_day_mat.setdefault(
            (stream.event_id, stream.day_number, stream.mat_number), []
        ).append(stream)
    for stream in candidate_streams:
        related_streams = streams_by_day_mat[
            (stream.event_id, stream.day_number, stream.mat_number)
        ]
        if any(
            _stream_contains_video_second(stream, related_streams, video_second)
            for video_second in linked_seconds
        ):
            offset_matches.append(stream)

    matched_streams = {stream.id: stream for stream in [*time_matches, *offset_matches]}
    if matched_streams:
        # Conflicting schedule/offset evidence fails closed rather than exposing a
        # segment that an administrator marked hidden.
        return all(not stream.hide_all for stream in matched_streams.values())

    visibility_values = {stream.hide_all for stream in candidate_streams}
    if len(visibility_values) == 1:
        return not visibility_values.pop()
    return False


def load_linked_archive_video_links(session, match_ids=None):
    """Return segment-visible YouTube archive links for OCR-linked matches."""
    query = (
        session.query(
            LivestreamFrameTextEvent.match_id,
            Event.ibjjf_id,
            Match.happened_at,
            Match.match_location,
            Match.video_start_offset_seconds,
            LivestreamFrameArchive.youtube_video_id,
            LivestreamFrameArchive.canonical_url,
            func.min(LivestreamFrameTextEvent.frame_second),
        )
        .select_from(LivestreamFrameTextEvent)
        .join(Match, Match.id == LivestreamFrameTextEvent.match_id)
        .join(Event, Event.id == Match.event_id)
        .join(
            LivestreamFrameArchive,
            LivestreamFrameArchive.id == LivestreamFrameTextEvent.archive_id,
        )
        .filter(LivestreamFrameTextEvent.match_id.isnot(None))
    )
    if match_ids is not None:
        match_ids = [
            match_id if isinstance(match_id, uuid.UUID) else uuid.UUID(str(match_id))
            for match_id in match_ids
        ]
        if not match_ids:
            return {}
        query = query.filter(LivestreamFrameTextEvent.match_id.in_(match_ids))

    rows = (
        query.group_by(
            LivestreamFrameTextEvent.match_id,
            Event.ibjjf_id,
            Match.happened_at,
            Match.match_location,
            Match.video_start_offset_seconds,
            LivestreamFrameArchive.youtube_video_id,
            LivestreamFrameArchive.canonical_url,
        )
        .order_by(
            LivestreamFrameTextEvent.match_id,
            LivestreamFrameArchive.youtube_video_id,
        )
        .all()
    )
    if not rows:
        return {}

    entries = {}
    for (
        match_id,
        event_id,
        happened_at,
        match_location,
        offset_seconds,
        youtube_video_id,
        canonical_url,
        frame_second,
    ) in rows:
        entry = entries.setdefault(
            (match_id, youtube_video_id),
            {
                "match_id": match_id,
                "event_id": event_id,
                "happened_at": happened_at,
                "match_location": match_location,
                "video_start_offset_seconds": offset_seconds,
                "youtube_video_id": youtube_video_id,
                "canonical_url": canonical_url,
                "frame_seconds": [],
            },
        )
        entry["frame_seconds"].append(frame_second)

    event_ids = {entry["event_id"] for entry in entries.values()}
    event_start_dates = {
        event_id: happened_at
        for event_id, happened_at in session.query(
            Event.ibjjf_id, func.min(Match.happened_at)
        )
        .join(Match, Match.event_id == Event.id)
        .filter(Event.ibjjf_id.in_(event_ids))
        .group_by(Event.ibjjf_id)
        .all()
    }
    streams_by_archive_key = {}
    for stream in (
        session.query(LiveStream)
        .filter(LiveStream.event_id.in_(event_ids))
        .order_by(
            LiveStream.event_id,
            LiveStream.day_number,
            LiveStream.mat_number,
            LiveStream.start_hour,
            LiveStream.start_minute,
            LiveStream.start_seconds,
        )
        .all()
    ):
        youtube_video_id = extract_youtube_video_id(stream.link)
        if youtube_video_id is not None:
            streams_by_archive_key.setdefault(
                (stream.event_id, youtube_video_id), []
            ).append(stream)

    links_by_match_id = {}
    for entry in entries.values():
        streams = streams_by_archive_key.get(
            (entry["event_id"], entry["youtube_video_id"]), []
        )
        if not streams or not _linked_archive_segment_is_visible(
            entry,
            streams,
            event_start_dates.get(entry["event_id"]),
        ):
            continue
        link = _youtube_url_with_offset(
            entry["canonical_url"], entry["video_start_offset_seconds"]
        )
        if link is not None:
            links_by_match_id.setdefault(entry["match_id"], link)
    return links_by_match_id


def _load_special_search_names(session):
    return {
        athlete_name: search_name
        for athlete_name, search_name in session.execute(
            text(
                """
            SELECT athlete_name, search_name
            FROM flo_search_names
            """
            )
        )
    }


def load_livestream_links(session, event_ids, registrations=False):
    tournament_days = {}
    tournament_end_days = {}

    # Build parameterized IN clause for event_ids
    event_id_params = {f"eid_{i}": eid for i, eid in enumerate(event_ids)}
    event_id_placeholders = ", ".join([f":eid_{i}" for i in range(len(event_ids))])

    if registrations:
        event_results = session.execute(
            text(
                f"""
            SELECT r.event_id, r.event_start_date, r.event_end_date
            FROM registration_links r
            WHERE r.event_id IN ({event_id_placeholders})
            """
            ),
            event_id_params,
        )
        for ibjjf_id, start_date, end_date in event_results:
            start_date_date = start_date
            if isinstance(start_date, str):
                start_date_date = datetime.fromisoformat(start_date)
            tournament_days[ibjjf_id] = start_date_date.date()
            if end_date is not None:
                end_date_date = end_date
                if isinstance(end_date, str):
                    end_date_date = datetime.fromisoformat(end_date)
                tournament_end_days[ibjjf_id] = end_date_date.date()
    else:
        event_results = session.execute(
            text(
                f"""
            SELECT e.ibjjf_id, MIN(m.happened_at) AS min_date
            FROM events e
            JOIN matches m ON e.id = m.event_id
            WHERE e.ibjjf_id IN ({event_id_placeholders})
            GROUP BY e.ibjjf_id
            """
            ),
            event_id_params,
        )
        for ibjjf_id, min_date in event_results:
            min_date_date = min_date
            if isinstance(min_date, str):
                min_date_date = datetime.fromisoformat(min_date)
            tournament_days[ibjjf_id] = min_date_date.date()

    live_streams = {}
    for (
        event_id,
        day_number,
        mat_number,
        link,
        start_hour,
        start_minute,
        start_seconds,
        end_hour,
        end_minute,
        drift_factor,
        hide_all,
    ) in session.execute(
        text(
            f"""
        SELECT event_id, day_number, mat_number, link, start_hour, start_minute, start_seconds, end_hour, end_minute, drift_factor, hide_all
        FROM live_streams
        WHERE event_id IN ({event_id_placeholders})
        ORDER BY event_id, day_number, mat_number, start_hour, start_minute, start_seconds
        """
        ),
        event_id_params,
    ):
        live_streams.setdefault((event_id, day_number, mat_number), []).append(
            (
                link,
                start_hour,
                start_minute,
                start_seconds,
                end_hour,
                end_minute,
                drift_factor,
                hide_all,
            )
        )

    flo_event_tags = {
        event_id: tag
        for event_id, tag in session.execute(
            text(
                f"""
            SELECT event_id, tag
            FROM flo_event_tags
            WHERE event_id IN ({event_id_placeholders})
            """
            ),
            event_id_params,
        )
    }

    flo_mat_links = {}
    for ev_id, mat_number, link in session.execute(
        text(
            f"""
        SELECT event_id, mat_number, link
        FROM flo_mat_links
        WHERE event_id IN ({event_id_placeholders})
        """
        ),
        event_id_params,
    ):
        flo_mat_links[(ev_id, mat_number)] = link

    special_search_names = _load_special_search_names(session)

    return {
        "tournament_days": tournament_days,
        "tournament_end_days": tournament_end_days,
        "live_streams": live_streams,
        "flo_event_tags": flo_event_tags,
        "flo_mat_links": flo_mat_links,
        "special_search_names": special_search_names,
    }


def name_components(name):
    return [
        n
        for n in normalize(name.strip()).split()
        if n.lower() not in ["jr.", "sr.", "jr", "sr", "2nd", "3rd", "ii", "iii"]
        and not n.startswith('"')
        and len(n.replace(".", "")) > 1
    ]


def without_nicknames(name):
    return re.sub(r'"[^"]*"', "", name).strip()


def regular_search_name(name):
    names = name_components(name)
    if len(name) > 32:
        # use first two names only to avoid cutoff
        return " ".join(names[:2])
    else:
        # use first and last name
        return " ".join([names[0], names[-1]])


def is_quarterfinal_or_above(division_size, match_number):
    if division_size is None or match_number is None:
        return False
    return division_size - match_number <= 6


def should_use_special_search_name(
    division_belt,
    division_age,
    division_size,
    match_number,
):
    return (
        division_belt == BLACK
        and division_age == ADULT
        and is_quarterfinal_or_above(division_size, match_number)
    )


def get_search_name(
    full_name,
    special_search_names,
    personal_name,
    use_special_search_name,
):
    if not use_special_search_name:
        return regular_search_name(full_name)
    if full_name in special_search_names:
        return special_search_names[full_name]
    if personal_name is not None:
        personal_name_without_nicknames = without_nicknames(personal_name)
        if personal_name_without_nicknames:
            return regular_search_name(personal_name_without_nicknames)
    return regular_search_name(full_name)


def get_livestream_link(
    livestream_links,
    ibjjf_id,
    winner_name,
    loser_name,
    happened_at_datetime,
    match_location,
    division_belt,
    division_age,
    division_size,
    match_number,
    winner_personal_name,
    loser_personal_name,
    video_link,
    video_start_offset_seconds,
):
    if isinstance(video_link, str) and video_link.lower() == "none":
        return video_link

    tournament_days = livestream_links["tournament_days"]
    live_streams = livestream_links["live_streams"]
    flo_event_tags = livestream_links["flo_event_tags"]
    special_search_names = livestream_links.get("special_search_names", {})
    livestream_link = None

    if ibjjf_id in flo_event_tags and winner_name and loser_name:
        tag = flo_event_tags[ibjjf_id]
        if winner_name and loser_name:
            use_special_search_name = should_use_special_search_name(
                division_belt,
                division_age,
                division_size,
                match_number,
            )
            winner_search_name = get_search_name(
                winner_name,
                special_search_names,
                winner_personal_name,
                use_special_search_name,
            )
            loser_search_name = get_search_name(
                loser_name,
                special_search_names,
                loser_personal_name,
                use_special_search_name,
            )
            livestream_link = (
                f"https://www.flograppling.com/events/{tag}/videos?"
                f"openInBrowser=1&search={quote(winner_search_name)}%20vs%20"
                f"{quote(loser_search_name)}"
            )
    elif len(live_streams):
        event_start_day = tournament_days.get(ibjjf_id)
        if event_start_day:
            match_day = happened_at_datetime.date()
            match_hour = happened_at_datetime.hour
            match_minute = happened_at_datetime.minute
            day_number = (match_day - event_start_day).days + 1
            mat_number = match_location
            mat_number_int = None
            if mat_number:
                try:
                    mat_number_int = int(mat_number.split()[-1])
                except ValueError:
                    mat_number_int = None
            if mat_number_int is not None:
                livestream_info_list = live_streams.get(
                    (ibjjf_id, day_number, mat_number_int)
                )
                if livestream_info_list:
                    for index, livestream_info in enumerate(livestream_info_list):
                        (
                            link,
                            start_hour,
                            start_minute,
                            start_seconds,
                            end_hour,
                            end_minute,
                            drift_factor,
                            hide_all,
                        ) = livestream_info

                        cut_seconds = 0
                        (
                            start_hour_with_link,
                            start_minute_with_link,
                            start_second_with_link,
                        ) = (start_hour, start_minute, start_seconds)
                        start_set = False
                        if index > 0:
                            for i in range(index):
                                (
                                    prevlink,
                                    lsh,
                                    lsm,
                                    lss,
                                    eh,
                                    em,
                                    _,
                                    _,
                                ) = livestream_info_list[i]
                                (
                                    _,
                                    sh,
                                    sm,
                                    ss,
                                    _,
                                    _,
                                    _,
                                    _,
                                ) = livestream_info_list[i + 1]

                                if prevlink == link:
                                    missing_seconds = (sh * 3600 + sm * 60 + ss) - (
                                        eh * 3600 + em * 60
                                    )
                                    cut_seconds += missing_seconds

                                    if not start_set:
                                        start_hour_with_link = lsh
                                        start_minute_with_link = lsm
                                        start_second_with_link = lss
                                        start_set = True

                        match_seconds = match_hour * 3600 + match_minute * 60
                        start_seconds_for_offset = (
                            start_hour_with_link * 3600
                            + start_minute_with_link * 60
                            + start_second_with_link
                        )
                        stream_start_seconds = (
                            start_hour * 3600 + start_minute * 60 + start_seconds
                        )
                        end_seconds = end_hour * 3600 + end_minute * 60

                        if (
                            match_seconds >= stream_start_seconds
                            and match_seconds < end_seconds
                        ):
                            if video_start_offset_seconds is not None:
                                time_offset_seconds = video_start_offset_seconds
                            else:
                                time_offset_seconds = (
                                    match_seconds
                                    - start_seconds_for_offset
                                    - cut_seconds
                                )

                            if time_offset_seconds <= 0:
                                time_offset_seconds = 1

                            if video_start_offset_seconds is None:
                                time_offset_seconds = round(
                                    time_offset_seconds * drift_factor
                                )

                            if not flo_event_tags.get(ibjjf_id):
                                if "?" in link:
                                    link += "&t=" + str(time_offset_seconds) + "s"
                                else:
                                    link += "#t=" + str(time_offset_seconds) + "s"

                            if hide_all:
                                livestream_link = None
                                break

                            livestream_link = link
                            break

    if (
        livestream_link
        and video_start_offset_seconds is not None
        and extract_youtube_video_id(livestream_link) is not None
        and "flograppling.com" not in livestream_link.lower()
    ):
        return livestream_link

    if video_link:
        return video_link

    return livestream_link
