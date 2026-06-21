from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import selectinload
from sqlalchemy import Integer, cast, func

from models import (
    Event,
    LiveStream,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameOcrReading,
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
DEFAULT_SEGMENT_SECONDS = 3600
DEFAULT_FRAME_RATE = 1.0
DEFAULT_IMAGE_FORMAT = "jpg"


@dataclass(frozen=True)
class LivestreamUsage:
    stream: LiveStream
    youtube_video_id: str
    event_name: str | None


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
        status="pending",
        frame_rate=DEFAULT_FRAME_RATE,
        image_format=DEFAULT_IMAGE_FORMAT,
        processed_frame_count=0,
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
                    processed_frame_count=0,
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
        LivestreamFrameArchive.created_at,
        LivestreamFrameCaptureSegment.start_second,
        LivestreamFrameCaptureSegment.created_at,
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
    successful_segments = [
        segment for segment in segments if segment.status in ("success", "skipped")
    ]
    archive.processed_frame_count = sum(
        segment.processed_frame_count or 0 for segment in successful_segments
    )
    archive.last_processed_second = max(
        [
            segment.last_processed_second
            for segment in successful_segments
            if segment.last_processed_second is not None
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
            quality = archive_quality_metrics(session, archive.id)
        rows.append(
            {
                "youtube_video_id": youtube_video_id,
                "canonical_url": canonical_youtube_url(youtube_video_id),
                "archive": archive,
                "usages": usages.get(youtube_video_id, []),
                "latest_task_id": latest_task_id,
                "quality": quality if archive else None,
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
        return f"{archive.processed_frame_count or 0} / ?"
    return f"{archive.processed_frame_count or 0} / {expected}"


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return (part / whole) * 100.0


def archive_quality_metrics(session, archive_id) -> dict:
    total = (
        session.query(func.count(LivestreamFrameOcrReading.id))
        .filter(LivestreamFrameOcrReading.archive_id == archive_id)
        .scalar()
        or 0
    )
    if total == 0:
        return {
            "total": 0,
            "score_complete": 0,
            "clock_detected": 0,
            "victory": 0,
            "score_complete_percent": 0.0,
            "clock_detected_percent": 0.0,
            "avg_known_score_count": 0.0,
            "engines": "",
        }

    score_complete = (
        session.query(func.count(LivestreamFrameOcrReading.id))
        .filter(
            LivestreamFrameOcrReading.archive_id == archive_id,
            LivestreamFrameOcrReading.score_complete.is_(True),
        )
        .scalar()
        or 0
    )
    clock_detected = (
        session.query(func.count(LivestreamFrameOcrReading.id))
        .filter(
            LivestreamFrameOcrReading.archive_id == archive_id,
            LivestreamFrameOcrReading.clock_detected.is_(True),
        )
        .scalar()
        or 0
    )
    victory = (
        session.query(func.count(LivestreamFrameOcrReading.id))
        .filter(
            LivestreamFrameOcrReading.archive_id == archive_id,
            LivestreamFrameOcrReading.victory.is_(True),
        )
        .scalar()
        or 0
    )
    avg_known_score_count = (
        session.query(func.avg(LivestreamFrameOcrReading.known_score_count))
        .filter(LivestreamFrameOcrReading.archive_id == archive_id)
        .scalar()
        or 0.0
    )
    engines = [
        row[0]
        for row in session.query(LivestreamFrameOcrReading.ocr_engine)
        .filter(LivestreamFrameOcrReading.archive_id == archive_id)
        .distinct()
        .order_by(LivestreamFrameOcrReading.ocr_engine)
        .all()
        if row[0]
    ]
    return {
        "total": total,
        "score_complete": score_complete,
        "clock_detected": clock_detected,
        "victory": victory,
        "score_complete_percent": _percent(score_complete, total),
        "clock_detected_percent": _percent(clock_detected, total),
        "avg_known_score_count": float(avg_known_score_count),
        "engines": ", ".join(engines),
    }


def segment_quality_metrics(session, segment_ids: list) -> dict:
    if not segment_ids:
        return {}
    rows = (
        session.query(
            LivestreamFrameOcrReading.segment_id,
            func.count(LivestreamFrameOcrReading.id),
            func.sum(cast(LivestreamFrameOcrReading.score_complete, Integer)),
            func.sum(cast(LivestreamFrameOcrReading.clock_detected, Integer)),
            func.avg(LivestreamFrameOcrReading.known_score_count),
        )
        .filter(LivestreamFrameOcrReading.segment_id.in_(segment_ids))
        .group_by(LivestreamFrameOcrReading.segment_id)
        .all()
    )
    metrics = {}
    for segment_id, total, score_complete, clock_detected, avg_known_score in rows:
        total = total or 0
        score_complete = score_complete or 0
        clock_detected = clock_detected or 0
        metrics[segment_id] = {
            "total": total,
            "score_complete": score_complete,
            "clock_detected": clock_detected,
            "score_complete_percent": _percent(score_complete, total),
            "clock_detected_percent": _percent(clock_detected, total),
            "avg_known_score_count": float(avg_known_score or 0.0),
        }
    return metrics


def upsert_ocr_reading(
    session,
    archive: LivestreamFrameArchive,
    segment: LivestreamFrameCaptureSegment,
    reading,
) -> LivestreamFrameOcrReading:
    row = LivestreamFrameOcrReading.query.filter_by(
        archive_id=archive.id,
        frame_second=reading.frame_second,
    ).one_or_none()
    if row is None:
        row = LivestreamFrameOcrReading(
            archive_id=archive.id,
            frame_second=reading.frame_second,
        )
        session.add(row)

    row.segment_id = segment.id
    row.frame_index = reading.frame_index
    row.video_offset_seconds = reading.video_offset_seconds
    row.ocr_engine = reading.ocr_engine
    row.overlay_style = reading.overlay_style
    row.clock = reading.clock
    row.red_points = reading.red_points
    row.red_advantages = reading.red_advantages
    row.red_penalties = reading.red_penalties
    row.blue_points = reading.blue_points
    row.blue_advantages = reading.blue_advantages
    row.blue_penalties = reading.blue_penalties
    row.red_athlete_name = getattr(reading, "red_athlete_name", None)
    row.red_team_name = getattr(reading, "red_team_name", None)
    row.blue_athlete_name = getattr(reading, "blue_athlete_name", None)
    row.blue_team_name = getattr(reading, "blue_team_name", None)
    row.known_score_count = reading.known_score_count
    row.score_complete = reading.score_complete
    row.clock_detected = reading.clock_detected
    row.victory = reading.victory
    row.victory_text = reading.victory_text
    row.scoreboard_text = reading.scoreboard_text
    row.timer_text = reading.timer_text
    return row
