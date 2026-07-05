from __future__ import annotations

import math
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
DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS = 1800


def error_retry_backoff_seconds(
    attempt_count: int | None,
    base_seconds: int = DEFAULT_ERROR_RETRY_BACKOFF_SECONDS,
    max_seconds: int = DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS,
) -> int:
    if base_seconds <= 0:
        return 0
    attempts = max((attempt_count or 0), 1)
    retry_seconds = base_seconds * (2 ** (attempts - 1))
    if max_seconds > 0:
        retry_seconds = min(retry_seconds, max_seconds)
    return retry_seconds


def error_segment_retry_ready(
    segment: LivestreamFrameCaptureSegment,
    now: datetime | None = None,
    base_seconds: int = DEFAULT_ERROR_RETRY_BACKOFF_SECONDS,
    max_seconds: int = DEFAULT_MAX_ERROR_RETRY_BACKOFF_SECONDS,
) -> bool:
    if segment.status != "error":
        return False
    if base_seconds <= 0:
        return True
    if not segment.finished_at:
        return True
    now = now or datetime.utcnow()
    retry_at = segment.finished_at + timedelta(
        seconds=error_retry_backoff_seconds(
            segment.attempt_count,
            base_seconds=base_seconds,
            max_seconds=max_seconds,
        )
    )
    return retry_at <= now


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
) -> int:
    created = create_missing_segments(session, archive, segment_seconds)
    requeued = (
        LivestreamFrameCaptureSegment.query.filter_by(archive_id=archive.id)
        .filter(
            LivestreamFrameCaptureSegment.status.in_(["pending", "error", "cancelled"])
        )
        .update({"status": "queued", "last_error": None}, synchronize_session=False)
    )
    archive.status = "queued"
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
    query = LivestreamFrameCaptureSegment.query.filter(
        LivestreamFrameCaptureSegment.status.in_(statuses)
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
            recompute_archive_status(session, archive)
    return len(segments)


def requeue_completed_segments(session, archive: LivestreamFrameArchive) -> int:
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
    base_query = LivestreamFrameCaptureSegment.query.options(
        selectinload(LivestreamFrameCaptureSegment.archive)
    ).join(LivestreamFrameArchive)
    if archive_id:
        base_query = base_query.filter(
            LivestreamFrameCaptureSegment.archive_id == archive_id
        )
    if youtube_video_id:
        base_query = base_query.filter(
            LivestreamFrameArchive.youtube_video_id == youtube_video_id
        )

    ordering = (
        LivestreamFrameArchive.created_at,
        LivestreamFrameCaptureSegment.start_second,
        LivestreamFrameCaptureSegment.created_at,
    )
    segment = (
        base_query.filter(
            LivestreamFrameCaptureSegment.status.in_(["pending", "queued"])
        )
        .order_by(*ordering)
        .first()
    )
    if not segment:
        now = datetime.utcnow()
        error_segments = (
            base_query.filter(LivestreamFrameCaptureSegment.status == "error")
            .order_by(*ordering)
            .all()
        )
        segment = next(
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
    if not segment:
        return None

    now = datetime.utcnow()
    segment.status = "running"
    segment.attempt_count = (segment.attempt_count or 0) + 1
    segment.started_at = now
    segment.finished_at = None
    segment.last_error = None
    segment.background_task_id = background_task_id
    segment.archive.status = "running"
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


def get_archive_dashboard_rows(session, sort: str = "event_date_desc") -> list[dict]:
    usages = discover_livestream_usages(session)
    archives = {
        archive.youtube_video_id: archive
        for archive in LivestreamFrameArchive.query.options(
            selectinload(LivestreamFrameArchive.segments)
        )
        .order_by(LivestreamFrameArchive.youtube_video_id)
        .all()
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
                "usages": row_usages,
                "event_date": _dashboard_row_event_date(row_usages),
            }
        )
    if sort == "youtube_id":
        rows.sort(key=lambda row: row["youtube_video_id"])
    elif sort == "event_date_asc":
        rows.sort(key=lambda row: row["youtube_video_id"])
        rows.sort(
            key=lambda row: (
                row["event_date"] is None,
                row["event_date"] or datetime.max,
            )
        )
    else:
        rows.sort(key=lambda row: row["youtube_video_id"])
        rows.sort(
            key=lambda row: row["event_date"] or datetime.min,
            reverse=True,
        )
    return rows


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
