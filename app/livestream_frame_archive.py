from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import selectinload

from models import (
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
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
SEGMENT_STATUSES = (
    "pending",
    "queued",
    "running",
    "success",
    "error",
    "cancelled",
    "skipped",
)
DEFAULT_SEGMENT_SECONDS = 600
DEFAULT_FRAME_RATE = 1.0
DEFAULT_IMAGE_FORMAT = "jpg"


@dataclass(frozen=True)
class LivestreamUsage:
    stream: LiveStream
    youtube_video_id: str
    event_name: str | None


def s3_prefix_for_youtube_id(youtube_video_id: str) -> str:
    return f"livestream-frames/{youtube_video_id}/"


def frame_s3_key(archive: LivestreamFrameArchive, second: int) -> str:
    image_format = archive.image_format or DEFAULT_IMAGE_FORMAT
    return f"{archive.s3_prefix}{second:09d}.{image_format}"


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

    usages: dict[str, list[LivestreamUsage]] = {}
    for stream in streams:
        youtube_video_id = extract_youtube_video_id(stream.link)
        if not youtube_video_id:
            continue
        usages.setdefault(youtube_video_id, []).append(
            LivestreamUsage(
                stream=stream,
                youtube_video_id=youtube_video_id,
                event_name=events_by_id.get(stream.event_id),
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


def create_missing_segments(
    session,
    archive: LivestreamFrameArchive,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
) -> int:
    existing = {
        (segment.start_second, segment.end_second)
        for segment in LivestreamFrameCaptureSegment.query.filter_by(
            archive_id=archive.id
        ).all()
    }
    existing_starts = {start_second for start_second, _ in existing}

    if archive.duration_seconds is None:
        ranges = [(0, segment_seconds)]
    else:
        ranges = segment_ranges(archive.duration_seconds, segment_seconds)

    created = 0
    for start_second, end_second in ranges:
        if (start_second, end_second) in existing or start_second in existing_starts:
            continue
        session.add(
            LivestreamFrameCaptureSegment(
                archive_id=archive.id,
                start_second=start_second,
                end_second=end_second,
                status="queued",
                attempt_count=0,
                uploaded_frame_count=0,
            )
        )
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
        .filter(LivestreamFrameCaptureSegment.status.in_(["pending", "error"]))
        .update({"status": "queued", "last_error": None}, synchronize_session=False)
    )
    archive.status = "queued"
    archive.last_error = None
    archive.completed_at = None
    archive.expected_frame_count = expected_frame_count(
        archive.duration_seconds, archive.frame_rate
    )
    return created + requeued


def retry_failed_segments(session, archive_ids: list | None = None) -> int:
    query = LivestreamFrameCaptureSegment.query.filter(
        LivestreamFrameCaptureSegment.status == "error"
    )
    if archive_ids:
        query = query.filter(LivestreamFrameCaptureSegment.archive_id.in_(archive_ids))

    segments = query.all()
    for segment in segments:
        segment.status = "queued"
        segment.last_error = None
        segment.finished_at = None
        recompute_archive_status(session, segment.archive)
    return len(segments)


def cancel_queued_segments(session, archive_ids: list | None = None) -> int:
    query = LivestreamFrameCaptureSegment.query.filter(
        LivestreamFrameCaptureSegment.status.in_(["pending", "queued", "running"])
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
) -> LivestreamFrameCaptureSegment | None:
    query = (
        LivestreamFrameCaptureSegment.query.options(
            selectinload(LivestreamFrameCaptureSegment.archive)
        )
        .join(LivestreamFrameArchive)
        .filter(LivestreamFrameCaptureSegment.status.in_(["pending", "queued"]))
    )
    if archive_id:
        query = query.filter(LivestreamFrameCaptureSegment.archive_id == archive_id)
    if youtube_video_id:
        query = query.filter(
            LivestreamFrameArchive.youtube_video_id == youtube_video_id
        )

    segment = query.order_by(
        LivestreamFrameCaptureSegment.created_at,
        LivestreamFrameCaptureSegment.start_second,
    ).first()
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
    archive.uploaded_frame_count = sum(
        segment.uploaded_frame_count or 0 for segment in segments
    )
    archive.last_uploaded_second = max(
        [
            segment.last_uploaded_second
            for segment in segments
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


def get_archive_dashboard_rows(session) -> list[dict]:
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
        latest_task_id = None
        if archive:
            latest_segment = (
                LivestreamFrameCaptureSegment.query.filter_by(archive_id=archive.id)
                .filter(LivestreamFrameCaptureSegment.background_task_id.isnot(None))
                .order_by(LivestreamFrameCaptureSegment.updated_at.desc())
                .first()
            )
            if latest_segment:
                latest_task_id = latest_segment.background_task_id
        rows.append(
            {
                "youtube_video_id": youtube_video_id,
                "canonical_url": canonical_youtube_url(youtube_video_id),
                "archive": archive,
                "usages": usages.get(youtube_video_id, []),
                "latest_task_id": latest_task_id,
            }
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
