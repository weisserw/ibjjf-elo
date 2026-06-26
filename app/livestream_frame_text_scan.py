from __future__ import annotations

import io
import json
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import exists
from sqlalchemy.orm import selectinload

from models import (
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    LivestreamFrameTextScanSegment,
)


TEXT_SCAN_STATUSES = (
    "pending",
    "queued",
    "running",
    "partial",
    "success",
    "error",
    "cancelled",
)
TEXT_SCAN_SEGMENT_STATUSES = (
    "pending",
    "queued",
    "running",
    "success",
    "error",
    "cancelled",
    "skipped",
)
DEFAULT_COARSE_INTERVAL_SECONDS = 120
DEFAULT_PARSER_PROFILE = "auto"
DEFAULT_SCORE_ENGINE = "tesseract"
SCORE_FIELDS = (
    "top_points",
    "top_advantages",
    "top_penalties",
    "bottom_points",
    "bottom_advantages",
    "bottom_penalties",
)
NAME_FIELDS = (
    "top_athlete_name",
    "top_team_name",
    "bottom_athlete_name",
    "bottom_team_name",
)


@dataclass(frozen=True)
class TextEventData:
    frame_second: int
    top_points: int | None = None
    top_advantages: int | None = None
    top_penalties: int | None = None
    bottom_points: int | None = None
    bottom_advantages: int | None = None
    bottom_penalties: int | None = None
    timer_state: str | None = None
    timer_value: str | None = None
    top_athlete_name: str | None = None
    top_team_name: str | None = None
    bottom_athlete_name: str | None = None
    bottom_team_name: str | None = None
    profile_id: str | None = None
    score_engine: str | None = None
    name_engine: str | None = None
    confidence: float | None = None
    needs_review: bool = False
    evidence: dict | None = None


@dataclass
class TextState:
    top_points: int | None = None
    top_advantages: int | None = None
    top_penalties: int | None = None
    bottom_points: int | None = None
    bottom_advantages: int | None = None
    bottom_penalties: int | None = None
    timer_state: str | None = None
    timer_value: str | None = None
    timer_frame_second: int | None = None
    top_athlete_name: str | None = None
    top_team_name: str | None = None
    bottom_athlete_name: str | None = None
    bottom_team_name: str | None = None

    def copy(self) -> "TextState":
        return TextState(**asdict(self))


@dataclass(frozen=True)
class FrameReading:
    frame_second: int
    top_points: int | None = None
    top_advantages: int | None = None
    top_penalties: int | None = None
    bottom_points: int | None = None
    bottom_advantages: int | None = None
    bottom_penalties: int | None = None
    timer_state: str | None = None
    timer_value: str | None = None
    top_athlete_name: str | None = None
    top_team_name: str | None = None
    bottom_athlete_name: str | None = None
    bottom_team_name: str | None = None
    profile_id: str | None = None
    score_engine: str | None = None
    name_engine: str | None = None
    confidence: float | None = None
    needs_review: bool = False
    evidence: dict | None = None


class FrameTextParser(Protocol):
    def parse(
        self,
        frame_second: int,
        score_image: bytes | None,
        timer_image: bytes | None,
    ) -> FrameReading:
        pass


class FrameBatchProvider:
    def get_frame(self, frame_second: int, crop_variant: str) -> bytes | None:
        raise NotImplementedError


class S3FrameBatchProvider(FrameBatchProvider):
    def __init__(
        self,
        capture_segments: list[LivestreamFrameCaptureSegment],
        s3_client,
        bucket: str,
    ):
        self.capture_segments = sorted(
            capture_segments, key=lambda item: item.start_second
        )
        self.s3_client = s3_client
        self.bucket = bucket
        self._cache: dict[str, dict[str, bytes]] = {}

    def _segment_for_second(self, frame_second: int):
        for segment in self.capture_segments:
            if segment.start_second <= frame_second < segment.end_second:
                return segment
        return None

    def _load_batch(self, segment: LivestreamFrameCaptureSegment) -> dict[str, bytes]:
        key = segment.batch_s3_key
        if not key:
            raise RuntimeError(f"capture segment {segment.id} has no batch_s3_key")
        if key in self._cache:
            return self._cache[key]

        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        files = {}
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                fileobj = tar.extractfile(member)
                if fileobj is not None:
                    files[member.name] = fileobj.read()
        self._cache[key] = files
        return files

    def get_frame(self, frame_second: int, crop_variant: str) -> bytes | None:
        segment = self._segment_for_second(frame_second)
        if not segment:
            return None
        batch = self._load_batch(segment)
        prefix = f"{frame_second:09d}_{crop_variant}."
        for name, data in batch.items():
            if name.startswith(prefix):
                return data
        return None


def get_or_create_text_scan(
    session,
    archive: LivestreamFrameArchive,
    parser_profile: str = DEFAULT_PARSER_PROFILE,
    score_engine: str = DEFAULT_SCORE_ENGINE,
    name_engine: str | None = None,
    coarse_interval_seconds: int = DEFAULT_COARSE_INTERVAL_SECONDS,
) -> tuple[LivestreamFrameTextScan, bool]:
    scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one_or_none()
    if scan:
        return scan, False
    scan = LivestreamFrameTextScan(
        archive_id=archive.id,
        status="pending",
        parser_profile=parser_profile,
        score_engine=score_engine,
        name_engine=name_engine,
        coarse_interval_seconds=coarse_interval_seconds,
    )
    session.add(scan)
    return scan, True


def queue_text_scan(
    session,
    archive: LivestreamFrameArchive,
    parser_profile: str = DEFAULT_PARSER_PROFILE,
    score_engine: str = DEFAULT_SCORE_ENGINE,
    name_engine: str | None = None,
    coarse_interval_seconds: int = DEFAULT_COARSE_INTERVAL_SECONDS,
) -> int:
    if archive.status != "success":
        raise ValueError("text scans can only be queued for successful frame archives")

    scan, _ = get_or_create_text_scan(
        session,
        archive,
        parser_profile=parser_profile,
        score_engine=score_engine,
        name_engine=name_engine,
        coarse_interval_seconds=coarse_interval_seconds,
    )
    scan.parser_profile = parser_profile
    scan.score_engine = score_engine
    scan.name_engine = name_engine
    scan.coarse_interval_seconds = coarse_interval_seconds
    scan.status = "queued"
    scan.last_error = None
    scan.completed_at = None

    existing_capture_ids = {
        segment.capture_segment_id
        for segment in LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id)
    }
    capture_segments = (
        LivestreamFrameCaptureSegment.query.filter_by(
            archive_id=archive.id, status="success"
        )
        .order_by(LivestreamFrameCaptureSegment.start_second)
        .all()
    )
    created = 0
    for capture_segment in capture_segments:
        if capture_segment.id in existing_capture_ids:
            continue
        session.add(
            LivestreamFrameTextScanSegment(
                scan_id=scan.id,
                archive_id=archive.id,
                capture_segment_id=capture_segment.id,
                start_second=capture_segment.start_second,
                end_second=capture_segment.end_second,
                status="queued",
                attempt_count=0,
                event_count=0,
            )
        )
        created += 1

    requeued = (
        LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id)
        .filter(
            LivestreamFrameTextScanSegment.status.in_(["pending", "error", "cancelled"])
        )
        .update(
            {"status": "queued", "last_error": None, "finished_at": None},
            synchronize_session=False,
        )
    )
    scan.total_segment_count = len(capture_segments)
    recompute_text_scan_status(session, scan)
    if scan.status in ("pending", "partial"):
        scan.status = "queued"
    return created + requeued


def retry_failed_text_scan_segments(session, scan_ids: list | None = None) -> int:
    query = LivestreamFrameTextScanSegment.query.filter(
        LivestreamFrameTextScanSegment.status.in_(["error", "cancelled"])
    )
    if scan_ids:
        query = query.filter(LivestreamFrameTextScanSegment.scan_id.in_(scan_ids))

    segments = query.all()
    affected_scan_ids = set(scan_ids or [])
    for segment in segments:
        affected_scan_ids.add(segment.scan_id)
        segment.status = "queued"
        segment.last_error = None
        segment.finished_at = None

    if affected_scan_ids:
        scans = LivestreamFrameTextScan.query.filter(
            LivestreamFrameTextScan.id.in_(affected_scan_ids)
        ).all()
        for scan in scans:
            scan.last_error = None
            recompute_text_scan_status(session, scan)
            if scan.status in ("pending", "partial"):
                scan.status = "queued"
    return len(segments)


def cancel_queued_text_scan_segments(session, scan_ids: list | None = None) -> int:
    query = LivestreamFrameTextScanSegment.query.filter(
        LivestreamFrameTextScanSegment.status.in_(["pending", "queued", "running"])
    )
    if scan_ids:
        query = query.filter(LivestreamFrameTextScanSegment.scan_id.in_(scan_ids))
    segments = query.all()
    for segment in segments:
        segment.status = "cancelled"
        segment.finished_at = datetime.utcnow()
        recompute_text_scan_status(session, segment.scan)
    return len(segments)


def claim_next_text_scan_segment(
    session,
    scan_id=None,
    archive_id=None,
    youtube_video_id: str | None = None,
    background_task_id=None,
) -> LivestreamFrameTextScanSegment | None:
    query = (
        LivestreamFrameTextScanSegment.query.options(
            selectinload(LivestreamFrameTextScanSegment.scan),
            selectinload(LivestreamFrameTextScanSegment.archive),
            selectinload(LivestreamFrameTextScanSegment.capture_segment),
        )
        .join(LivestreamFrameTextScan)
        .join(LivestreamFrameArchive)
        .filter(LivestreamFrameTextScanSegment.status.in_(["pending", "queued"]))
    )
    if scan_id:
        query = query.filter(LivestreamFrameTextScanSegment.scan_id == scan_id)
    if archive_id:
        query = query.filter(LivestreamFrameTextScanSegment.archive_id == archive_id)
    if youtube_video_id:
        query = query.filter(
            LivestreamFrameArchive.youtube_video_id == youtube_video_id
        )

    candidates = query.order_by(
        LivestreamFrameTextScan.created_at,
        LivestreamFrameTextScanSegment.start_second,
        LivestreamFrameTextScanSegment.created_at,
    ).all()
    segment = None
    for candidate in candidates:
        blocker = LivestreamFrameTextScanSegment.query.filter(
            LivestreamFrameTextScanSegment.scan_id == candidate.scan_id,
            LivestreamFrameTextScanSegment.start_second < candidate.start_second,
            ~LivestreamFrameTextScanSegment.status.in_(["success", "skipped"]),
        ).first()
        if not blocker:
            segment = candidate
            break
    if not segment:
        return None

    now = datetime.utcnow()
    segment.status = "running"
    segment.attempt_count = (segment.attempt_count or 0) + 1
    segment.started_at = now
    segment.finished_at = None
    segment.last_error = None
    segment.background_task_id = background_task_id
    segment.scan.status = "running"
    segment.scan.started_at = segment.scan.started_at or now
    segment.scan.background_task_id = background_task_id
    segment.scan.last_error = None
    session.commit()
    return segment


def recompute_text_scan_status(session, scan: LivestreamFrameTextScan) -> None:
    segments = LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id).all()
    successful_segments = [
        segment for segment in segments if segment.status in ("success", "skipped")
    ]
    scan.total_segment_count = len(segments)
    scan.processed_segment_count = len(successful_segments)
    scan.last_processed_second = max(
        [
            segment.last_processed_second
            for segment in successful_segments
            if segment.last_processed_second is not None
        ],
        default=None,
    )
    if not segments:
        scan.status = scan.status if scan.status in TEXT_SCAN_STATUSES else "pending"
        return

    statuses = {segment.status for segment in segments}
    has_success = "success" in statuses
    if "running" in statuses:
        scan.status = "running"
    elif "error" in statuses:
        scan.status = "partial" if has_success else "error"
    elif statuses & {"queued", "pending"}:
        scan.status = "partial" if has_success else "queued"
    elif statuses <= {"success", "skipped"}:
        scan.status = "success"
        scan.completed_at = scan.completed_at or datetime.utcnow()
    elif statuses <= {"cancelled"}:
        scan.status = "cancelled"
    else:
        scan.status = "partial"


def _timer_to_seconds(value: str | None) -> int | None:
    if not value or ":" not in value:
        return None
    minutes, _, seconds = value.partition(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def _seconds_to_timer(value: int) -> str:
    value = max(0, value)
    minutes, seconds = divmod(value, 60)
    return f"{minutes:d}:{seconds:02d}"


def expected_timer_value(state: TextState, frame_second: int) -> str | None:
    if state.timer_state != "running":
        return state.timer_value
    start_seconds = _timer_to_seconds(state.timer_value)
    if start_seconds is None or state.timer_frame_second is None:
        return state.timer_value
    elapsed = max(0, frame_second - state.timer_frame_second)
    return _seconds_to_timer(start_seconds - elapsed)


def apply_event_to_state(state: TextState, event) -> TextState:
    next_state = state.copy()
    for field in SCORE_FIELDS:
        value = getattr(event, field, None)
        if value is not None:
            setattr(next_state, field, value)
    if getattr(event, "timer_state", None) is not None:
        next_state.timer_state = event.timer_state
        next_state.timer_value = event.timer_value
        next_state.timer_frame_second = event.frame_second
    for field in NAME_FIELDS:
        value = getattr(event, field, None)
        if value is not None:
            setattr(next_state, field, value)
    return next_state


def reconstruct_text_state(
    session, archive_id, before_second: int | None = None
) -> TextState:
    query = LivestreamFrameTextEvent.query.filter_by(archive_id=archive_id)
    if before_second is not None:
        query = query.filter(LivestreamFrameTextEvent.frame_second < before_second)
    events = query.order_by(LivestreamFrameTextEvent.frame_second).all()
    state = TextState()
    for event in events:
        state = apply_event_to_state(state, event)
    return state


def reading_changes(state: TextState, reading: FrameReading) -> dict:
    changes = {}
    for field in SCORE_FIELDS:
        value = getattr(reading, field)
        if value is not None and getattr(state, field) != value:
            changes[field] = value

    if reading.timer_state is not None:
        expected_value = expected_timer_value(state, reading.frame_second)
        if (
            state.timer_state != reading.timer_state
            or reading.timer_state != "running"
            and state.timer_value != reading.timer_value
            or reading.timer_state == "running"
            and expected_value != reading.timer_value
        ):
            changes["timer_state"] = reading.timer_state
            changes["timer_value"] = reading.timer_value

    for field in NAME_FIELDS:
        value = getattr(reading, field)
        if value is not None and getattr(state, field) != value:
            changes[field] = value
    return changes


def event_from_reading(reading: FrameReading, changes: dict) -> TextEventData:
    event_kwargs = {
        "frame_second": reading.frame_second,
        "profile_id": reading.profile_id,
        "score_engine": reading.score_engine,
        "name_engine": reading.name_engine,
        "confidence": reading.confidence,
        "needs_review": reading.needs_review,
        "evidence": reading.evidence,
    }
    event_kwargs.update(changes)
    return TextEventData(**event_kwargs)


def coarse_probe_seconds(
    start_second: int, end_second: int, interval: int
) -> list[int]:
    if end_second <= start_second:
        return []
    interval = max(1, interval)
    seconds = list(range(start_second, end_second, interval))
    last_second = end_second - 1
    if last_second not in seconds:
        seconds.append(last_second)
    return seconds


def _read_frame(provider: FrameBatchProvider, parser: FrameTextParser, second: int):
    return parser.parse(
        second,
        provider.get_frame(second, "score"),
        provider.get_frame(second, "timer"),
    )


def _find_first_changed_second(
    provider: FrameBatchProvider,
    parser: FrameTextParser,
    base_state: TextState,
    low_second: int,
    high_second: int,
) -> int:
    left = low_second + 1
    right = high_second
    while left < right:
        mid = (left + right) // 2
        reading = _read_frame(provider, parser, mid)
        if reading_changes(base_state, reading):
            right = mid
        else:
            left = mid + 1
    return left


def scan_frame_text_segment(
    provider: FrameBatchProvider,
    parser: FrameTextParser,
    start_second: int,
    end_second: int,
    initial_state: TextState | None = None,
    coarse_interval_seconds: int = DEFAULT_COARSE_INTERVAL_SECONDS,
) -> list[TextEventData]:
    state = initial_state.copy() if initial_state else TextState()
    events: list[TextEventData] = []
    previous_probe_second = start_second - 1
    for probe_second in coarse_probe_seconds(
        start_second, end_second, coarse_interval_seconds
    ):
        while True:
            reading = _read_frame(provider, parser, probe_second)
            changes = reading_changes(state, reading)
            if not changes:
                previous_probe_second = probe_second
                break

            refined_second = (
                probe_second
                if previous_probe_second >= probe_second
                else _find_first_changed_second(
                    provider,
                    parser,
                    state,
                    previous_probe_second,
                    probe_second,
                )
            )
            refined_reading = _read_frame(provider, parser, refined_second)
            refined_changes = reading_changes(state, refined_reading)
            if not refined_changes:
                previous_probe_second = refined_second
                continue
            event = event_from_reading(refined_reading, refined_changes)
            events.append(event)
            state = apply_event_to_state(state, event)
            if refined_second >= probe_second:
                previous_probe_second = refined_second
                break
            previous_probe_second = refined_second
    return events


def create_text_event(
    scan_segment: LivestreamFrameTextScanSegment, event_data: TextEventData
) -> LivestreamFrameTextEvent:
    return LivestreamFrameTextEvent(
        scan_id=scan_segment.scan_id,
        archive_id=scan_segment.archive_id,
        scan_segment_id=scan_segment.id,
        capture_segment_id=scan_segment.capture_segment_id,
        frame_second=event_data.frame_second,
        top_points=event_data.top_points,
        top_advantages=event_data.top_advantages,
        top_penalties=event_data.top_penalties,
        bottom_points=event_data.bottom_points,
        bottom_advantages=event_data.bottom_advantages,
        bottom_penalties=event_data.bottom_penalties,
        timer_state=event_data.timer_state,
        timer_value=event_data.timer_value,
        top_athlete_name=event_data.top_athlete_name,
        top_team_name=event_data.top_team_name,
        bottom_athlete_name=event_data.bottom_athlete_name,
        bottom_team_name=event_data.bottom_team_name,
        profile_id=event_data.profile_id,
        score_engine=event_data.score_engine,
        name_engine=event_data.name_engine,
        confidence=event_data.confidence,
        needs_review=event_data.needs_review,
        evidence_json=(
            json.dumps(event_data.evidence, sort_keys=True)
            if event_data.evidence is not None
            else None
        ),
    )


def replace_segment_events(
    session, scan_segment: LivestreamFrameTextScanSegment, events: list[TextEventData]
) -> None:
    LivestreamFrameTextEvent.query.filter_by(scan_segment_id=scan_segment.id).delete()
    for event_data in events:
        session.add(create_text_event(scan_segment, event_data))


def mark_text_scan_segment_success(
    session, scan_segment: LivestreamFrameTextScanSegment, events: list[TextEventData]
) -> None:
    replace_segment_events(session, scan_segment, events)
    scan_segment.status = "success"
    scan_segment.event_count = len(events)
    scan_segment.last_processed_second = scan_segment.end_second - 1
    scan_segment.last_error = None
    scan_segment.finished_at = datetime.utcnow()
    recompute_text_scan_status(session, scan_segment.scan)


def mark_text_scan_segment_error(
    session, scan_segment: LivestreamFrameTextScanSegment, error: str
) -> None:
    session.rollback()
    scan_segment = session.get(LivestreamFrameTextScanSegment, scan_segment.id)
    scan = session.get(LivestreamFrameTextScan, scan_segment.scan_id)
    scan_segment.status = "error"
    scan_segment.last_error = error
    scan_segment.finished_at = datetime.utcnow()
    scan.last_error = error
    recompute_text_scan_status(session, scan)


def archive_has_text_scan(session, archive_id) -> bool:
    return session.query(
        exists().where(LivestreamFrameTextScan.archive_id == archive_id)
    ).scalar()
