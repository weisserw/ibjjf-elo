#!/usr/bin/env python3
"""Fetch IBJJF YouTube match uploads and match them to imported bracket matches."""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests
from sqlalchemy.orm import selectinload

from constants import ADULT, FEMALE, MALE, translate_belt, translate_weight
from models import Athlete, Event, Match, MatchParticipant, YoutubeMatchVideo

import medal_import_lib
import match_youtube_events


IBJJF_CHANNEL_ID = "UCuEclQFX1C12JpywNDNMHIg"
RSS_URL = "https://www.youtube.com/feeds/videos.xml"
CHANNEL_VIDEOS_URL = "https://www.youtube.com/@ibjjf/videos"
YOUTUBEI_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
YOUTUBE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}
TITLE_RE = re.compile(
    r"^\s*(?P<a>.+?)\s+v(?:s\.?|ersus)\s+(?P<b>.+?)\s*/\s*(?P<event>.+?)\s*$", re.I
)
ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"
RELATIVE_TIME_RE = re.compile(
    r"\b(?P<count>a|an|\d+)\s+" r"(?P<unit>minute|hour|day|week|month|year)s?\s+ago\b",
    re.I,
)


@dataclass(frozen=True)
class YoutubeUpload:
    youtube_video_id: str
    url: str
    title: str
    description: str | None
    published_at: datetime | None
    updated_at: datetime | None
    thumbnail_url: str | None


@dataclass(frozen=True)
class ParsedYoutubeTitle:
    athlete1: str
    athlete2: str
    event_name: str


@dataclass(frozen=True)
class ParsedYoutubeDivision:
    age: str | None
    belt: str | None
    gender: str | None
    weight: str | None
    round_name: str | None


@dataclass(frozen=True)
class MatchCandidate:
    match: Match
    score: float
    score_gap: float
    athlete1_score: int
    athlete2_score: int
    direction: str
    reason: str


def _utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _utc_naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_youtube_match_title(title: str) -> ParsedYoutubeTitle | None:
    match = TITLE_RE.match(title or "")
    if not match:
        return None
    athlete1 = match.group("a").strip()
    athlete2 = match.group("b").strip()
    event_name = match.group("event").strip()
    if not athlete1 or not athlete2 or not event_name:
        return None
    return ParsedYoutubeTitle(
        athlete1=athlete1, athlete2=athlete2, event_name=event_name
    )


def _title_case_token(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def parse_youtube_division_description(
    description: str | None,
) -> ParsedYoutubeDivision:
    if not description:
        return ParsedYoutubeDivision(None, None, None, None, None)

    first_line = description.strip().splitlines()[0].strip()
    parts = [part.strip() for part in first_line.split("/")]
    if len(parts) < 4:
        return ParsedYoutubeDivision(None, None, None, None, None)

    age = None
    belt = None
    gender = None
    weight = None
    round_name = None

    raw_weight = parts[3]
    if " - " in raw_weight:
        raw_weight, round_name = [piece.strip() for piece in raw_weight.split(" - ", 1)]

    try:
        age = (
            ADULT
            if parts[0].strip().upper() == "ADULT"
            else _title_case_token(parts[0])
        )
        belt_token = parts[1].upper().replace("-BELT", "").replace(" BELT", "")
        belt = translate_belt(belt_token)
        gender_token = parts[2].strip().upper()
        if gender_token == "MALE":
            gender = MALE
        elif gender_token == "FEMALE":
            gender = FEMALE
        weight = translate_weight(_title_case_token(raw_weight))
    except ValueError:
        pass

    return ParsedYoutubeDivision(age, belt, gender, weight, round_name)


def parse_rss_uploads_xml(xml_content: bytes | str) -> list[YoutubeUpload]:
    root = ET.fromstring(xml_content)
    uploads = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        video_id = (entry.findtext(f"{YT_NS}videoId") or "").strip()
        title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
        link_el = entry.find(f"{ATOM_NS}link")
        url = (link_el.attrib.get("href") if link_el is not None else "") or ""
        group = entry.find(f"{MEDIA_NS}group")
        description = None
        thumbnail_url = None
        if group is not None:
            description = group.findtext(f"{MEDIA_NS}description")
            thumb_el = group.find(f"{MEDIA_NS}thumbnail")
            if thumb_el is not None:
                thumbnail_url = thumb_el.attrib.get("url")
        if video_id and title and url:
            uploads.append(
                YoutubeUpload(
                    youtube_video_id=video_id,
                    url=url,
                    title=title,
                    description=description,
                    published_at=_parse_datetime(entry.findtext(f"{ATOM_NS}published")),
                    updated_at=_parse_datetime(entry.findtext(f"{ATOM_NS}updated")),
                    thumbnail_url=thumbnail_url,
                )
            )
    return uploads


def _extract_json_after_marker(html: str, marker: str) -> dict:
    marker_index = html.find(marker)
    if marker_index < 0:
        return {}

    start = html.find("{", marker_index)
    if start < 0:
        return {}

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                import json

                return json.loads(html[start : index + 1])
    return {}


def _iter_values_with_key(value, key: str):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for child in value.values():
            yield from _iter_values_with_key(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_values_with_key(child, key)


def _text_content(value) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("content"), str):
        return value["content"]
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    runs = value.get("runs")
    if isinstance(runs, list):
        return "".join(run.get("text", "") for run in runs if isinstance(run, dict))
    return ""


def _youtubei_config(html: str) -> tuple[str, str, str]:
    api_key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
    client_name_match = re.search(r'"INNERTUBE_CLIENT_NAME":"([^"]+)"', html)
    client_version_match = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
    api_key = api_key_match.group(1) if api_key_match else None
    client_name = client_name_match.group(1) if client_name_match else None
    client_version = client_version_match.group(1) if client_version_match else None
    if not api_key or not client_name or not client_version:
        raise ValueError("Could not find YouTube innertube config")
    return api_key, client_name, client_version


def _lockup_url(lockup: dict, video_id: str) -> str:
    command = (
        lockup.get("rendererContext", {})
        .get("commandContext", {})
        .get("onTap", {})
        .get("innertubeCommand", {})
    )
    metadata = command.get("commandMetadata", {}).get("webCommandMetadata", {})
    url = metadata.get("url")
    if isinstance(url, str) and url:
        if url.startswith("http"):
            return url
        return f"https://www.youtube.com{url}"
    return f"https://www.youtube.com/watch?v={video_id}"


def _lockup_thumbnail_url(lockup: dict) -> str | None:
    sources = (
        lockup.get("contentImage", {})
        .get("thumbnailViewModel", {})
        .get("image", {})
        .get("sources", [])
    )
    if not isinstance(sources, list) or not sources:
        return None
    sorted_sources = sorted(
        (
            source
            for source in sources
            if isinstance(source, dict) and source.get("url")
        ),
        key=lambda source: source.get("width", 0),
    )
    if not sorted_sources:
        return None
    return sorted_sources[-1].get("url")


def _relative_published_at(value: str, now: datetime) -> datetime | None:
    match = RELATIVE_TIME_RE.search(value or "")
    if not match:
        return None
    count_token = match.group("count").lower()
    count = 1 if count_token in ("a", "an") else int(count_token)
    unit = match.group("unit").lower()
    if unit == "minute":
        delta = timedelta(minutes=count)
    elif unit == "hour":
        delta = timedelta(hours=count)
    elif unit == "day":
        delta = timedelta(days=count)
    elif unit == "week":
        delta = timedelta(weeks=count)
    elif unit == "month":
        delta = timedelta(days=30 * count)
    elif unit == "year":
        delta = timedelta(days=365 * count)
    else:
        return None
    return now - delta


def _lockup_published_at(lockup: dict, now: datetime) -> datetime | None:
    metadata_rows = (
        lockup.get("metadata", {})
        .get("lockupMetadataViewModel", {})
        .get("metadata", {})
        .get("contentMetadataViewModel", {})
        .get("metadataRows", [])
    )
    if not isinstance(metadata_rows, list):
        return None
    for row in metadata_rows:
        for part in row.get("metadataParts", []):
            text = _text_content(part.get("text"))
            published_at = _relative_published_at(text, now)
            if published_at is not None:
                return published_at
            label = part.get("accessibilityLabel")
            published_at = _relative_published_at(label, now)
            if published_at is not None:
                return published_at
    return None


def _continuation_token(data: dict, seen_tokens: set[str]) -> str | None:
    for command in _iter_values_with_key(data, "continuationCommand"):
        if not isinstance(command, dict):
            continue
        token = command.get("token")
        if token and token not in seen_tokens:
            return token
    return None


def parse_channel_uploads_data(
    data: dict, *, now: datetime | None = None
) -> list[YoutubeUpload]:
    now = now or datetime.utcnow()
    uploads = []
    seen_video_ids = set()
    for lockup in _iter_values_with_key(data, "lockupViewModel"):
        if not isinstance(lockup, dict):
            continue
        if lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            continue
        video_id = lockup.get("contentId")
        if not isinstance(video_id, str) or not video_id or video_id in seen_video_ids:
            continue
        title = _text_content(
            lockup.get("metadata", {}).get("lockupMetadataViewModel", {}).get("title")
        ).strip()
        if not title:
            continue
        seen_video_ids.add(video_id)
        uploads.append(
            YoutubeUpload(
                youtube_video_id=video_id,
                url=_lockup_url(lockup, video_id),
                title=title,
                description=None,
                published_at=_lockup_published_at(lockup, now),
                updated_at=None,
                thumbnail_url=_lockup_thumbnail_url(lockup),
            )
        )
    return uploads


def fetch_rss_uploads(
    *,
    channel_id: str = IBJJF_CHANNEL_ID,
    timeout: int = 20,
) -> list[YoutubeUpload]:
    response = requests.get(
        RSS_URL,
        params={"channel_id": channel_id},
        headers=YOUTUBE_REQUEST_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_rss_uploads_xml(response.content)


def fetch_channel_uploads(
    *,
    max_pages: int = 4,
    timeout: int = 20,
    now: datetime | None = None,
) -> list[YoutubeUpload]:
    now = now or datetime.utcnow()
    response = requests.get(
        CHANNEL_VIDEOS_URL, headers=YOUTUBE_REQUEST_HEADERS, timeout=timeout
    )
    response.raise_for_status()
    html = response.text
    api_key, client_name, client_version = _youtubei_config(html)
    data = _extract_json_after_marker(html, "var ytInitialData =")

    uploads = []
    seen_video_ids = set()
    seen_tokens = set()

    for page_index in range(max_pages):
        for upload in parse_channel_uploads_data(data, now=now):
            if upload.youtube_video_id in seen_video_ids:
                continue
            seen_video_ids.add(upload.youtube_video_id)
            uploads.append(upload)

        if page_index >= max_pages - 1:
            break
        token = _continuation_token(data, seen_tokens)
        if not token:
            break
        seen_tokens.add(token)
        payload = {
            "context": {
                "client": {
                    "clientName": client_name,
                    "clientVersion": client_version,
                }
            },
            "continuation": token,
        }
        response = requests.post(
            f"{YOUTUBEI_BROWSE_URL}?key={api_key}",
            headers={**YOUTUBE_REQUEST_HEADERS, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

    return uploads


def upsert_youtube_match_videos(
    session,
    uploads: Iterable[YoutubeUpload],
    *,
    scraped_at: datetime | None = None,
) -> tuple[int, int]:
    scraped_at = scraped_at or datetime.utcnow()
    uploads = list(uploads)
    if not uploads:
        return 0, 0

    existing = {
        row.youtube_video_id: row
        for row in session.query(YoutubeMatchVideo)
        .filter(
            YoutubeMatchVideo.youtube_video_id.in_(
                [upload.youtube_video_id for upload in uploads]
            )
        )
        .all()
    }

    inserted = 0
    updated = 0
    for upload in uploads:
        row = existing.get(upload.youtube_video_id)
        if row is None:
            row = YoutubeMatchVideo(
                youtube_video_id=upload.youtube_video_id,
                url=upload.url,
                title=upload.title,
                description=upload.description,
                published_at=upload.published_at,
                updated_at=upload.updated_at,
                thumbnail_url=upload.thumbnail_url,
                scraped_at=scraped_at,
            )
            session.add(row)
            inserted += 1
        else:
            row.url = upload.url
            row.title = upload.title
            if upload.description is None:
                if row.description is None:
                    row.description = upload.description
                if row.published_at is None:
                    row.published_at = upload.published_at
                if row.updated_at is None:
                    row.updated_at = upload.updated_at
                if row.thumbnail_url is None:
                    row.thumbnail_url = upload.thumbnail_url
            else:
                row.description = upload.description
                row.published_at = upload.published_at
                row.updated_at = upload.updated_at
                row.thumbnail_url = upload.thumbnail_url
            row.scraped_at = scraped_at
            updated += 1
    session.commit()
    return inserted, updated


def _merge_uploads_prefer_rich_metadata(
    upload_lists: Iterable[Iterable[YoutubeUpload]],
) -> list[YoutubeUpload]:
    uploads_by_id: dict[str, YoutubeUpload] = {}
    order: list[str] = []
    for uploads in upload_lists:
        for upload in uploads:
            existing = uploads_by_id.get(upload.youtube_video_id)
            if existing is None:
                uploads_by_id[upload.youtube_video_id] = upload
                order.append(upload.youtube_video_id)
            elif upload.description is not None:
                uploads_by_id[upload.youtube_video_id] = upload
    return [uploads_by_id[video_id] for video_id in order]


def update_youtube_match_videos(
    session, *, source: str = "auto", max_pages: int = 2
) -> tuple[int, int]:
    if source == "auto":
        uploads = _merge_uploads_prefer_rich_metadata(
            [fetch_channel_uploads(max_pages=max_pages), fetch_rss_uploads()]
        )
    elif source == "rss":
        uploads = fetch_rss_uploads()
    elif source == "channel":
        uploads = fetch_channel_uploads(max_pages=max_pages)
    else:
        raise ValueError(f"Unsupported YouTube source: {source}")
    match_uploads = [
        upload
        for upload in uploads
        if parse_youtube_match_title(upload.title) is not None
    ]
    return upsert_youtube_match_videos(session, match_uploads)


def _event_candidates(session) -> list[tuple[Event, match_youtube_events.ParsedEvent]]:
    events = (
        session.query(Event)
        .filter(Event.ibjjf_id.isnot(None))
        .order_by(Event.name)
        .all()
    )
    return [(event, match_youtube_events.parse_event(event.name)) for event in events]


def match_event(
    parsed_title: ParsedYoutubeTitle,
    event_candidates: list[tuple[Event, match_youtube_events.ParsedEvent]],
) -> tuple[Event | None, float, float, str, list[tuple[Event, float]]]:
    parsed_event = match_youtube_events.parse_event(parsed_title.event_name)
    scored = sorted(
        (
            (match_youtube_events.pair_score(parsed_event, candidate), event)
            for event, candidate in event_candidates
            if parsed_event.year is None
            or candidate.year == parsed_event.year
            or candidate.year is None
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored:
        return None, 0.0, 0.0, "no_year_candidates", []

    top_score, top_event = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    gap = top_score - second_score
    alternatives = [(event, round(score, 2)) for score, event in scored[:5]]
    if top_score >= 90.0 and gap >= 6.0:
        return top_event, round(top_score, 2), round(gap, 2), "event_auto", alternatives
    if top_score >= 84.0 and gap >= 12.0:
        return top_event, round(top_score, 2), round(gap, 2), "event_auto", alternatives
    return top_event, round(top_score, 2), round(gap, 2), "event_review", alternatives


def _athlete_score(youtube_name: str, athlete: Athlete) -> int:
    scores = [medal_import_lib.name_score(youtube_name, athlete.name)]
    if athlete.personal_name:
        scores.append(medal_import_lib.name_score(youtube_name, athlete.personal_name))
    return max(scores)


def _pair_score(
    parsed_title: ParsedYoutubeTitle, participants: list[MatchParticipant]
) -> tuple[float, int, int, str]:
    left, right = participants
    direct_a = _athlete_score(parsed_title.athlete1, left.athlete)
    direct_b = _athlete_score(parsed_title.athlete2, right.athlete)
    reverse_a = _athlete_score(parsed_title.athlete1, right.athlete)
    reverse_b = _athlete_score(parsed_title.athlete2, left.athlete)

    direct = (direct_a + direct_b) / 2.0
    reverse = (reverse_a + reverse_b) / 2.0
    if reverse > direct:
        return reverse, reverse_a, reverse_b, "reverse"
    return direct, direct_a, direct_b, "direct"


def _division_matches(match: Match, parsed_division: ParsedYoutubeDivision) -> bool:
    division = match.division
    if parsed_division.age and division.age != parsed_division.age:
        return False
    if parsed_division.belt and division.belt != parsed_division.belt:
        return False
    if parsed_division.gender and division.gender != parsed_division.gender:
        return False
    if parsed_division.weight and division.weight != parsed_division.weight:
        return False
    return True


def match_video_to_matches(
    session,
    video: YoutubeMatchVideo,
    event: Event,
    parsed_title: ParsedYoutubeTitle,
    parsed_division: ParsedYoutubeDivision,
) -> list[MatchCandidate]:
    matches = (
        session.query(Match)
        .options(
            selectinload(Match.participants).selectinload(MatchParticipant.athlete),
            selectinload(Match.division),
        )
        .filter(Match.event_id == event.id)
        .order_by(Match.happened_at.desc(), Match.id)
        .all()
    )
    if any(
        [
            parsed_division.age,
            parsed_division.belt,
            parsed_division.gender,
            parsed_division.weight,
        ]
    ):
        matches = [
            match for match in matches if _division_matches(match, parsed_division)
        ]

    scored = []
    for match in matches:
        participants = list(match.participants)
        if len(participants) != 2:
            continue
        score, a_score, b_score, direction = _pair_score(parsed_title, participants)
        scored.append((score, match, a_score, b_score, direction))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []

    second_score = scored[1][0] if len(scored) > 1 else 0.0
    candidates = []
    for score, match, a_score, b_score, direction in scored[:5]:
        gap = score - second_score if match.id == scored[0][1].id else 0.0
        reason = "name_pair"
        if match.video_link == video.url or video.imported_match_id == match.id:
            reason = "already_imported"
        elif match.video_link:
            reason = "target_has_video_link"
        candidates.append(
            MatchCandidate(
                match=match,
                score=round(score, 2),
                score_gap=round(gap, 2),
                athlete1_score=a_score,
                athlete2_score=b_score,
                direction=direction,
                reason=reason,
            )
        )
    return candidates


def scan_youtube_match_videos(
    session,
    since: datetime,
    until: datetime,
) -> list[dict]:
    event_candidates = _event_candidates(session)
    videos = (
        session.query(YoutubeMatchVideo)
        .filter(YoutubeMatchVideo.ignored.isnot(True))
        .filter(YoutubeMatchVideo.published_at >= since)
        .filter(YoutubeMatchVideo.published_at <= until)
        .order_by(YoutubeMatchVideo.published_at.desc(), YoutubeMatchVideo.title)
        .all()
    )
    entries = []
    for video in videos:
        parsed_title = parse_youtube_match_title(video.title)
        parsed_division = parse_youtube_division_description(video.description)
        if parsed_title is None:
            entries.append(
                {
                    "video": video,
                    "status": "unparseable",
                    "parsed_title": None,
                    "parsed_division": parsed_division,
                    "event": None,
                    "event_score": 0.0,
                    "event_gap": 0.0,
                    "event_alternatives": [],
                    "matched_candidate": None,
                    "alternatives": [],
                }
            )
            continue

        event, event_score, event_gap, event_reason, event_alternatives = match_event(
            parsed_title, event_candidates
        )
        if event is None or event_reason != "event_auto":
            entries.append(
                {
                    "video": video,
                    "status": "no_event" if event is None else "event_review",
                    "parsed_title": parsed_title,
                    "parsed_division": parsed_division,
                    "event": event,
                    "event_score": event_score,
                    "event_gap": event_gap,
                    "event_alternatives": event_alternatives,
                    "matched_candidate": None,
                    "alternatives": [],
                }
            )
            continue

        alternatives = match_video_to_matches(
            session, video, event, parsed_title, parsed_division
        )
        top = alternatives[0] if alternatives else None
        status = "no_match"
        if top:
            if top.reason == "already_imported":
                status = "already_imported"
            elif top.reason == "target_has_video_link":
                status = "conflict"
            elif (
                top.score >= 90.0
                and top.score_gap >= 8.0
                and min(top.athlete1_score, top.athlete2_score) >= 78
            ):
                status = "matched"
            elif top.score >= 75.0:
                status = "ambiguous"

        entries.append(
            {
                "video": video,
                "status": status,
                "parsed_title": parsed_title,
                "parsed_division": parsed_division,
                "event": event,
                "event_score": event_score,
                "event_gap": event_gap,
                "event_alternatives": event_alternatives,
                "matched_candidate": (
                    top
                    if status in ("matched", "already_imported", "conflict")
                    else None
                ),
                "alternatives": alternatives,
            }
        )
    return entries


def import_youtube_match_video_links(
    session,
    selections: Iterable[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[int, int, list[str]]:
    imported = 0
    skipped = 0
    errors: list[str] = []
    selections = list(selections)
    if not selections:
        return imported, skipped, errors

    video_ids = list({video_id for video_id, _ in selections})
    match_ids = list({match_id for _, match_id in selections})
    videos_by_id = {
        video.id: video
        for video in session.query(YoutubeMatchVideo)
        .filter(YoutubeMatchVideo.id.in_(video_ids))
        .all()
    }
    matches_by_id = {
        match.id: match
        for match in session.query(Match).filter(Match.id.in_(match_ids)).all()
    }
    now = datetime.utcnow()

    for video_id, match_id in selections:
        video = videos_by_id.get(video_id)
        match = matches_by_id.get(match_id)
        if video is None or match is None:
            skipped += 1
            errors.append(f"Missing video or match for selection {video_id}:{match_id}")
            continue
        if match.video_link and match.video_link != video.url:
            skipped += 1
            errors.append(f"Match {match.id} already has a different video link.")
            continue
        match.video_link = video.url
        video.imported_match_id = match.id
        video.imported_at = now
        video.ignored = False
        imported += 1

    session.commit()
    return imported, skipped, errors
