from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from models import (
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    Match,
    RegistrationLink,
)
from youtube_utils import canonical_youtube_url, extract_youtube_video_id


ARCHIVE_STATUSES = (
    "pending",
    "probing",
    "ready",
    "queued",
    "running",
    "partial",
    "success",
    "error",
    "cancelled",
)
DEFAULT_ERROR_RETRY_BACKOFF_SECONDS = 300
DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS = 600
DEFAULT_FRESH_SEGMENTS_PER_ERROR_RETRY = 3


def error_retry_backoff_seconds(
    attempt_count: int | None = None,
    base_seconds: int = DEFAULT_ERROR_RETRY_BACKOFF_SECONDS,
    max_seconds: int = DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS,
) -> int:
    """Return one randomized archive retry delay.

    ``attempt_count`` remains accepted for worker/API compatibility, but capture
    retries no longer grow exponentially by segment attempt.
    """
    del attempt_count
    if base_seconds <= 0:
        return 0
    minimum = int(base_seconds)
    maximum = int(max_seconds) if max_seconds > 0 else minimum
    maximum = max(maximum, minimum)
    return random.randint(minimum, maximum)


def error_segment_retry_ready(
    segment: LivestreamFrameCaptureSegment,
    now: datetime | None = None,
    base_seconds: int = DEFAULT_ERROR_RETRY_BACKOFF_SECONDS,
    max_seconds: int = DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS,
) -> bool:
    if segment.status != "error":
        return False
    now = now or datetime.utcnow()
    retry_at = segment.archive.capture_retry_at
    if retry_at is not None:
        return retry_at <= now
    if base_seconds <= 0 or not segment.finished_at:
        return True
    # Backward compatibility for failures created before capture_retry_at existed
    # or by an older worker during a rolling deployment.
    return segment.finished_at + timedelta(seconds=base_seconds) <= now


def mark_capture_segment_error(
    session,
    segment: LivestreamFrameCaptureSegment,
    error: str,
    retry_delay_seconds: int | None = None,
    now: datetime | None = None,
) -> None:
    now = now or datetime.utcnow()
    if retry_delay_seconds is None:
        retry_delay_seconds = error_retry_backoff_seconds()
    retry_delay_seconds = max(int(retry_delay_seconds), 0)
    segment.status = "error"
    segment.last_error = error
    segment.finished_at = now
    segment.archive.last_error = error
    segment.archive.capture_retry_at = now + timedelta(seconds=retry_delay_seconds)
    recompute_archive_status(session, segment.archive)


SEGMENT_STATUSES = (
    "pending",
    "queued",
    "running",
    "success",
    "error",
    "cancelled",
    "skipped",
)
DEFAULT_SEGMENT_SECONDS = 3600
DEFAULT_FRAME_RATE = 1.0
DEFAULT_IMAGE_FORMAT = "jpg"


@dataclass(frozen=True)
class LivestreamUsage:
    stream: LiveStream
    youtube_video_id: str
    event_name: str | None
    event_date: datetime | None


def s3_prefix_for_youtube_id(youtube_video_id: str) -> str:
    return f"livestream-frames/{youtube_video_id}/"


def batch_s3_prefix_for_youtube_id(youtube_video_id: str) -> str:
    return f"livestream-frame-batches/{youtube_video_id}/"


def batch_s3_key(
    archive: LivestreamFrameArchive, segment: LivestreamFrameCaptureSegment
) -> str:
    return (
        f"{batch_s3_prefix_for_youtube_id(archive.youtube_video_id)}"
        f"{segment.start_second:09d}-{segment.end_second:09d}.tgz"
    )


def expected_frame_count(
    duration_seconds: int | None, frame_rate: float | None
) -> int | None:
    if duration_seconds is None:
        return None
    return int(math.ceil(duration_seconds * (frame_rate or DEFAULT_FRAME_RATE)))


def discover_livestream_usages(session) -> dict[str, list[LivestreamUsage]]:
    streams = LiveStream.query.order_by(
        LiveStream.event_id, LiveStream.day_number, LiveStream.mat_number
    ).all()
    event_ids = sorted({stream.event_id for stream in streams if stream.event_id})
    events_by_id = {
        event.ibjjf_id: event.name
        for event in Event.query.filter(Event.ibjjf_id.in_(event_ids)).all()
    }
    event_dates_by_id = {
        ibjjf_id: min_happened_at
        for ibjjf_id, min_happened_at in session.query(
            Event.ibjjf_id, func.min(Match.happened_at)
        )
        .join(Match, Match.event_id == Event.id)
        .filter(Event.ibjjf_id.in_(event_ids))
        .group_by(Event.ibjjf_id)
        .all()
    }
    registration_names_by_id = {}
    for registration_link in (
        RegistrationLink.query.filter(RegistrationLink.event_id.in_(event_ids))
        .order_by(RegistrationLink.event_id, RegistrationLink.updated_at.desc())
        .all()
    ):
        if registration_link.event_id:
            registration_names_by_id.setdefault(
                registration_link.event_id, registration_link.name
            )
            if registration_link.event_start_date:
                event_dates_by_id.setdefault(
                    registration_link.event_id, registration_link.event_start_date
                )

    usages: dict[str, list[LivestreamUsage]] = {}
    for stream in streams:
        youtube_video_id = extract_youtube_video_id(stream.link)
        if not youtube_video_id:
            continue
        usages.setdefault(youtube_video_id, []).append(
            LivestreamUsage(
                stream=stream,
                youtube_video_id=youtube_video_id,
                event_name=events_by_id.get(stream.event_id)
                or registration_names_by_id.get(stream.event_id),
                event_date=event_dates_by_id.get(stream.event_id),
            )
        )
    return usages


def get_or_create_archive(
    session, youtube_video_id: str
) -> tuple[LivestreamFrameArchive, bool]:
    archive = LivestreamFrameArchive.query.filter_by(
        youtube_video_id=youtube_video_id
    ).one_or_none()
    if archive:
        return archive, False

    archive = LivestreamFrameArchive(
        youtube_video_id=youtube_video_id,
        canonical_url=canonical_youtube_url(youtube_video_id),
        s3_prefix=s3_prefix_for_youtube_id(youtube_video_id),
        status="pending",
        frame_rate=DEFAULT_FRAME_RATE,
        image_format=DEFAULT_IMAGE_FORMAT,
        uploaded_frame_count=0,
    )
    session.add(archive)
    return archive, True


def sync_archives_from_livestreams(session) -> dict[str, int]:
    usages = discover_livestream_usages(session)
    created = 0
    for youtube_video_id in sorted(usages):
        _, was_created = get_or_create_archive(session, youtube_video_id)
        if was_created:
            created += 1
    return {"created": created, "discovered": len(usages)}


def segment_ranges(
    duration_seconds: int, segment_seconds: int
) -> list[tuple[int, int]]:
    if duration_seconds <= 0:
        return []
    ranges = []
    start = 0
    while start < duration_seconds:
        end = min(start + segment_seconds, duration_seconds)
        ranges.append((start, end))
        start = end
    return ranges


def _uncovered_ranges(
    start_second: int, end_second: int, existing_ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    ranges = []
    cursor = start_second
    for existing_start, existing_end in existing_ranges:
        if existing_end <= cursor:
            continue
        if existing_start >= end_second:
            break
        if existing_start > cursor:
            ranges.append((cursor, min(existing_start, end_second)))
        cursor = max(cursor, existing_end)
        if cursor >= end_second:
            break
    if cursor < end_second:
        ranges.append((cursor, end_second))
    return ranges


def create_missing_segments(
    session,
    archive: LivestreamFrameArchive,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
) -> int:
    existing = sorted(
        (segment.start_second, segment.end_second)
        for segment in LivestreamFrameCaptureSegment.query.filter_by(
            archive_id=archive.id
        ).all()
    )

    if archive.duration_seconds is None:
        ranges = [(0, segment_seconds)]
    else:
        ranges = segment_ranges(archive.duration_seconds, segment_seconds)

    created = 0
    for start_second, end_second in ranges:
        for missing_start, missing_end in _uncovered_ranges(
            start_second, end_second, existing
        ):
            session.add(
                LivestreamFrameCaptureSegment(
                    archive_id=archive.id,
                    start_second=missing_start,
                    end_second=missing_end,
                    status="queued",
                    attempt_count=0,
                    uploaded_frame_count=0,
                )
            )
            existing.append((missing_start, missing_end))
            existing.sort()
            created += 1
    return created


def queue_archive_capture(
    session,
    archive: LivestreamFrameArchive,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    queue_requested_at: datetime | None = None,
) -> int:
    if archive.is_bad:
        raise ValueError("bad frame archives cannot be queued")
    created = create_missing_segments(session, archive, segment_seconds)
    requeued = (
        LivestreamFrameCaptureSegment.query.filter_by(archive_id=archive.id)
        .filter(
            LivestreamFrameCaptureSegment.status.in_(["pending", "error", "cancelled"])
        )
        .update({"status": "queued", "last_error": None}, synchronize_session=False)
    )
    archive.status = "queued"
    archive.capture_retry_at = None
    archive.queue_requested_at = queue_requested_at or datetime.utcnow()
    archive.last_error = None
    archive.completed_at = None
    archive.expected_frame_count = expected_frame_count(
        archive.duration_seconds, archive.frame_rate
    )
    return created + requeued


def retry_failed_segments(
    session, archive_ids: list | None = None, statuses: list[str] | None = None
) -> int:
    statuses = statuses or ["error", "cancelled"]
    query = (
        LivestreamFrameCaptureSegment.query.join(LivestreamFrameArchive)
        .filter(LivestreamFrameCaptureSegment.status.in_(statuses))
        .filter(LivestreamFrameArchive.is_bad.is_(False))
    )
    if archive_ids:
        query = query.filter(LivestreamFrameCaptureSegment.archive_id.in_(archive_ids))

    segments = query.all()
    affected_archive_ids = set(archive_ids or [])
    for segment in segments:
        affected_archive_ids.add(segment.archive_id)
        segment.status = "queued"
        segment.last_error = None
        segment.finished_at = None

    if affected_archive_ids:
        archives = LivestreamFrameArchive.query.filter(
            LivestreamFrameArchive.id.in_(affected_archive_ids)
        ).all()
        for archive in archives:
            archive.last_error = None
            archive.capture_retry_at = None
            recompute_archive_status(session, archive)
    return len(segments)


def requeue_completed_segments(session, archive: LivestreamFrameArchive) -> int:
    if archive.is_bad:
        raise ValueError("bad frame archives cannot be queued")
    segments = (
        LivestreamFrameCaptureSegment.query.filter_by(archive_id=archive.id)
        .filter(LivestreamFrameCaptureSegment.status.in_(["success", "skipped"]))
        .order_by(LivestreamFrameCaptureSegment.start_second)
        .all()
    )
    for segment in segments:
        segment.status = "queued"
        segment.uploaded_frame_count = 0
        segment.sampled_frame_count = 0
        segment.last_uploaded_second = None
        segment.batch_s3_key = None
        segment.batch_uploaded_at = None
        segment.started_at = None
        segment.finished_at = None
        segment.background_task_id = None
        segment.last_error = None

    if segments:
        archive.status = "queued"
        archive.uploaded_frame_count = 0
        archive.last_uploaded_second = None
        archive.last_error = None
        archive.completed_at = None
        archive.expected_frame_count = expected_frame_count(
            archive.duration_seconds, archive.frame_rate
        )
    return len(segments)


def cancel_queued_segments(
    session, archive_ids: list | None = None, statuses: list[str] | None = None
) -> int:
    statuses = statuses or ["pending", "queued", "running"]
    query = LivestreamFrameCaptureSegment.query.filter(
        LivestreamFrameCaptureSegment.status.in_(statuses)
    )
    if archive_ids:
        query = query.filter(LivestreamFrameCaptureSegment.archive_id.in_(archive_ids))

    segments = query.all()
    for segment in segments:
        segment.status = "cancelled"
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(session, segment.archive)
    return len(segments)


def claim_next_segment(
    session,
    archive_id=None,
    youtube_video_id: str | None = None,
    background_task_id=None,
    error_retry_backoff_seconds: int = DEFAULT_ERROR_RETRY_BACKOFF_SECONDS,
    max_error_retry_backoff_seconds: int = DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS,
    fresh_segments_per_error_retry: int = DEFAULT_FRESH_SEGMENTS_PER_ERROR_RETRY,
) -> LivestreamFrameCaptureSegment | None:
    error_retry_backoff_seconds = (
        DEFAULT_ERROR_RETRY_BACKOFF_SECONDS
        if error_retry_backoff_seconds is None
        else int(error_retry_backoff_seconds)
    )
    max_error_retry_backoff_seconds = (
        DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS
        if max_error_retry_backoff_seconds is None
        else int(max_error_retry_backoff_seconds)
    )
    fresh_segments_per_error_retry = (
        DEFAULT_FRESH_SEGMENTS_PER_ERROR_RETRY
        if fresh_segments_per_error_retry is None
        else max(int(fresh_segments_per_error_retry), 0)
    )
    base_query = (
        LivestreamFrameCaptureSegment.query.options(
            selectinload(LivestreamFrameCaptureSegment.archive)
        )
        .join(LivestreamFrameArchive)
        .filter(LivestreamFrameArchive.is_bad.is_(False))
    )
    if archive_id:
        base_query = base_query.filter(
            LivestreamFrameCaptureSegment.archive_id == archive_id
        )
    if youtube_video_id:
        base_query = base_query.filter(
            LivestreamFrameArchive.youtube_video_id == youtube_video_id
        )

    ordering = (
        func.coalesce(
            LivestreamFrameArchive.queue_requested_at,
            LivestreamFrameArchive.created_at,
        ),
        LivestreamFrameArchive.created_at,
        LivestreamFrameCaptureSegment.start_second,
        LivestreamFrameCaptureSegment.created_at,
    )
    now = datetime.utcnow()
    archives_with_errors = session.query(
        LivestreamFrameCaptureSegment.archive_id
    ).filter(LivestreamFrameCaptureSegment.status == "error")
    archives_with_running_segments = session.query(
        LivestreamFrameCaptureSegment.archive_id
    ).filter(LivestreamFrameCaptureSegment.status == "running")
    fresh_segment = (
        base_query.filter(
            LivestreamFrameCaptureSegment.status.in_(["pending", "queued"]),
            ~LivestreamFrameCaptureSegment.archive_id.in_(archives_with_errors),
            ~LivestreamFrameCaptureSegment.archive_id.in_(
                archives_with_running_segments
            ),
        )
        .order_by(*ordering)
        .first()
    )
    error_segments = (
        base_query.filter(
            LivestreamFrameCaptureSegment.status == "error",
            ~LivestreamFrameCaptureSegment.archive_id.in_(
                archives_with_running_segments
            ),
        )
        .order_by(*ordering)
        .all()
    )
    retry_segment = next(
        (
            error_segment
            for error_segment in error_segments
            if error_segment_retry_ready(
                error_segment,
                now=now,
                base_seconds=error_retry_backoff_seconds,
                max_seconds=max_error_retry_backoff_seconds,
            )
        ),
        None,
    )

    segment = fresh_segment or retry_segment
    if fresh_segment and retry_segment:
        # The persisted claim history is the scheduler state, so the retry share
        # survives worker restarts without a queue-size- or time-based heuristic.
        recent_claims = (
            base_query.filter(LivestreamFrameCaptureSegment.started_at.isnot(None))
            .order_by(
                LivestreamFrameCaptureSegment.started_at.desc(),
                LivestreamFrameCaptureSegment.created_at.desc(),
            )
            .limit(fresh_segments_per_error_retry)
            .all()
        )
        retry_quota_ready = fresh_segments_per_error_retry == 0 or (
            len(recent_claims) == fresh_segments_per_error_retry
            and all((recent.attempt_count or 0) <= 1 for recent in recent_claims)
        )
        segment = retry_segment if retry_quota_ready else fresh_segment
    if not segment:
        return None

    was_retry = segment.status == "error"
    segment.status = "running"
    segment.attempt_count = (segment.attempt_count or 0) + 1
    segment.started_at = now
    segment.finished_at = None
    segment.last_error = None
    segment.background_task_id = background_task_id
    segment.archive.status = "running"
    segment.archive.last_error = None
    if was_retry:
        segment.archive.capture_retry_at = None
    segment.archive.started_at = segment.archive.started_at or now
    session.commit()
    return segment


def recompute_archive_status(session, archive: LivestreamFrameArchive) -> None:
    segments = LivestreamFrameCaptureSegment.query.filter_by(
        archive_id=archive.id
    ).all()
    successful_segments = [
        segment for segment in segments if segment.status in ("success", "skipped")
    ]
    archive.uploaded_frame_count = sum(
        segment.uploaded_frame_count or 0 for segment in successful_segments
    )
    archive.last_uploaded_second = max(
        [
            segment.last_uploaded_second
            for segment in successful_segments
            if segment.last_uploaded_second is not None
        ],
        default=None,
    )
    archive.expected_frame_count = expected_frame_count(
        archive.duration_seconds, archive.frame_rate
    )

    if not segments:
        archive.status = (
            archive.status if archive.status in ARCHIVE_STATUSES else "pending"
        )
        return

    statuses = {segment.status for segment in segments}
    has_success = "success" in statuses
    if "running" in statuses:
        archive.status = "running"
    elif "error" in statuses:
        archive.status = "partial" if has_success else "error"
    elif statuses & {"queued", "pending"}:
        archive.status = "partial" if has_success else "queued"
    elif statuses <= {"success", "skipped"}:
        archive.status = "success"
        archive.completed_at = archive.completed_at or datetime.utcnow()
    elif statuses <= {"cancelled"}:
        archive.status = "cancelled"
    else:
        archive.status = "partial"


def _dashboard_row_event_date(usages: list[LivestreamUsage]) -> datetime | None:
    dates = [usage.event_date for usage in usages if usage.event_date is not None]
    if not dates:
        return None
    return min(dates)


def _dashboard_row_max_day_number(usages: list[LivestreamUsage]) -> int:
    return max((usage.stream.day_number for usage in usages), default=0)


def _dashboard_row_max_mat_number(usages: list[LivestreamUsage]) -> int:
    return max((usage.stream.mat_number for usage in usages), default=0)


def _dashboard_row_matches_search(row: dict, search: str) -> bool:
    terms = [term for term in search.casefold().split() if term]
    if not terms:
        return True

    values = [
        row["youtube_video_id"],
    ]
    for usage in row["usages"]:
        values.extend((usage.event_name or "", usage.stream.event_id or ""))
    searchable_text = " ".join(values).casefold()
    return all(term in searchable_text for term in terms)


def archive_dashboard_status(archive: LivestreamFrameArchive | None) -> str:
    if archive is None:
        return "not_synced"
    if archive.is_bad:
        return "bad"
    if archive.status in {"pending", "cancelled"}:
        return "ready"
    if archive.status in {"probing", "ready", "running"}:
        return "in_progress"
    return archive.status


def _dashboard_row_matches_status(row: dict, status: str) -> bool:
    if not status:
        return True
    return row["dashboard_status"] == status


def get_archive_dashboard_rows(
    session,
    sort: str = "event_date_desc",
    search: str = "",
    status: str = "",
    load_segments: bool = True,
) -> list[dict]:
    usages = discover_livestream_usages(session)
    archive_query = LivestreamFrameArchive.query
    if load_segments:
        archive_query = archive_query.options(
            selectinload(LivestreamFrameArchive.segments)
        )
    archives = {
        archive.youtube_video_id: archive
        for archive in archive_query.order_by(
            LivestreamFrameArchive.youtube_video_id
        ).all()
    }

    rows = []
    for youtube_video_id in sorted(set(usages) | set(archives)):
        archive = archives.get(youtube_video_id)
        row_usages = usages.get(youtube_video_id, [])
        rows.append(
            {
                "youtube_video_id": youtube_video_id,
                "canonical_url": canonical_youtube_url(youtube_video_id),
                "archive": archive,
                "dashboard_status": archive_dashboard_status(archive),
                "usages": row_usages,
                "event_date": _dashboard_row_event_date(row_usages),
                "max_day_number": _dashboard_row_max_day_number(row_usages),
                "max_mat_number": _dashboard_row_max_mat_number(row_usages),
            }
        )
    if search:
        rows = [row for row in rows if _dashboard_row_matches_search(row, search)]
    if status:
        rows = [row for row in rows if _dashboard_row_matches_status(row, status)]
    if sort == "youtube_id":
        rows.sort(key=lambda row: row["youtube_video_id"])
    elif sort == "event_date_asc":
        rows.sort(key=lambda row: row["youtube_video_id"])
        rows.sort(key=lambda row: row["max_mat_number"], reverse=True)
        rows.sort(key=lambda row: row["max_day_number"], reverse=True)
        rows.sort(
            key=lambda row: (
                row["event_date"] is None,
                row["event_date"] or datetime.max,
            )
        )
    else:
        rows.sort(key=lambda row: row["youtube_video_id"])
        rows.sort(key=lambda row: row["max_mat_number"], reverse=True)
        rows.sort(key=lambda row: row["max_day_number"], reverse=True)
        rows.sort(
            key=lambda row: row["event_date"] or datetime.min,
            reverse=True,
        )
    return rows


def get_archive_dashboard_page(
    session,
    sort: str = "event_date_desc",
    search: str = "",
    status: str = "",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], dict]:
    rows = get_archive_dashboard_rows(
        session,
        sort=sort,
        search=search,
        status=status,
        load_segments=False,
    )
    total = len(rows)
    per_page = max(int(per_page or 1), 1)
    total_pages = max(1, math.ceil(total / per_page))
    page = min(max(int(page or 1), 1), total_pages)
    offset = (page - 1) * per_page
    page_rows = rows[offset : offset + per_page]

    archive_ids = [
        row["archive"].id for row in page_rows if row.get("archive") is not None
    ]
    if archive_ids:
        loaded_archives = (
            LivestreamFrameArchive.query.options(
                selectinload(LivestreamFrameArchive.segments)
            )
            .filter(LivestreamFrameArchive.id.in_(archive_ids))
            .all()
        )
        archive_by_id = {archive.id: archive for archive in loaded_archives}
        for row in page_rows:
            archive = row.get("archive")
            if archive is not None:
                row["archive"] = archive_by_id[archive.id]

    return page_rows, {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "first_item": offset + 1 if total else 0,
        "last_item": min(offset + per_page, total),
    }


def archive_usage_rows(session, youtube_video_id: str) -> list[LivestreamUsage]:
    return discover_livestream_usages(session).get(youtube_video_id, [])


def apply_probe_metadata(
    archive: LivestreamFrameArchive, info: dict, selected: dict
) -> None:
    duration = info.get("duration")
    if duration is not None:
        archive.duration_seconds = int(math.ceil(float(duration)))
    archive.expected_frame_count = expected_frame_count(
        archive.duration_seconds, archive.frame_rate
    )
    archive.format_id = selected.get("format_id")
    archive.format_note = selected.get("format_note")
    archive.width = selected.get("width")
    archive.height = selected.get("height")
    archive.source_fps = selected.get("fps")
    archive.video_codec = selected.get("vcodec")
    archive.audio_codec = selected.get("acodec")
    archive.tbr = selected.get("tbr")
    archive.protocol = selected.get("protocol")
    archive.status = "ready"


def archive_progress_label(archive: LivestreamFrameArchive | None) -> str:
    if not archive:
        return ""
    expected = archive.expected_frame_count
    if expected is None:
        return f"{archive.uploaded_frame_count or 0} / ?"
    return f"{archive.uploaded_frame_count or 0} / {expected}"
