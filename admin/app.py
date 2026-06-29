import os
import sys
import uuid
import json
import io
import subprocess
import threading
import time
import traceback
import signal
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta, timezone
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from types import SimpleNamespace
from urllib.parse import urlparse, urlencode, urlunparse
from sqlalchemy import or_, func, case
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError


# Ensure app directory is in sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))
from extensions import db
from models import (
    Athlete,
    Event,
    RegistrationLink,
    LiveStream,
    Match,
    MatchParticipant,
    Medal,
    ResultMedal,
    YoutubeMatchVideo,
    Team,
    FloEventTag,
    FloMatLink,
    BackgroundTask,
    LivestreamFrameArchive,
    LivestreamFrameCaptureSegment,
    LivestreamFrameTextEvent,
    LivestreamFrameTextScan,
    LivestreamFrameTextScanSegment,
    MatchParticipantTextEvent,
    FloSearchName,
    TeamNameMapping,
    AthleteMediaCoverage,
)
from livestream_frame_archive import (
    DEFAULT_SEGMENT_SECONDS,
    apply_probe_metadata,
    archive_progress_label,
    archive_usage_rows,
    cancel_queued_segments,
    claim_next_segment,
    create_missing_segments,
    get_archive_dashboard_rows,
    get_or_create_archive,
    queue_archive_capture,
    requeue_completed_segments,
    recompute_archive_status,
    retry_failed_segments,
    sync_archives_from_livestreams,
)
from livestream_frame_text_scan import (
    DEFAULT_COARSE_INTERVAL_SECONDS,
    DEFAULT_NAME_ENGINE,
    DEFAULT_PARSER_PROFILE,
    DEFAULT_SCORE_ENGINE,
    SCOREBOARD_STATE_BLANK,
    SCORE_FIELDS,
    TEXT_SCAN_SEGMENT_STATUSES,
    TextState,
    apply_event_to_state,
    cancel_queued_text_scan_segments,
    claim_next_text_scan_segment,
    mark_text_scan_segment_error,
    mark_text_scan_segment_success,
    prepare_text_scan_segment_rescan,
    queue_text_scan,
    reconstruct_text_state,
    reset_text_scan_for_archive,
    retry_failed_text_scan_segments,
    S3FrameBatchProvider,
    TextEventData,
)
from youtube_utils import canonical_youtube_url
from livestream_match_linking import link_completed_text_scan
from normalize import normalize
from elo import WINNER_NOT_RECORDED
from photos import (
    bucket_name,
    detect_image_content_type,
    get_public_photo_url,
    get_s3_client,
    save_profile_photo_to_s3,
)

app = Flask(__name__)
app.secret_key = os.environ.get("ADMIN_SECRET_KEY", "default_secret")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Use same SQLite DB file as main app by default
default_db_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../app/instance/app.db")
)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{default_db_path}")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Admin password
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
MAX_PROFILE_PHOTO_BYTES = 1 * 1024 * 1024
MEDIA_COVERAGE_TYPES = (
    "feature",
    "news",
    "video",
    "podcast",
    "highlight",
    "technique",
    "interview",
    "breakdown",
)
MAX_MEDIA_TITLE_SCAN_BYTES = 4 * 1024 * 1024
WORKER_API_PREFIX = "/api/livestream_frame_archives/worker/"


def _append_task_log(task, text):
    task.log_text = (task.log_text or "") + text


def _utc_iso(dt):
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _archive_payload(archive):
    if not archive:
        return None
    return {
        "id": str(archive.id),
        "youtube_video_id": archive.youtube_video_id,
        "canonical_url": archive.canonical_url,
        "s3_prefix": archive.s3_prefix,
        "status": archive.status,
        "frame_rate": archive.frame_rate,
        "image_format": archive.image_format,
        "jpeg_quality": archive.jpeg_quality,
        "duration_seconds": archive.duration_seconds,
        "expected_frame_count": archive.expected_frame_count,
        "uploaded_frame_count": archive.uploaded_frame_count,
        "last_uploaded_second": archive.last_uploaded_second,
        "format_id": archive.format_id,
        "format_note": archive.format_note,
        "width": archive.width,
        "height": archive.height,
        "source_fps": archive.source_fps,
        "video_codec": archive.video_codec,
        "audio_codec": archive.audio_codec,
        "tbr": archive.tbr,
        "protocol": archive.protocol,
        "yt_dlp_version": archive.yt_dlp_version,
        "last_error": archive.last_error,
        "created_at": _utc_iso(archive.created_at),
        "updated_at": _utc_iso(archive.updated_at),
        "started_at": _utc_iso(archive.started_at),
        "completed_at": _utc_iso(archive.completed_at),
    }


def _segment_payload(segment, include_archive=True):
    if not segment:
        return None
    payload = {
        "id": str(segment.id),
        "archive_id": str(segment.archive_id),
        "start_second": segment.start_second,
        "end_second": segment.end_second,
        "status": segment.status,
        "attempt_count": segment.attempt_count,
        "uploaded_frame_count": segment.uploaded_frame_count,
        "sampled_frame_count": segment.sampled_frame_count,
        "last_uploaded_second": segment.last_uploaded_second,
        "batch_s3_key": segment.batch_s3_key,
        "batch_uploaded_at": _utc_iso(segment.batch_uploaded_at),
        "background_task_id": (
            str(segment.background_task_id) if segment.background_task_id else None
        ),
        "last_error": segment.last_error,
        "created_at": _utc_iso(segment.created_at),
        "updated_at": _utc_iso(segment.updated_at),
        "started_at": _utc_iso(segment.started_at),
        "finished_at": _utc_iso(segment.finished_at),
    }
    if include_archive:
        payload["archive"] = _archive_payload(segment.archive)
    return payload


def _text_scan_payload(scan):
    if not scan:
        return None
    return {
        "id": str(scan.id),
        "archive_id": str(scan.archive_id),
        "status": scan.status,
        "parser_profile": scan.parser_profile,
        "score_engine": scan.score_engine,
        "name_engine": scan.name_engine,
        "coarse_interval_seconds": scan.coarse_interval_seconds,
        "total_segment_count": scan.total_segment_count,
        "processed_segment_count": scan.processed_segment_count,
        "last_processed_second": scan.last_processed_second,
        "background_task_id": (
            str(scan.background_task_id) if scan.background_task_id else None
        ),
        "last_error": scan.last_error,
        "created_at": _utc_iso(scan.created_at),
        "updated_at": _utc_iso(scan.updated_at),
        "started_at": _utc_iso(scan.started_at),
        "completed_at": _utc_iso(scan.completed_at),
    }


def _text_scan_capture_segment_payload(capture_segment):
    if not capture_segment:
        return None
    return {
        "id": str(capture_segment.id),
        "archive_id": str(capture_segment.archive_id),
        "start_second": capture_segment.start_second,
        "end_second": capture_segment.end_second,
        "status": capture_segment.status,
        "batch_s3_key": capture_segment.batch_s3_key,
        "last_uploaded_second": capture_segment.last_uploaded_second,
    }


def _text_scan_segment_payload(segment, include_scan=True, include_archive=True):
    if not segment:
        return None
    payload = {
        "id": str(segment.id),
        "scan_id": str(segment.scan_id),
        "archive_id": str(segment.archive_id),
        "capture_segment_id": str(segment.capture_segment_id),
        "start_second": segment.start_second,
        "end_second": segment.end_second,
        "status": segment.status,
        "attempt_count": segment.attempt_count,
        "event_count": segment.event_count,
        "last_processed_second": segment.last_processed_second,
        "background_task_id": (
            str(segment.background_task_id) if segment.background_task_id else None
        ),
        "last_error": segment.last_error,
        "created_at": _utc_iso(segment.created_at),
        "updated_at": _utc_iso(segment.updated_at),
        "started_at": _utc_iso(segment.started_at),
        "finished_at": _utc_iso(segment.finished_at),
        "capture_segment": _text_scan_capture_segment_payload(segment.capture_segment),
    }
    if include_archive:
        capture_segments = (
            LivestreamFrameCaptureSegment.query.filter_by(
                archive_id=segment.archive_id, status="success"
            )
            .order_by(LivestreamFrameCaptureSegment.start_second)
            .all()
        )
        payload["archive_capture_segments"] = [
            _text_scan_capture_segment_payload(capture_segment)
            for capture_segment in capture_segments
        ]
    if include_scan:
        payload["scan"] = _text_scan_payload(segment.scan)
    if include_archive:
        payload["archive"] = _archive_payload(segment.archive)
    return payload


def _text_event_payload(event):
    if not event:
        return None
    evidence = None
    if event.evidence_json:
        try:
            evidence = json.loads(event.evidence_json)
        except json.JSONDecodeError:
            evidence = {"raw": event.evidence_json}
    return {
        "id": str(event.id),
        "scan_id": str(event.scan_id),
        "archive_id": str(event.archive_id),
        "scan_segment_id": str(event.scan_segment_id),
        "capture_segment_id": str(event.capture_segment_id),
        "frame_second": event.frame_second,
        "top_points": event.top_points,
        "top_advantages": event.top_advantages,
        "top_penalties": event.top_penalties,
        "bottom_points": event.bottom_points,
        "bottom_advantages": event.bottom_advantages,
        "bottom_penalties": event.bottom_penalties,
        "scoreboard_state": event.scoreboard_state,
        "timer_state": event.timer_state,
        "timer_value": event.timer_value,
        "top_athlete_name": event.top_athlete_name,
        "top_team_name": event.top_team_name,
        "bottom_athlete_name": event.bottom_athlete_name,
        "bottom_team_name": event.bottom_team_name,
        "profile_id": event.profile_id,
        "score_engine": event.score_engine,
        "name_engine": event.name_engine,
        "confidence": event.confidence,
        "needs_review": event.needs_review,
        "evidence": evidence,
        "created_at": _utc_iso(event.created_at),
        "updated_at": _utc_iso(event.updated_at),
    }


def _text_scan_progress_label(scan):
    if not scan:
        return ""
    return f"{scan.processed_segment_count or 0} / {scan.total_segment_count or 0}"


def _text_event_type_counts_query():
    score_condition = or_(
        LivestreamFrameTextEvent.top_points.isnot(None),
        LivestreamFrameTextEvent.top_advantages.isnot(None),
        LivestreamFrameTextEvent.top_penalties.isnot(None),
        LivestreamFrameTextEvent.bottom_points.isnot(None),
        LivestreamFrameTextEvent.bottom_advantages.isnot(None),
        LivestreamFrameTextEvent.bottom_penalties.isnot(None),
        LivestreamFrameTextEvent.scoreboard_state.isnot(None),
    )
    timer_condition = or_(
        LivestreamFrameTextEvent.timer_state.isnot(None),
        LivestreamFrameTextEvent.timer_value.isnot(None),
    )
    athlete_name_condition = or_(
        LivestreamFrameTextEvent.top_athlete_name.isnot(None),
        LivestreamFrameTextEvent.bottom_athlete_name.isnot(None),
    )
    team_name_condition = or_(
        LivestreamFrameTextEvent.top_team_name.isnot(None),
        LivestreamFrameTextEvent.bottom_team_name.isnot(None),
    )
    return db.session.query(
        LivestreamFrameTextEvent.scan_id.label("scan_id"),
        func.count(LivestreamFrameTextEvent.id).label("total"),
        func.sum(case((score_condition, 1), else_=0)).label("score"),
        func.sum(case((timer_condition, 1), else_=0)).label("timer"),
        func.sum(case((athlete_name_condition, 1), else_=0)).label("athlete_names"),
        func.sum(case((team_name_condition, 1), else_=0)).label("team_names"),
        func.sum(
            case((LivestreamFrameTextEvent.profile_id.isnot(None), 1), else_=0)
        ).label("profiles"),
        func.sum(
            case((LivestreamFrameTextEvent.needs_review.is_(True), 1), else_=0)
        ).label("needs_review"),
    ).group_by(LivestreamFrameTextEvent.scan_id)


def _empty_text_event_counts():
    return {
        "total": 0,
        "score": 0,
        "timer": 0,
        "athlete_names": 0,
        "team_names": 0,
        "profiles": 0,
        "needs_review": 0,
    }


def _text_event_counts_for_scan_ids(scan_ids):
    if not scan_ids:
        return {}
    counts = {}
    for row in _text_event_type_counts_query().filter(
        LivestreamFrameTextEvent.scan_id.in_(scan_ids)
    ):
        counts[row.scan_id] = {
            "total": row.total or 0,
            "score": row.score or 0,
            "timer": row.timer or 0,
            "athlete_names": row.athlete_names or 0,
            "team_names": row.team_names or 0,
            "profiles": row.profiles or 0,
            "needs_review": row.needs_review or 0,
        }
    return counts


def _linked_text_event_rows(events):
    event_ids = [event.id for event in events]
    if not event_ids:
        return {}
    associations = MatchParticipantTextEvent.query.filter(
        MatchParticipantTextEvent.livestream_frame_text_event_id.in_(event_ids)
    ).all()
    participant_ids = {association.match_participant_id for association in associations}
    participants = {
        participant.id: participant
        for participant in MatchParticipant.query.options(
            selectinload(MatchParticipant.athlete),
            selectinload(MatchParticipant.match),
        )
        .filter(MatchParticipant.id.in_(participant_ids))
        .all()
    }
    grouped = {}
    for association in associations:
        participant = participants.get(association.match_participant_id)
        if not participant:
            continue
        grouped.setdefault(association.livestream_frame_text_event_id, []).append(
            participant
        )

    rows = {}
    for event_id, linked_participants in grouped.items():
        match_participants = [
            participant
            for participant in linked_participants
            if participant.match is not None
        ]
        if not match_participants:
            continue
        match = match_participants[0].match
        top = next(
            (
                participant
                for participant in match_participants
                if participant.scoreboard_position == "top"
            ),
            None,
        )
        bottom = next(
            (
                participant
                for participant in match_participants
                if participant.scoreboard_position == "bottom"
            ),
            None,
        )
        rows[event_id] = SimpleNamespace(match=match, top=top, bottom=bottom)
    return rows


def _text_event_display_rows(events, linked_rows=None):
    linked_rows = linked_rows or {}
    rows = []
    state = TextState()
    for event in events:
        has_score_change = (
            any(getattr(event, field, None) is not None for field in SCORE_FIELDS)
            or getattr(event, "scoreboard_state", None) is not None
        )
        state = apply_event_to_state(state, event)
        rows.append(
            SimpleNamespace(
                event=event,
                score=state.copy(),
                has_score_change=has_score_change,
                is_scoreboard_blank=state.scoreboard_state == SCOREBOARD_STATE_BLANK,
                linked_match=linked_rows.get(getattr(event, "id", None)),
            )
        )
    return rows


def _text_scan_segment_status_counts(scan_ids):
    if not scan_ids:
        return {}
    counts = {}
    rows = (
        db.session.query(
            LivestreamFrameTextScanSegment.scan_id,
            LivestreamFrameTextScanSegment.status,
            func.count(LivestreamFrameTextScanSegment.id),
        )
        .filter(LivestreamFrameTextScanSegment.scan_id.in_(scan_ids))
        .group_by(
            LivestreamFrameTextScanSegment.scan_id,
            LivestreamFrameTextScanSegment.status,
        )
        .all()
    )
    for scan_id, status, count in rows:
        counts.setdefault(scan_id, {})[status] = count
    return counts


def _livestream_frame_text_scan_rows():
    archive_rows = get_archive_dashboard_rows(db.session)
    archive_ids = [
        row["archive"].id for row in archive_rows if row.get("archive") is not None
    ]
    scans = []
    if archive_ids:
        scans = LivestreamFrameTextScan.query.filter(
            LivestreamFrameTextScan.archive_id.in_(archive_ids)
        ).all()
    scan_by_archive_id = {scan.archive_id: scan for scan in scans}
    scan_ids = [scan.id for scan in scans]
    event_counts_by_scan_id = _text_event_counts_for_scan_ids(scan_ids)
    segment_counts_by_scan_id = _text_scan_segment_status_counts(scan_ids)

    rows = []
    for row in archive_rows:
        archive = row.get("archive")
        scan = scan_by_archive_id.get(archive.id) if archive else None
        capture_segments = list(archive.segments) if archive else []
        successful_capture_segments = [
            segment for segment in capture_segments if segment.status == "success"
        ]
        ready_to_queue = (
            archive is not None
            and archive.status == "success"
            and scan is None
            and bool(successful_capture_segments)
        )
        rows.append(
            {
                **row,
                "scan": scan,
                "ready_to_queue": ready_to_queue,
                "capture_segment_count": len(capture_segments),
                "successful_capture_segment_count": len(successful_capture_segments),
                "segment_status_counts": (
                    segment_counts_by_scan_id.get(scan.id, {}) if scan else {}
                ),
                "event_counts": (
                    event_counts_by_scan_id.get(scan.id, _empty_text_event_counts())
                    if scan
                    else _empty_text_event_counts()
                ),
            }
        )
    return rows


def _parse_uuid_list(values):
    parsed = []
    for value in values:
        if not value:
            continue
        parsed.append(uuid.UUID(value))
    return parsed


def _hms(seconds):
    if seconds is None:
        return ""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _text_event_data_from_payload(payload):
    return TextEventData(
        frame_second=int(payload["frame_second"]),
        top_points=payload.get("top_points"),
        top_advantages=payload.get("top_advantages"),
        top_penalties=payload.get("top_penalties"),
        bottom_points=payload.get("bottom_points"),
        bottom_advantages=payload.get("bottom_advantages"),
        bottom_penalties=payload.get("bottom_penalties"),
        scoreboard_state=payload.get("scoreboard_state"),
        timer_state=payload.get("timer_state"),
        timer_value=payload.get("timer_value"),
        top_athlete_name=payload.get("top_athlete_name"),
        top_team_name=payload.get("top_team_name"),
        bottom_athlete_name=payload.get("bottom_athlete_name"),
        bottom_team_name=payload.get("bottom_team_name"),
        profile_id=payload.get("profile_id"),
        score_engine=payload.get("score_engine"),
        name_engine=payload.get("name_engine"),
        confidence=payload.get("confidence"),
        needs_review=bool(payload.get("needs_review")),
        evidence=payload.get("evidence"),
    )


def _worker_api_authorized():
    password = request.headers.get("X-Admin-Password")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        password = auth_header.removeprefix("Bearer ").strip()
    return password == ADMIN_PASSWORD


def _parse_uuid(value, field_name):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _run_import_task(task_id, args):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        env = os.environ.copy()
        env["IMPORT_NONINTERACTIVE"] = "1"

        process = subprocess.Popen(
            ["./import.sh"] + args,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        task.pid = process.pid
        db.session.commit()

        buffer = []
        last_flush = time.time()
        try:
            if process.stdout:
                for line in process.stdout:
                    buffer.append(line)
                    if len(buffer) >= 20 or time.time() - last_flush >= 1.0:
                        _append_task_log(task, "".join(buffer))
                        db.session.commit()
                        buffer = []
                        last_flush = time.time()

            return_code = process.wait()
            if buffer:
                _append_task_log(task, "".join(buffer))
            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


def _run_logged_process(task, cmd, env=None):
    process = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    task.pid = process.pid
    db.session.commit()

    buffer = []
    last_flush = time.time()
    if process.stdout:
        for line in process.stdout:
            buffer.append(line)
            if len(buffer) >= 20 or time.time() - last_flush >= 1.0:
                _append_task_log(task, "".join(buffer))
                db.session.commit()
                buffer = []
                last_flush = time.time()

    return_code = process.wait()
    if buffer:
        _append_task_log(task, "".join(buffer))
    task.pid = None
    db.session.commit()
    return return_code


def _run_set_winner_task(task_id, args):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        try:
            set_winner_cmd = ["python3", "scripts/set_winner.py"] + args
            _append_task_log(task, f"$ {' '.join(set_winner_cmd)}\n")
            db.session.commit()
            return_code = _run_logged_process(
                task, set_winner_cmd, env=os.environ.copy()
            )

            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


def _run_recompute_ranks_task(task_id, gi_mode):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        try:
            rank_flag = "--gi" if gi_mode == "gi" else "--nogi"
            recompute_cmd = [
                "python3",
                "scripts/recompute_ratings.py",
                "--rank-only",
                rank_flag,
            ]
            _append_task_log(task, f"$ {' '.join(recompute_cmd)}\n")
            db.session.commit()
            return_code = _run_logged_process(
                task, recompute_cmd, env=os.environ.copy()
            )

            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


def _run_update_result_medals_task(task_id, args):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        try:
            update_cmd = ["python3", "scripts/update_result_medals.py"] + args
            _append_task_log(task, f"$ {' '.join(update_cmd)}\n")
            db.session.commit()
            return_code = _run_logged_process(task, update_cmd, env=os.environ.copy())

            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


def _run_update_youtube_match_videos_task(task_id, args):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        try:
            update_cmd = ["python3", "scripts/update_youtube_match_videos.py"] + args
            _append_task_log(task, f"$ {' '.join(update_cmd)}\n")
            db.session.commit()
            return_code = _run_logged_process(task, update_cmd, env=os.environ.copy())

            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


# Simple authentication
@app.before_request
def require_login():
    if request.endpoint == "login" or request.endpoint == "static":
        return
    if request.path.startswith(WORKER_API_PREFIX):
        if _worker_api_authorized():
            return
        return jsonify({"error": "unauthorized"}), 401
    if "logged_in" not in session:
        return redirect(url_for("login"))


@app.after_request
def add_cache_control_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Invalid password")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/bjjcompsystem/tournaments")
def bjjcompsystem_tournaments():
    url = "https://www.bjjcompsystem.com/"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        select = soup.find("select", id="tournament_id")
        if not select:
            return jsonify({"error": "tournament select not found"}), 502
        options = []
        for option in select.find_all("option"):
            value = (option.get("value") or "").strip()
            label = option.get_text(strip=True)
            if value:
                options.append({"id": value, "name": label})
        return jsonify({"tournaments": options})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


def _is_http_url(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_media_coverage_date(raw_date):
    if not raw_date:
        return None
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def _media_coverage_form_values(form):
    return {
        "covered_at": (form.get("covered_at") or "").strip(),
        "coverage_type": (form.get("coverage_type") or "").strip(),
        "url": (form.get("url") or "").strip(),
        "title": (form.get("title") or "").strip(),
        "portuguese": form.get("portuguese") == "on",
    }


def _validate_media_coverage_values(values):
    errors = []
    covered_at = _parse_media_coverage_date(values["covered_at"])
    if covered_at is None:
        errors.append("Date must be a valid YYYY-MM-DD date.")
    if values["coverage_type"] not in MEDIA_COVERAGE_TYPES:
        errors.append(
            "Type must be Feature, News, Video, Podcast, Highlight, Technique, Interview, or Breakdown."
        )
    if not values["url"] or not _is_http_url(values["url"]):
        errors.append("URL must start with http:// or https://.")
    if not values["title"]:
        errors.append("Title is required.")
    return covered_at, errors


def _fetch_media_title(url):
    with requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
        allow_redirects=True,
        stream=True,
    ) as response:
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and (
            "text/html" not in content_type
            and "application/xhtml+xml" not in content_type
        ):
            raise ValueError("URL did not return an HTML page.")

        html_buffer = bytearray()
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            total_bytes += len(chunk)
            html_buffer.extend(chunk)
            if b"</title" in html_buffer.lower():
                break
            if total_bytes > MAX_MEDIA_TITLE_SCAN_BYTES:
                raise ValueError("No <title> found near the start of the HTML page.")

    soup = BeautifulSoup(bytes(html_buffer), "html.parser")
    title = soup.find("title")
    if not title:
        raise ValueError("No <title> found.")

    title_text = " ".join(title.get_text(" ", strip=True).split())
    if not title_text:
        raise ValueError("No title text found.")
    return title_text


@app.route("/api/media_title", methods=["POST"])
def media_title():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not _is_http_url(url):
        return jsonify({"error": "URL must start with http:// or https://."}), 400

    try:
        return jsonify({"title": _fetch_media_title(url)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/tasks")
def tasks_index():
    per_page = 10
    page = request.args.get("page", 1, type=int)
    selected_task_type = (request.args.get("task_type") or "all").strip()

    default_task_types = [
        "import_results",
        "set_match_winner",
        "recompute_ranks",
        "update_result_medals",
        "update_youtube_match_videos",
    ]
    db_task_types = [
        row[0]
        for row in db.session.query(BackgroundTask.task_type)
        .distinct()
        .order_by(BackgroundTask.task_type)
        .all()
        if row[0]
    ]
    task_types = sorted(set(default_task_types + db_task_types))

    task_query = BackgroundTask.query
    if selected_task_type != "all":
        task_query = task_query.filter(BackgroundTask.task_type == selected_task_type)

    total_tasks = task_query.count()
    total_pages = max(1, (total_tasks + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)

    tasks = (
        task_query.order_by(BackgroundTask.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    task_event_names = {}
    for task in tasks:
        event_name = None
        if task.params_json:
            try:
                params = json.loads(task.params_json)
                if isinstance(params, dict):
                    event_name = params.get("event_name") or params.get(
                        "tournament_name"
                    )
            except json.JSONDecodeError:
                pass
        task_event_names[task.id] = event_name

    return render_template(
        "tasks_index.html",
        tasks=tasks,
        task_event_names=task_event_names,
        page=page,
        total_pages=total_pages,
        selected_task_type=selected_task_type,
        task_types=task_types,
    )


@app.route("/tasks/unrecorded_winners")
def tasks_unrecorded_winners():
    archive_base_url = (
        "https://jiujitsu.net" if os.getenv("DATABASE_URL") else "http://localhost:5173"
    )
    return render_template(
        "tasks_unrecorded_winners.html", archive_base_url=archive_base_url
    )


@app.route("/livestream_frame_archives", methods=["GET", "POST"])
def livestream_frame_archives():
    message = request.args.get("message")
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        youtube_ids = request.form.getlist("selected_youtube_id")
        archive_ids = [
            archive.id
            for archive in LivestreamFrameArchive.query.filter(
                LivestreamFrameArchive.youtube_video_id.in_(youtube_ids)
            ).all()
        ]

        try:
            if action == "sync":
                result = sync_archives_from_livestreams(db.session)
                db.session.commit()
                message = (
                    f"Synced {result['discovered']} stream(s); "
                    f"created {result['created']} archive row(s)."
                )
            elif action == "queue_missing":
                sync_archives_from_livestreams(db.session)
                archives = LivestreamFrameArchive.query.filter(
                    LivestreamFrameArchive.status != "success"
                ).all()
                segment_count = 0
                for archive in archives:
                    segment_count += queue_archive_capture(db.session, archive)
                    recompute_archive_status(db.session, archive)
                db.session.commit()
                message = f"Queued {segment_count} segment(s)."
            elif action == "queue_selected":
                archives = []
                for youtube_id in youtube_ids:
                    archive, _ = get_or_create_archive(db.session, youtube_id)
                    archives.append(archive)
                if archive_ids:
                    archives.extend(
                        LivestreamFrameArchive.query.filter(
                            LivestreamFrameArchive.id.in_(archive_ids)
                        ).all()
                    )
                seen = set()
                segment_count = 0
                for archive in archives:
                    if archive.id in seen:
                        continue
                    seen.add(archive.id)
                    segment_count += queue_archive_capture(db.session, archive)
                    recompute_archive_status(db.session, archive)
                db.session.commit()
                message = f"Queued {segment_count} segment(s)."
            elif action == "retry_failed":
                segment_count = retry_failed_segments(db.session, archive_ids or None)
                db.session.commit()
                message = f"Requeued {segment_count} failed/cancelled segment(s)."
            elif action == "cancel":
                segment_count = cancel_queued_segments(db.session, archive_ids or None)
                db.session.commit()
                message = f"Cancelled {segment_count} queued/running segment(s)."
        except Exception as exc:
            db.session.rollback()
            error = str(exc)

    rows = get_archive_dashboard_rows(db.session)
    return render_template(
        "livestream_frame_archives.html",
        rows=rows,
        message=message,
        error=error,
        progress_label=archive_progress_label,
    )


@app.route("/livestream_frame_archives/<archive_id>", methods=["GET", "POST"])
def livestream_frame_archive_detail(archive_id):
    message = request.args.get("message")
    error = request.args.get("error")
    archive = LivestreamFrameArchive.query.get(uuid.UUID(archive_id))
    if not archive:
        return redirect(url_for("livestream_frame_archives"))

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "requeue_completed":
                segment_count = requeue_completed_segments(db.session, archive)
                db.session.commit()
                message = f"Requeued {segment_count} completed segment(s)."
                return redirect(
                    url_for(
                        "livestream_frame_archive_detail",
                        archive_id=archive.id,
                        message=message,
                    )
                )
        except Exception as exc:
            db.session.rollback()
            error = str(exc)

    segments = (
        LivestreamFrameCaptureSegment.query.filter_by(archive_id=archive.id)
        .order_by(LivestreamFrameCaptureSegment.start_second)
        .all()
    )
    usages = archive_usage_rows(db.session, archive.youtube_video_id)
    return render_template(
        "livestream_frame_archive_detail.html",
        archive=archive,
        segments=segments,
        usages=usages,
        message=message,
        error=error,
        canonical_url=canonical_youtube_url(archive.youtube_video_id),
        progress_label=archive_progress_label,
    )


@app.route("/livestream_frame_text_scans", methods=["GET", "POST"])
def livestream_frame_text_scans():
    message = request.args.get("message")
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        try:
            archive_ids = _parse_uuid_list(request.form.getlist("selected_archive_id"))
            scan_ids = [
                scan.id
                for scan in LivestreamFrameTextScan.query.filter(
                    LivestreamFrameTextScan.archive_id.in_(archive_ids)
                ).all()
            ]

            if action == "queue_ready":
                scan_archive_ids = [
                    row[0]
                    for row in db.session.query(LivestreamFrameTextScan.archive_id)
                ]
                successful_capture_archive_ids = [
                    row[0]
                    for row in db.session.query(
                        LivestreamFrameCaptureSegment.archive_id
                    )
                    .filter(LivestreamFrameCaptureSegment.status == "success")
                    .distinct()
                ]
                archives = (
                    LivestreamFrameArchive.query.filter(
                        LivestreamFrameArchive.status == "success",
                        ~LivestreamFrameArchive.id.in_(scan_archive_ids),
                        LivestreamFrameArchive.id.in_(successful_capture_archive_ids),
                    )
                    .order_by(LivestreamFrameArchive.created_at)
                    .all()
                )
                segment_count = 0
                for archive in archives:
                    segment_count += queue_text_scan(db.session, archive)
                db.session.commit()
                message = f"Queued {segment_count} text scan segment(s)."
            elif action == "queue_selected":
                archives = (
                    LivestreamFrameArchive.query.filter(
                        LivestreamFrameArchive.id.in_(archive_ids),
                        LivestreamFrameArchive.status == "success",
                    )
                    .order_by(LivestreamFrameArchive.created_at)
                    .all()
                )
                segment_count = 0
                for archive in archives:
                    segment_count += queue_text_scan(db.session, archive)
                db.session.commit()
                message = f"Queued {segment_count} text scan segment(s)."
            elif action == "retry_failed":
                segment_count = retry_failed_text_scan_segments(
                    db.session, scan_ids or None
                )
                db.session.commit()
                message = f"Requeued {segment_count} failed/cancelled segment(s)."
            elif action == "cancel":
                segment_count = cancel_queued_text_scan_segments(
                    db.session, scan_ids or None
                )
                db.session.commit()
                message = f"Cancelled {segment_count} queued/running segment(s)."
        except Exception as exc:
            db.session.rollback()
            error = str(exc)

    rows = _livestream_frame_text_scan_rows()
    ready_count = sum(1 for row in rows if row["ready_to_queue"])
    active_count = sum(
        1
        for row in rows
        if row["scan"] and row["scan"].status in {"queued", "running", "partial"}
    )
    return render_template(
        "livestream_frame_text_scans.html",
        rows=rows,
        ready_count=ready_count,
        active_count=active_count,
        message=message,
        error=error,
        progress_label=_text_scan_progress_label,
        segment_statuses=TEXT_SCAN_SEGMENT_STATUSES,
    )


@app.route("/livestream_frame_text_scans/<archive_id>", methods=["GET", "POST"])
def livestream_frame_text_scan_detail(archive_id):
    archive = LivestreamFrameArchive.query.get(uuid.UUID(archive_id))
    if not archive:
        return redirect(url_for("livestream_frame_text_scans"))

    scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one_or_none()
    if request.method == "POST":
        if not scan:
            return redirect(
                url_for(
                    "livestream_frame_text_scan_detail",
                    archive_id=archive.id,
                    error="No text scan found.",
                )
            )
        summary = link_completed_text_scan(db.session, scan)
        db.session.commit()
        if summary.skipped:
            return redirect(
                url_for(
                    "livestream_frame_text_scan_detail",
                    archive_id=archive.id,
                    error=f"Match relink skipped: {summary.skipped}.",
                )
            )
        return redirect(
            url_for(
                "livestream_frame_text_scan_detail",
                archive_id=archive.id,
                message=(
                    f"Recreated {summary.linked} match link(s) from "
                    f"{summary.windows} OCR window(s)."
                ),
            )
        )

    segments = []
    events = []
    event_counts = _empty_text_event_counts()
    segment_status_counts = {}
    if scan:
        segments = (
            LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id)
            .order_by(LivestreamFrameTextScanSegment.start_second)
            .all()
        )
        events = (
            LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
            .order_by(LivestreamFrameTextEvent.frame_second)
            .all()
        )
        event_counts = _text_event_counts_for_scan_ids([scan.id]).get(
            scan.id, event_counts
        )
        segment_status_counts = _text_scan_segment_status_counts([scan.id]).get(
            scan.id, {}
        )

    usages = archive_usage_rows(db.session, archive.youtube_video_id)
    event_rows = _text_event_display_rows(events, _linked_text_event_rows(events))
    return render_template(
        "livestream_frame_text_scan_detail.html",
        archive=archive,
        scan=scan,
        segments=segments,
        event_rows=event_rows,
        usages=usages,
        event_counts=event_counts,
        segment_status_counts=segment_status_counts,
        segment_statuses=TEXT_SCAN_SEGMENT_STATUSES,
        canonical_url=canonical_youtube_url(archive.youtube_video_id),
        progress_label=_text_scan_progress_label,
        time_label=_hms,
        message=request.args.get("message"),
        error=request.args.get("error"),
    )


@app.route(
    "/api/livestream_frame_text_scans/<archive_id>/events/<event_id>/captures/<crop_variant>"
)
def livestream_frame_text_event_capture(archive_id, event_id, crop_variant):
    try:
        archive_uuid = uuid.UUID(archive_id)
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        abort(404)

    crop_variants = {"scoreboard": "score", "timer": "timer"}
    crop_name = crop_variants.get(crop_variant)
    if crop_name is None:
        abort(404)

    event = db.session.get(LivestreamFrameTextEvent, event_uuid)
    if not event or event.archive_id != archive_uuid:
        abort(404)

    capture_segment = event.capture_segment
    if not capture_segment:
        abort(404)

    frame = S3FrameBatchProvider(
        [capture_segment], get_s3_client(), bucket_name
    ).get_frame(event.frame_second, crop_name)
    if frame is None:
        abort(404)

    download_name = (
        f"{event.archive.youtube_video_id}_{event.frame_second:09d}_{crop_variant}.jpg"
    )
    return send_file(
        io.BytesIO(frame),
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=download_name,
    )


@app.route(f"{WORKER_API_PREFIX}segments/claim", methods=["POST"])
def worker_claim_livestream_frame_segment():
    data = request.get_json(silent=True) or {}
    try:
        archive_id = _parse_uuid(data.get("archive_id"), "archive_id")
        background_task_id = _parse_uuid(
            data.get("background_task_id"), "background_task_id"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    segment = claim_next_segment(
        db.session,
        archive_id=archive_id,
        youtube_video_id=data.get("youtube_video_id"),
        background_task_id=background_task_id,
    )
    return jsonify({"segment": _segment_payload(segment)})


@app.route(
    f"{WORKER_API_PREFIX}archives/<archive_id>/probe_start",
    methods=["POST"],
)
def worker_start_livestream_frame_probe(archive_id):
    try:
        archive_uuid = uuid.UUID(archive_id)
    except ValueError:
        return jsonify({"error": "archive_id must be a UUID"}), 400

    archive = LivestreamFrameArchive.query.get(archive_uuid)
    if not archive:
        return jsonify({"error": "archive not found"}), 404

    data = request.get_json(silent=True) or {}
    archive.status = "probing"
    archive.frame_rate = data.get("frame_rate") or archive.frame_rate
    db.session.commit()
    return jsonify({"archive": _archive_payload(archive)})


@app.route(
    f"{WORKER_API_PREFIX}archives/<archive_id>/probe_complete",
    methods=["POST"],
)
def worker_complete_livestream_frame_probe(archive_id):
    try:
        archive_uuid = uuid.UUID(archive_id)
    except ValueError:
        return jsonify({"error": "archive_id must be a UUID"}), 400

    archive = LivestreamFrameArchive.query.get(archive_uuid)
    if not archive:
        return jsonify({"error": "archive not found"}), 404

    data = request.get_json(silent=True) or {}
    selected = data.get("selected") or {}
    info = {"duration": data.get("duration")}
    segment_seconds = data.get("segment_seconds") or DEFAULT_SEGMENT_SECONDS
    archive.frame_rate = data.get("frame_rate") or archive.frame_rate
    apply_probe_metadata(archive, info, selected)
    archive.yt_dlp_version = data.get("yt_dlp_version")
    created_segments = create_missing_segments(db.session, archive, segment_seconds)
    db.session.commit()
    return jsonify(
        {
            "archive": _archive_payload(archive),
            "created_segments": created_segments,
        }
    )


@app.route(
    f"{WORKER_API_PREFIX}segments/<segment_id>/complete",
    methods=["POST"],
)
def worker_complete_livestream_frame_segment(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    segment = LivestreamFrameCaptureSegment.query.get(segment_uuid)
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    data = request.get_json(silent=True) or {}
    status = data.get("status") or "success"
    if status not in {"success", "skipped"}:
        return jsonify({"error": "status must be success or skipped"}), 400

    segment.status = status
    segment.uploaded_frame_count = data.get(
        "uploaded_frame_count", segment.uploaded_frame_count
    )
    segment.sampled_frame_count = data.get(
        "sampled_frame_count", segment.sampled_frame_count
    )
    segment.last_uploaded_second = data.get(
        "last_uploaded_second", segment.last_uploaded_second
    )
    segment.batch_s3_key = data.get("batch_s3_key", segment.batch_s3_key)
    if data.get("batch_uploaded_at"):
        segment.batch_uploaded_at = datetime.utcnow()
    segment.last_error = None
    segment.finished_at = datetime.utcnow()
    recompute_archive_status(db.session, segment.archive)
    db.session.commit()
    return jsonify({"segment": _segment_payload(segment)})


@app.route(f"{WORKER_API_PREFIX}segments/<segment_id>/error", methods=["POST"])
def worker_error_livestream_frame_segment(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    segment = LivestreamFrameCaptureSegment.query.get(segment_uuid)
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    data = request.get_json(silent=True) or {}
    error = str(data.get("error") or "unknown error")
    segment.status = "error"
    segment.last_error = error
    segment.finished_at = datetime.utcnow()
    segment.archive.last_error = error
    recompute_archive_status(db.session, segment.archive)
    db.session.commit()
    return jsonify({"segment": _segment_payload(segment)})


@app.route("/api/livestream_frame_text_scans/queue", methods=["POST"])
def queue_livestream_frame_text_scans():
    data = request.get_json(silent=True) or {}
    archive_ids = data.get("archive_ids") or []
    youtube_video_ids = data.get("youtube_video_ids") or []
    parser_profile = data.get("parser_profile") or DEFAULT_PARSER_PROFILE
    score_engine = data.get("score_engine") or DEFAULT_SCORE_ENGINE
    name_engine = data.get("name_engine") or DEFAULT_NAME_ENGINE
    coarse_interval_seconds = (
        data.get("coarse_interval_seconds") or DEFAULT_COARSE_INTERVAL_SECONDS
    )

    archives_query = LivestreamFrameArchive.query.filter(
        LivestreamFrameArchive.status == "success"
    )
    filters = []
    if archive_ids:
        try:
            filters.append(
                LivestreamFrameArchive.id.in_(
                    [uuid.UUID(str(archive_id)) for archive_id in archive_ids]
                )
            )
        except ValueError:
            return jsonify({"error": "archive_ids must be UUIDs"}), 400
    if youtube_video_ids:
        filters.append(LivestreamFrameArchive.youtube_video_id.in_(youtube_video_ids))
    if filters:
        archives_query = archives_query.filter(or_(*filters))

    queued = 0
    scans = []
    for archive in archives_query.order_by(LivestreamFrameArchive.created_at).all():
        queued += queue_text_scan(
            db.session,
            archive,
            parser_profile=parser_profile,
            score_engine=score_engine,
            name_engine=name_engine,
            coarse_interval_seconds=coarse_interval_seconds,
        )
        scan = LivestreamFrameTextScan.query.filter_by(archive_id=archive.id).one()
        scans.append(scan)
    db.session.commit()
    return jsonify(
        {
            "queued_segments": queued,
            "scans": [_text_scan_payload(scan) for scan in scans],
        }
    )


@app.route("/api/livestream_frame_text_scans/retry", methods=["POST"])
def retry_livestream_frame_text_scans():
    data = request.get_json(silent=True) or {}
    try:
        scan_ids = [uuid.UUID(str(scan_id)) for scan_id in (data.get("scan_ids") or [])]
    except ValueError:
        return jsonify({"error": "scan_ids must be UUIDs"}), 400
    count = retry_failed_text_scan_segments(db.session, scan_ids or None)
    db.session.commit()
    return jsonify({"segments": count})


@app.route("/api/livestream_frame_text_scans/cancel", methods=["POST"])
def cancel_livestream_frame_text_scans():
    data = request.get_json(silent=True) or {}
    try:
        scan_ids = [uuid.UUID(str(scan_id)) for scan_id in (data.get("scan_ids") or [])]
    except ValueError:
        return jsonify({"error": "scan_ids must be UUIDs"}), 400
    count = cancel_queued_text_scan_segments(db.session, scan_ids or None)
    db.session.commit()
    return jsonify({"segments": count})


@app.route(
    f"{WORKER_API_PREFIX}text_scan_segments/claim",
    methods=["POST"],
)
def worker_claim_livestream_frame_text_scan_segment():
    data = request.get_json(silent=True) or {}
    try:
        scan_id = _parse_uuid(data.get("scan_id"), "scan_id")
        archive_id = _parse_uuid(data.get("archive_id"), "archive_id")
        background_task_id = _parse_uuid(
            data.get("background_task_id"), "background_task_id"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    segment = claim_next_text_scan_segment(
        db.session,
        scan_id=scan_id,
        archive_id=archive_id,
        youtube_video_id=data.get("youtube_video_id"),
        background_task_id=background_task_id,
    )
    return jsonify({"segment": _text_scan_segment_payload(segment)})


@app.route(
    f"{WORKER_API_PREFIX}text_scan_segments/<segment_id>/rescan",
    methods=["POST"],
)
def worker_rescan_livestream_frame_text_scan_segment(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    data = request.get_json(silent=True) or {}
    try:
        background_task_id = _parse_uuid(
            data.get("background_task_id"), "background_task_id"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    segment = prepare_text_scan_segment_rescan(
        db.session,
        segment_uuid,
        background_task_id=background_task_id,
    )
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    return jsonify({"segment": _text_scan_segment_payload(segment)})


@app.route(
    f"{WORKER_API_PREFIX}archives/<archive_id>/text_scan/reset",
    methods=["POST"],
)
def worker_reset_livestream_frame_text_scan(archive_id):
    try:
        archive_uuid = uuid.UUID(archive_id)
    except ValueError:
        return jsonify({"error": "archive_id must be a UUID"}), 400

    data = request.get_json(silent=True) or {}
    try:
        background_task_id = _parse_uuid(
            data.get("background_task_id"), "background_task_id"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        scan = reset_text_scan_for_archive(
            db.session,
            archive_uuid,
            background_task_id=background_task_id,
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 409
    if not scan:
        return jsonify({"error": "text scan not found"}), 404

    db.session.commit()
    segments = (
        LivestreamFrameTextScanSegment.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextScanSegment.start_second)
        .all()
    )
    return jsonify(
        {
            "scan": _text_scan_payload(scan),
            "segments": [
                _text_scan_segment_payload(segment, include_archive=False)
                for segment in segments
            ],
        }
    )


@app.route(
    f"{WORKER_API_PREFIX}text_scan_segments/<segment_id>/complete",
    methods=["POST"],
)
def worker_complete_livestream_frame_text_scan_segment(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    segment = LivestreamFrameTextScanSegment.query.get(segment_uuid)
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    data = request.get_json(silent=True) or {}
    events_payload = data.get("events") or []
    if not isinstance(events_payload, list):
        return jsonify({"error": "events must be a list"}), 400
    try:
        events = [_text_event_data_from_payload(item) for item in events_payload]
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"invalid event payload: {exc}"}), 400

    mark_text_scan_segment_success(db.session, segment, events)
    db.session.commit()
    stored_events = (
        LivestreamFrameTextEvent.query.filter_by(scan_segment_id=segment.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    return jsonify(
        {
            "segment": _text_scan_segment_payload(segment),
            "events": [_text_event_payload(event) for event in stored_events],
        }
    )


@app.route(
    f"{WORKER_API_PREFIX}text_scan_segments/<segment_id>/initial_state",
    methods=["GET"],
)
def worker_livestream_frame_text_scan_segment_initial_state(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    segment = LivestreamFrameTextScanSegment.query.get(segment_uuid)
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    state = reconstruct_text_state(
        db.session, segment.archive_id, before_second=segment.start_second
    )
    return jsonify({"state": state.__dict__})


@app.route(
    f"{WORKER_API_PREFIX}text_scan_segments/<segment_id>/error",
    methods=["POST"],
)
def worker_error_livestream_frame_text_scan_segment(segment_id):
    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        return jsonify({"error": "segment_id must be a UUID"}), 400

    segment = LivestreamFrameTextScanSegment.query.get(segment_uuid)
    if not segment:
        return jsonify({"error": "segment not found"}), 404

    data = request.get_json(silent=True) or {}
    error = str(data.get("error") or "unknown error")
    mark_text_scan_segment_error(db.session, segment, error)
    db.session.commit()
    return jsonify({"segment": _text_scan_segment_payload(segment)})


@app.route("/api/events/search")
def events_search():
    query = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 15
    if not page or page < 1:
        page = 1

    unrecorded_counts_subquery = (
        db.session.query(
            Match.event_id.label("event_id"),
            db.func.count(db.distinct(Match.id)).label("unrecorded_match_count"),
        )
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .filter(MatchParticipant.note.ilike(f"%{WINNER_NOT_RECORDED}%"))
        .group_by(Match.event_id)
        .subquery()
    )

    event_query = db.session.query(
        Event, unrecorded_counts_subquery.c.unrecorded_match_count
    ).join(
        unrecorded_counts_subquery, unrecorded_counts_subquery.c.event_id == Event.id
    )

    if query:
        normalized_search = normalize(query)
        tokens = [token for token in normalized_search.split() if token]
        for token in tokens:
            event_query = event_query.filter(Event.normalized_name.ilike(f"%{token}%"))

    total_results = event_query.count()
    total_pages = max(1, (total_results + per_page - 1) // per_page)
    page = min(page, total_pages)

    events = (
        event_query.order_by(
            unrecorded_counts_subquery.c.unrecorded_match_count.desc(),
            Event.name.asc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return jsonify(
        {
            "events": [
                {
                    "id": str(event.id),
                    "name": event.name,
                    "ibjjf_id": event.ibjjf_id,
                    "unrecorded_match_count": int(unrecorded_match_count or 0),
                }
                for event, unrecorded_match_count in events
            ],
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "total_results": total_results,
        }
    )


@app.route("/api/events/<event_id>/unrecorded_matches")
def event_unrecorded_matches(event_id):
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        return jsonify({"error": "invalid event id"}), 400

    event = Event.query.get(event_uuid)
    if not event:
        return jsonify({"error": "event not found"}), 404

    unrecorded_subquery = db.session.query(MatchParticipant.match_id).filter(
        MatchParticipant.note.ilike(f"%{WINNER_NOT_RECORDED}%")
    )
    matches = (
        Match.query.filter(Match.event_id == event_uuid)
        .filter(Match.id.in_(unrecorded_subquery))
        .order_by(Match.happened_at)
        .all()
    )

    response_matches = []
    for match in matches:
        participants = []
        for participant in match.participants:
            participants.append(
                {
                    "athlete_id": str(participant.athlete_id),
                    "athlete_name": participant.athlete.name,
                    "winner": participant.winner,
                    "note": participant.note or "",
                }
            )

        division = match.division
        response_matches.append(
            {
                "id": str(match.id),
                "happened_at": (
                    match.happened_at.isoformat() if match.happened_at else None
                ),
                "event_name": match.event.name,
                "division": {
                    "age": division.age,
                    "gender": division.gender,
                    "belt": division.belt,
                    "weight": division.weight,
                    "gi": division.gi,
                },
                "participants": participants,
            }
        )

    return jsonify(
        {
            "event": {
                "id": str(event.id),
                "name": event.name,
                "ibjjf_id": event.ibjjf_id,
            },
            "matches": response_matches,
        }
    )


@app.route("/tasks/unrecorded_winners/set_winner", methods=["POST"])
def set_unrecorded_match_winner():
    event_id_raw = request.form.get("event_id", "").strip()
    match_id_raw = request.form.get("match_id", "").strip()
    winner_id_raw = request.form.get("winner_id", "").strip()
    loser_no_show_raw = request.form.get("loser_no_show", "").strip().lower()
    loser_no_show = loser_no_show_raw in ["1", "true", "yes", "on"]

    if not event_id_raw or not match_id_raw or not winner_id_raw:
        return jsonify({"error": "Missing event, match, or winner ID."}), 400

    try:
        event_id = uuid.UUID(event_id_raw)
        match_id = uuid.UUID(match_id_raw)
        winner_id = uuid.UUID(winner_id_raw)
    except ValueError:
        return jsonify({"error": "Invalid UUID supplied."}), 400

    match = Match.query.get(match_id)
    if not match or match.event_id != event_id:
        return jsonify({"error": "Match not found for the selected event."}), 404

    participants = list(match.participants)
    winner_participant = None
    for participant in participants:
        if participant.athlete_id == winner_id:
            winner_participant = participant
            break
    if not winner_participant:
        return jsonify({"error": "Winner is not a participant in this match."}), 400

    if not any(
        WINNER_NOT_RECORDED in (participant.note or "") for participant in participants
    ):
        return jsonify({"error": "This match no longer has an unrecorded winner."}), 400

    params = {
        "event_id": str(match.event_id),
        "event_name": match.event.name,
        "match_id": str(match.id),
        "winner_athlete_id": str(winner_participant.athlete_id),
        "winner_athlete_name": winner_participant.athlete.name,
        "loser_no_show": loser_no_show,
    }

    task = BackgroundTask(
        task_type="set_match_winner",
        status="queued",
        params_json=json.dumps(params),
    )
    db.session.add(task)
    db.session.commit()

    task_args = [str(winner_participant.athlete_id), str(match.id)]
    if loser_no_show:
        task_args.append("--loser-no-show")

    thread = threading.Thread(
        target=_run_set_winner_task,
        args=(task.id, task_args),
        daemon=True,
    )
    thread.start()

    return jsonify(
        {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "message": (
                f"Created set winner task for {winner_participant.athlete.name}."
                if not loser_no_show
                else f"Created no-show disqualification task for {winner_participant.athlete.name}."
            ),
        }
    )


@app.route("/tasks/unrecorded_winners/recompute_ranks", methods=["POST"])
def recompute_ranks():
    gi_mode = (request.form.get("gi_mode") or "").strip().lower()
    if gi_mode not in ["gi", "nogi"]:
        return redirect(url_for("tasks_unrecorded_winners"))

    event_id_raw = (request.form.get("event_id") or "").strip()
    event_name = (request.form.get("event_name") or "").strip()
    params = {
        "gi_mode": gi_mode,
    }

    if event_name:
        params["event_name"] = event_name
    if event_id_raw:
        params["event_id"] = event_id_raw

    task = BackgroundTask(
        task_type="recompute_ranks",
        status="queued",
        params_json=json.dumps(params),
    )
    db.session.add(task)
    db.session.commit()

    thread = threading.Thread(
        target=_run_recompute_ranks_task,
        args=(task.id, gi_mode),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("tasks_index"))


@app.route("/tasks/import", methods=["GET", "POST"])
def tasks_import():
    error = None
    if request.method == "POST":
        tournament_id = request.form.get("tournament_id", "").strip()
        tournament_name = request.form.get("tournament_name", "").strip()
        gi_mode = request.form.get("gi_mode", "gi")
        retries = request.form.get("retries", "2").strip()
        allow_errors = request.form.get("allow_errors") == "on"
        incomplete = request.form.get("incomplete") == "on"
        slow_mode = request.form.get("slow_mode") == "on"

        if not tournament_id or not tournament_name:
            error = "Tournament ID and Tournament Name are required."
        else:
            try:
                retries_int = max(0, int(retries))
            except ValueError:
                error = "Retries must be a number."
                retries_int = 2

        if not error:
            args = [
                tournament_id,
                tournament_name,
                "--gi" if gi_mode == "gi" else "--nogi",
                "--retries",
                str(retries_int),
            ]
            if allow_errors:
                args.append("--allow-errors")
            if incomplete:
                args.append("--incomplete")
            if slow_mode:
                args.append("--slow-mode")

            params = {
                "tournament_id": tournament_id,
                "tournament_name": tournament_name,
                "gi_mode": gi_mode,
                "retries": retries_int,
                "allow_errors": allow_errors,
                "incomplete": incomplete,
                "slow_mode": slow_mode,
            }

            task = BackgroundTask(
                task_type="import_results",
                status="queued",
                params_json=json.dumps(params),
            )
            db.session.add(task)
            db.session.commit()

            thread = threading.Thread(
                target=_run_import_task, args=(task.id, args), daemon=True
            )
            thread.start()

            return redirect(url_for("task_detail", task_id=task.id))

    return render_template("tasks_import.html", error=error)


@app.route("/tasks/<task_id>")
def task_detail(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    params = {}
    if task and task.params_json:
        try:
            params = json.loads(task.params_json)
        except json.JSONDecodeError:
            params = {}
    return render_template("task_detail.html", task=task, params=params)


@app.route("/api/tasks/<task_id>")
def task_status(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "status": task.status,
            "exit_code": task.exit_code,
            "log_text": task.log_text or "",
            "created_at": _utc_iso(task.created_at),
            "started_at": _utc_iso(task.started_at),
            "finished_at": _utc_iso(task.finished_at),
        }
    )


@app.route("/tasks/<task_id>/mark_finished", methods=["POST"])
def task_mark_finished(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if task:
        task.status = "manual"
        task.finished_at = datetime.utcnow()
        task.pid = None
        db.session.commit()
    return redirect(url_for("task_detail", task_id=task_id))


@app.route("/tasks/<task_id>/cancel", methods=["POST"])
def task_cancel(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if not task:
        return redirect(url_for("tasks_index"))

    if task.status in ["running", "queued"]:
        pid = task.pid
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
                time.sleep(1.5)
                os.killpg(pid, 0)
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                _append_task_log(task, f"\nCancel error: {exc}\n")
        task.status = "cancelled"
        task.finished_at = datetime.utcnow()
        task.exit_code = None
        task.pid = None
        db.session.commit()

    return redirect(url_for("task_detail", task_id=task_id))


@app.route("/events/upcoming")
def upcoming_events():
    events = (
        RegistrationLink.query.filter(RegistrationLink.hidden.isnot(True))
        .filter(RegistrationLink.event_end_date > datetime.now() - timedelta(days=1))
        .order_by(RegistrationLink.event_end_date, RegistrationLink.name)
        .all()
    )
    return render_template("events_upcoming.html", events=events)


@app.route("/events/past")
def past_events():
    search_term = request.args.get("search", "")
    events = []
    if search_term:
        events = (
            Event.query.filter(
                Event.normalized_name.ilike(f"%{normalize(search_term)}%")
            )
            .filter(Event.ibjjf_id.isnot(None))
            .order_by(Event.name)
            .limit(30)
            .all()
        )
    return render_template("events_past.html", events=events)


@app.route("/event/livestreams", methods=["GET", "POST"])
def event_livestreams():
    event_id = request.args.get("id")
    name = request.args.get("name")
    error = None

    streams = (
        LiveStream.query.filter(LiveStream.event_id == event_id)
        .order_by(
            LiveStream.day_number,
            LiveStream.mat_number,
            LiveStream.start_hour,
            LiveStream.start_minute,
            LiveStream.start_seconds,
        )
        .all()
    )

    flo_event_tags = FloEventTag.query.filter(FloEventTag.event_id == event_id).all()

    flo_tag = ""
    if len(flo_event_tags) > 0:
        flo_tag = flo_event_tags[0].tag

    flo_mat_links = (
        FloMatLink.query.filter(FloMatLink.event_id == event_id)
        .order_by(FloMatLink.mat_number)
        .all()
    )

    if request.method == "POST":
        action = request.form.get("action")
        day_number = request.form.get("day_number", type=int)
        mat_number = request.form.get("mat_number", type=int)
        link = request.form.get("link", "").strip()
        stream_id = request.form.get("stream_id")
        start_time_str = request.form.get("start_time", "09:29:00")
        end_time_str = request.form.get("end_time", "23:00:00")
        drift_factor_str = request.form.get("drift_factor", "1.0000")
        hide_all_str = request.form.get("hide_all")
        try:
            drift_factor = float(drift_factor_str)
            if drift_factor < 0.0001 or drift_factor > 1.2000:
                raise ValueError
        except ValueError:
            drift_factor = 1.0000  # Default drift factor

        hide_all = bool(hide_all_str)

        try:
            comps = start_time_str.split(":")
            if len(comps) < 2 or len(comps) > 3:
                raise ValueError
            start_hour, start_minute = map(int, comps[:2])
            start_seconds = int(comps[2]) if len(comps) == 3 else 0
            if (
                start_hour < 0
                or start_hour > 23
                or start_minute < 0
                or start_minute > 59
                or start_seconds < 0
                or start_seconds > 59
            ):
                raise ValueError
        except ValueError:
            start_hour, start_minute, start_seconds = 9, 29, 0  # Default time

        try:
            comps = end_time_str.split(":")
            if len(comps) != 2:
                raise ValueError
            end_hour, end_minute = map(int, comps)
            if end_hour < 0 or end_hour > 23 or end_minute < 0 or end_minute > 59:
                raise ValueError
        except ValueError:
            end_hour, end_minute = 23, 0  # Default time

        # try to parse link with urllib so we can normalize it
        try:
            parsed_url = urlparse(link)
            if parsed_url.netloc == "youtu.be":
                video_id = parsed_url.path.lstrip("/")
                query = urlencode({"v": video_id})
                parsed_url = parsed_url._replace(
                    netloc="www.youtube.com", path="/watch", query=query
                )
                link = urlunparse(parsed_url)
        except Exception:
            pass  # if parsing fails, keep the original link

        if action == "add":
            new_stream = LiveStream(
                event_id=event_id,
                platform="youtube",
                mat_number=mat_number,
                day_number=day_number,
                start_hour=start_hour,
                start_minute=start_minute,
                start_seconds=start_seconds,
                end_hour=end_hour,
                end_minute=end_minute,
                drift_factor=drift_factor,
                hide_all=hide_all,
                link=link,
            )
            db.session.add(new_stream)
            db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))

        elif action == "edit":
            stream = LiveStream.query.get(uuid.UUID(stream_id))
            if stream:
                stream.day_number = day_number
                stream.mat_number = mat_number
                stream.start_hour = start_hour
                stream.start_minute = start_minute
                stream.start_seconds = start_seconds
                stream.end_hour = end_hour
                stream.end_minute = end_minute
                stream.drift_factor = drift_factor
                stream.hide_all = hide_all
                stream.link = link
                db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))
        elif action == "delete":
            stream = LiveStream.query.get(uuid.UUID(stream_id))
            if stream:
                db.session.delete(stream)
                db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))
        elif action == "update_flo_tag":
            flo_tag = request.form.get("flo_tag", "").strip()

            if len(flo_event_tags) > 1:
                for event_tag in flo_event_tags[1:]:
                    db.session.delete(event_tag)
                flo_event_tags = flo_event_tags[:1]

            if flo_tag:
                if len(flo_event_tags) > 0:
                    flo_event_tags[0].tag = flo_tag
                else:
                    new_flo_event_tag = FloEventTag(
                        event_id=event_id,
                        tag=flo_tag,
                    )
                    db.session.add(new_flo_event_tag)
            else:
                # If flo_tag is empty, delete existing tag if it exists
                if len(flo_event_tags) > 0:
                    for event_tag in flo_event_tags:
                        db.session.delete(event_tag)
            db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))
        elif action in (
            "add_flo_mat_link",
            "edit_flo_mat_link",
            "delete_flo_mat_link",
        ):
            flo_mat_link_id = request.form.get("flo_mat_link_id")
            flo_mat_number = request.form.get("flo_mat_number", type=int)
            flo_mat_link_url = request.form.get("flo_mat_link", "").strip()

            if action == "delete_flo_mat_link":
                if flo_mat_link_id:
                    fml = FloMatLink.query.get(uuid.UUID(flo_mat_link_id))
                    if fml:
                        db.session.delete(fml)
                        db.session.commit()
                return redirect(url_for("event_livestreams", id=event_id, name=name))

            if not flo_mat_number or flo_mat_number < 1 or not flo_mat_link_url:
                error = "Mat number and URL are required for Flo per-mat links."
            else:
                try:
                    if action == "add_flo_mat_link":
                        new_fml = FloMatLink(
                            event_id=event_id,
                            mat_number=flo_mat_number,
                            link=flo_mat_link_url,
                        )
                        db.session.add(new_fml)
                        db.session.commit()
                        return redirect(
                            url_for("event_livestreams", id=event_id, name=name)
                        )
                    else:
                        fml = FloMatLink.query.get(uuid.UUID(flo_mat_link_id))
                        if fml:
                            fml.mat_number = flo_mat_number
                            fml.link = flo_mat_link_url
                            db.session.commit()
                        return redirect(
                            url_for("event_livestreams", id=event_id, name=name)
                        )
                except IntegrityError:
                    db.session.rollback()
                    error = (
                        f"A Flo per-mat link already exists for mat {flo_mat_number}."
                    )

        streams = (
            LiveStream.query.filter(LiveStream.event_id == event_id)
            .order_by(
                LiveStream.day_number,
                LiveStream.mat_number,
                LiveStream.start_hour,
                LiveStream.start_minute,
                LiveStream.start_seconds,
            )
            .all()
        )
        flo_mat_links = (
            FloMatLink.query.filter(FloMatLink.event_id == event_id)
            .order_by(FloMatLink.mat_number)
            .all()
        )

    return render_template(
        "event_livestreams.html",
        event_id=event_id,
        event_name=name,
        streams=streams,
        error=error,
        flo_tag=flo_tag,
        flo_mat_links=flo_mat_links,
    )


@app.route("/flo-search-names", methods=["GET", "POST"])
def flo_search_names_settings():
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            athlete_name = request.form.get("athlete_name", "").strip()
            search_name = request.form.get("search_name", "").strip()
            comment = request.form.get("comment", "").strip() or None

            if not athlete_name or not search_name:
                error = "Athlete Name and Search Name are required."
            else:
                db.session.add(
                    FloSearchName(
                        athlete_name=athlete_name,
                        search_name=search_name,
                        comment=comment,
                    )
                )
                db.session.commit()
                return redirect(url_for("flo_search_names_settings"))

        elif action == "edit":
            mapping_id_raw = request.form.get("mapping_id")
            athlete_name = request.form.get("athlete_name", "").strip()
            search_name = request.form.get("search_name", "").strip()
            comment = request.form.get("comment", "").strip() or None

            if not mapping_id_raw:
                error = "Missing mapping ID."
            elif not athlete_name or not search_name:
                error = "Athlete Name and Search Name are required."
            else:
                mapping = FloSearchName.query.get(uuid.UUID(mapping_id_raw))
                if not mapping:
                    error = "Mapping not found."
                else:
                    mapping.athlete_name = athlete_name
                    mapping.search_name = search_name
                    mapping.comment = comment
                    db.session.commit()
                    return redirect(url_for("flo_search_names_settings"))

        elif action == "delete":
            mapping_id_raw = request.form.get("mapping_id")
            if not mapping_id_raw:
                error = "Missing mapping ID."
            else:
                mapping = FloSearchName.query.get(uuid.UUID(mapping_id_raw))
                if mapping:
                    db.session.delete(mapping)
                    db.session.commit()
                return redirect(url_for("flo_search_names_settings"))

    mappings = FloSearchName.query.order_by(
        FloSearchName.athlete_name.asc(),
        FloSearchName.search_name.asc(),
    ).all()
    return render_template(
        "flo_search_names_settings.html",
        mappings=mappings,
        error=error,
    )


@app.route("/team-name-mappings", methods=["GET", "POST"])
def team_name_mappings_settings():
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name_match = request.form.get("name_match", "").strip()
            mapped_name = request.form.get("mapped_name", "").strip()
            if not name_match or not mapped_name:
                error = "Name Match and Mapped Name are required."
            else:
                db.session.add(
                    TeamNameMapping(
                        name_match=name_match,
                        mapped_name=mapped_name,
                    )
                )
                db.session.commit()
                return redirect(url_for("team_name_mappings_settings"))

        elif action == "edit":
            mapping_id_raw = request.form.get("mapping_id")
            name_match = request.form.get("name_match", "").strip()
            mapped_name = request.form.get("mapped_name", "").strip()
            if not mapping_id_raw:
                error = "Missing mapping ID."
            elif not name_match or not mapped_name:
                error = "Name Match and Mapped Name are required."
            else:
                mapping = TeamNameMapping.query.get(uuid.UUID(mapping_id_raw))
                if not mapping:
                    error = "Mapping not found."
                else:
                    mapping.name_match = name_match
                    mapping.mapped_name = mapped_name
                    db.session.commit()
                    return redirect(url_for("team_name_mappings_settings"))

        elif action == "delete":
            mapping_id_raw = request.form.get("mapping_id")
            if not mapping_id_raw:
                error = "Missing mapping ID."
            else:
                mapping = TeamNameMapping.query.get(uuid.UUID(mapping_id_raw))
                if mapping:
                    db.session.delete(mapping)
                    db.session.commit()
                return redirect(url_for("team_name_mappings_settings"))

    mappings = TeamNameMapping.query.order_by(
        TeamNameMapping.name_match.asc(),
        TeamNameMapping.mapped_name.asc(),
    ).all()
    return render_template(
        "team_name_mappings_settings.html",
        mappings=mappings,
        error=error,
    )


@app.route("/athletes")
@app.route("/athletes", methods=["GET", "POST"])
def athletes():
    search_term = request.args.get("search", "")
    athletes = []
    if search_term:
        normalized_search = normalize(search_term)
        tokens = [token for token in normalized_search.split() if token]
        if tokens:
            query = Athlete.query
            for token in tokens:
                query = query.filter(
                    or_(
                        Athlete.normalized_name.ilike(f"%{token}%"),
                        Athlete.normalized_personal_name.ilike(f"%{token}%"),
                    )
                )
            athletes = (
                query.order_by(Athlete.personal_name.isnot(None).desc(), Athlete.name)
                .limit(30)
                .all()
            )
    return render_template("athletes.html", search_term=search_term, athletes=athletes)


@app.route("/athlete_matches")
def athlete_matches():
    athlete_id = request.args.get("id")
    athlete = None
    matches = []
    if athlete_id:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
        if athlete:
            matches = (
                Match.query.filter(
                    db.session.query(MatchParticipant)
                    .filter(
                        MatchParticipant.match_id == Match.id,
                        MatchParticipant.athlete_id == athlete.id,
                    )
                    .exists()
                )
                .order_by(Match.happened_at.desc())
                .all()
            )
            # Add opponent and athlete_participant fields to each match
            for match in matches:
                athlete_participant = None
                opponent = None
                for p in match.participants:
                    if p.athlete_id == athlete.id:
                        athlete_participant = p
                    else:
                        opponent = p
                match.athlete_participant = athlete_participant
                match.opponent = opponent
    return render_template("athlete_matches.html", athlete=athlete, matches=matches)


@app.route("/athlete_edit")
@app.route("/athlete_edit", methods=["GET", "POST"])
def athlete_edit():
    athlete_id = request.args.get("id")
    athlete = None
    message = None
    error_message = None
    photo_url = None
    if athlete_id:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
    if request.method == "POST" and athlete:
        instagram_profile = request.form.get("instagram_profile", "")
        # Sanitize input: remove URL and @
        instagram_profile = instagram_profile.strip()
        if instagram_profile.startswith("https://www.instagram.com/"):
            instagram_profile = instagram_profile[len("https://www.instagram.com/") :]
            instagram_profile = instagram_profile.rstrip("/")
        if instagram_profile.startswith("@"):
            instagram_profile = instagram_profile[1:]
        athlete.instagram_profile = instagram_profile

        personal_name = request.form.get("personal_name", "").strip()
        athlete.personal_name = personal_name if personal_name else None
        if personal_name:
            athlete.normalized_personal_name = normalize(personal_name)
        else:
            athlete.normalized_personal_name = None

        country = request.form.get("country", "").strip().lower()
        athlete.country = country[:2]

        country_note = request.form.get("country_note", "").strip()
        athlete.country_note = country_note if country_note else None

        country_note_pt = request.form.get("country_note_pt", "").strip()
        athlete.country_note_pt = country_note_pt if country_note_pt else None

        nickname_translation = request.form.get("nickname_translation", "").strip()
        athlete.nickname_translation = (
            nickname_translation if nickname_translation else None
        )

        bjjheroes_link = request.form.get("bjjheroes_link", "").strip()
        athlete.bjjheroes_link = bjjheroes_link if bjjheroes_link else None

        athlete.hide_full_name = request.form.get("hide_full_name") == "on"

        uploaded_photo = request.files.get("profile_photo")
        photo_updated = False
        if uploaded_photo and uploaded_photo.filename:
            photo_bytes = uploaded_photo.read()
            if not photo_bytes:
                error_message = "Selected photo file is empty."
            elif len(photo_bytes) > MAX_PROFILE_PHOTO_BYTES:
                error_message = "Photo is too large. Maximum size is 1MB."
            else:
                detected_content_type = detect_image_content_type(photo_bytes)
                if detected_content_type != "image/jpeg":
                    error_message = "Invalid photo format. Please upload a JPG image."
                else:
                    try:
                        s3_client = get_s3_client()
                        save_profile_photo_to_s3(
                            s3_client,
                            athlete,
                            photo_bytes,
                            content_type=detected_content_type,
                        )
                        photo_updated = True
                    except Exception:
                        app.logger.exception(
                            "Failed to upload profile photo for athlete %s", athlete.id
                        )
                        error_message = "Failed to upload profile photo."

        if error_message is None:
            db.session.commit()
            if photo_updated:
                message = "Athlete info and profile photo updated."
            else:
                message = "Athlete info updated."
        else:
            db.session.rollback()

    if athlete and athlete.profile_image_saved_at is not None:
        try:
            s3_client = get_s3_client()
            photo_url = get_public_photo_url(s3_client, athlete)
        except Exception:
            app.logger.exception(
                "Failed to generate profile photo URL for athlete %s", athlete.id
            )
            photo_url = None

    return render_template(
        "athlete_edit.html",
        athlete=athlete,
        message=message,
        error_message=error_message,
        photo_url=photo_url,
    )


@app.route("/athlete_media", methods=["GET", "POST"])
def athlete_media():
    athlete_id = request.values.get("id") or request.values.get("athlete_id")
    athlete = None
    media_coverage = []
    message = None
    error_message = None
    add_values = {
        "covered_at": date.today().strftime("%Y-%m-%d"),
        "coverage_type": "feature",
        "url": "",
        "title": "",
        "portuguese": False,
    }

    if athlete_id:
        try:
            athlete = Athlete.query.get(uuid.UUID(athlete_id))
        except ValueError:
            athlete = None

    if request.method == "POST" and athlete:
        action = (request.form.get("action") or "").strip()

        if action == "delete":
            media_id = request.form.get("media_id")
            try:
                media_item = AthleteMediaCoverage.query.get(uuid.UUID(media_id))
            except (TypeError, ValueError):
                media_item = None
            if media_item and media_item.athlete_id == athlete.id:
                db.session.delete(media_item)
                db.session.commit()
                message = "Media coverage deleted."
            else:
                error_message = "Media coverage item not found."

        elif action in {"add", "update"}:
            values = _media_coverage_form_values(request.form)
            covered_at, errors = _validate_media_coverage_values(values)
            if action == "add":
                add_values = values

            if errors:
                error_message = " ".join(errors)
            else:
                try:
                    if action == "add":
                        media_item = AthleteMediaCoverage(athlete_id=athlete.id)
                        db.session.add(media_item)
                        success_message = "Media coverage added."
                    else:
                        media_id = request.form.get("media_id")
                        media_item = AthleteMediaCoverage.query.get(uuid.UUID(media_id))
                        if not media_item or media_item.athlete_id != athlete.id:
                            raise ValueError("Media coverage item not found.")
                        success_message = "Media coverage updated."

                    media_item.covered_at = covered_at
                    media_item.coverage_type = values["coverage_type"]
                    media_item.url = values["url"]
                    media_item.title = values["title"]
                    media_item.portuguese = values["portuguese"]
                    db.session.commit()
                    message = success_message
                    add_values = {
                        "covered_at": date.today().strftime("%Y-%m-%d"),
                        "coverage_type": "feature",
                        "url": "",
                        "title": "",
                        "portuguese": False,
                    }
                except IntegrityError:
                    db.session.rollback()
                    error_message = (
                        "This athlete already has media coverage with that URL."
                    )
                except (TypeError, ValueError) as exc:
                    db.session.rollback()
                    error_message = str(exc)

    if athlete:
        media_coverage = (
            AthleteMediaCoverage.query.filter_by(athlete_id=athlete.id)
            .order_by(
                AthleteMediaCoverage.covered_at.desc(),
                AthleteMediaCoverage.created_at.desc(),
            )
            .all()
        )

    return render_template(
        "athlete_media.html",
        athlete=athlete,
        media_coverage=media_coverage,
        media_types=MEDIA_COVERAGE_TYPES,
        add_values=add_values,
        message=message,
        error_message=error_message,
    )


@app.route("/update_all_video_links", methods=["POST"])
def update_all_video_links():
    athlete_id = request.form.get("athlete_id")
    # Collect all video_link fields
    match_video_links = {}
    for key, value in request.form.items():
        if key.startswith("video_link_"):
            match_id = key[len("video_link_") :]
            match_video_links[match_id] = value.strip() if value else None
    # Update each match
    for match_id, video_link in match_video_links.items():
        match = Match.query.get(uuid.UUID(match_id))
        if match:
            match.video_link = video_link
    db.session.commit()
    return redirect(url_for("athlete_matches", id=athlete_id))


@app.route("/athlete_medals")
def athlete_medals():
    athlete_id = request.args.get("id")
    athlete = None
    medals = []
    if athlete_id:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
        if athlete:
            medals = (
                Medal.query.filter(Medal.athlete_id == athlete.id)
                .order_by(Medal.happened_at.desc())
                .all()
            )
    return render_template("athlete_medals.html", athlete=athlete, medals=medals)


@app.route("/update_all_medals", methods=["POST"])
def update_all_medals():
    athlete_id = request.form.get("athlete_id")
    error = None

    delete_id = (request.form.get("delete_medal_id") or "").strip()
    if delete_id:
        try:
            medal = Medal.query.get(uuid.UUID(delete_id))
        except ValueError:
            medal = None
        if medal:
            db.session.delete(medal)
            db.session.commit()
        return redirect(url_for("athlete_medals", id=athlete_id))

    for key, value in request.form.items():
        if not key.startswith("place_"):
            continue
        medal_id_raw = key[len("place_") :]
        try:
            medal = Medal.query.get(uuid.UUID(medal_id_raw))
        except ValueError:
            continue
        if not medal or medal.default_gold:
            continue
        try:
            new_place = int(value)
        except (TypeError, ValueError):
            error = "Place must be an integer."
            continue
        if new_place < 1:
            error = "Place must be 1 or greater."
            continue
        medal.place = new_place

    if error:
        db.session.rollback()
    else:
        db.session.commit()
    return redirect(url_for("athlete_medals", id=athlete_id))


# ---------------------------------------------------------------------------
# Missing medals scanner (Problem 2)
# ---------------------------------------------------------------------------

# medal_import_lib lives under /scripts; add it to sys.path so it imports.
_SCRIPTS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_PATH not in sys.path:
    sys.path.insert(0, _SCRIPTS_PATH)
import medal_import_lib as medal_lib  # noqa: E402
import youtube_match_import_lib as youtube_match_lib  # noqa: E402


def _parse_date_form(s, default):
    if not s:
        return default
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return default


@app.route("/missing_medals_scan", methods=["GET"])
def missing_medals_scan():
    now = datetime.utcnow()
    default_since = now - timedelta(days=14)
    since = _parse_date_form(request.args.get("since"), default_since)
    until = _parse_date_form(request.args.get("until"), now)
    until_eod = until.replace(hour=23, minute=59, second=59)
    has_scanned = "scan" in request.args
    latest_result_medal_scraped_at = db.session.query(
        func.max(ResultMedal.scraped_at)
    ).scalar()
    latest_update_task = (
        BackgroundTask.query.filter(BackgroundTask.task_type == "update_result_medals")
        .order_by(BackgroundTask.created_at.desc())
        .first()
    )

    events_data = []
    summary = {
        "events": 0,
        "matched": 0,
        "already_imported": 0,
        "ambiguous": 0,
        "no_match": 0,
        "no_division": 0,
    }
    if has_scanned:
        division_cache = medal_lib.build_division_cache(db.session)
        events = medal_lib.find_events_with_matches_in_range(
            db.session, since, until_eod
        )
        summary["events"] = len(events)
        for event in events:
            entries = medal_lib.scan_event_for_missing_medals(
                db.session, event, fuzzy=False, division_cache=division_cache
            )
            actionable = []
            for e in entries:
                summary[e["status"]] = summary.get(e["status"], 0) + 1
                if e["status"] in ("matched", "ambiguous", "no_match", "no_division"):
                    actionable.append(e)
            if actionable:
                events_data.append({"event": event, "entries": actionable})

    return render_template(
        "missing_medals_scan.html",
        since=since.strftime("%Y-%m-%d"),
        until=until.strftime("%Y-%m-%d"),
        has_scanned=has_scanned,
        events_data=events_data,
        summary=summary,
        latest_result_medal_scraped_at=latest_result_medal_scraped_at,
        latest_update_task=latest_update_task,
    )


@app.route("/missing_medals_scan/update_result_medals", methods=["POST"])
def missing_medals_scan_update_result_medals():
    year = str(datetime.utcnow().year)

    params = {
        "year": year,
        "source": "all",
    }
    task = BackgroundTask(
        task_type="update_result_medals",
        status="queued",
        params_json=json.dumps(params),
    )
    db.session.add(task)
    db.session.commit()

    thread = threading.Thread(
        target=_run_update_result_medals_task,
        args=(task.id, ["--year", year]),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("task_detail", task_id=task.id))


@app.route("/missing_medals_scan/import", methods=["POST"])
def missing_medals_scan_import():
    since = request.form.get("since", "")
    until = request.form.get("until", "")
    selections = request.form.getlist("match")  # values like "<rm_id>:<athlete_id>"

    imported = 0
    skipped = 0
    errors = []

    # Parse selections up front so we can bulk-fetch everything by id. Matched
    # rows arrive as checkboxes; ambiguous rows arrive as one radio value per
    # result medal. Enforce one athlete per result medal server-side too.
    selected_by_rm = {}  # rm_id -> athlete_id

    def _add_selection(rm_id, athlete_id, label):
        existing = selected_by_rm.get(rm_id)
        if existing is not None and existing != athlete_id:
            errors.append(f"Multiple athletes selected for result medal {rm_id}")
            return
        selected_by_rm[rm_id] = athlete_id

    for sel in selections:
        try:
            rm_id_raw, athlete_id_raw = sel.split(":", 1)
            _add_selection(uuid.UUID(rm_id_raw), uuid.UUID(athlete_id_raw), sel)
        except (ValueError, AttributeError):
            errors.append(f"Invalid selection: {sel}")

    for key, value in request.form.items():
        if not key.startswith("ambiguous_") or not value:
            continue
        try:
            rm_id = uuid.UUID(key[len("ambiguous_") :])
            athlete_id = uuid.UUID(value)
            _add_selection(rm_id, athlete_id, f"{key}={value}")
        except ValueError:
            errors.append(f"Invalid ambiguous selection: {key}={value}")

    pairs = list(selected_by_rm.items())  # (rm_id, athlete_id)
    rm_ids = list({p[0] for p in pairs})
    athlete_ids = list({p[1] for p in pairs})

    rms_by_id = (
        {
            rm.id: rm
            for rm in db.session.query(ResultMedal)
            .filter(ResultMedal.id.in_(rm_ids))
            .all()
        }
        if rm_ids
        else {}
    )
    athletes_by_id = (
        {a.id: a for a in Athlete.query.filter(Athlete.id.in_(athlete_ids)).all()}
        if athlete_ids
        else {}
    )

    # Resolve events once per unique (name, ibjjf_id). find_event itself is 1-3
    # queries; pulling it out of the per-medal loop is a major win when 1700
    # medals share a handful of tournaments.
    division_cache = medal_lib.build_division_cache(db.session)
    event_cache = {}  # (event_name, event_ibjjf_id) -> Event
    for rm in rms_by_id.values():
        key = (rm.event_name, rm.event_ibjjf_id)
        if key not in event_cache:
            event_cache[key] = medal_lib.find_event(db.session, *key)
    event_ids = [e.id for e in event_cache.values() if e is not None]

    # Bulk-prefetch teams by normalized name. find_or_create_team is otherwise
    # one query per unique raw name — hundreds of teams across a big batch.
    team_cache = {}  # raw_team_name -> Team
    raw_team_names = {rm.team_name for rm in rms_by_id.values()}
    normed_to_raw = {}
    for raw in raw_team_names:
        normed_to_raw.setdefault(normalize(raw), raw)
    if normed_to_raw:
        existing_teams = (
            db.session.query(Team)
            .filter(Team.normalized_name.in_(normed_to_raw.keys()))
            .all()
        )
        for t in existing_teams:
            team_cache[normed_to_raw[t.normalized_name]] = t
    for raw in raw_team_names:
        if raw not in team_cache:
            norm = normalize(raw)
            t = Team(name=raw, normalized_name=norm)
            db.session.add(t)
            team_cache[raw] = t
    if any(t for t in team_cache.values() if t.id is None):
        db.session.flush()  # one flush gets ids for all new teams

    # Bulk-prefetch existing medals to avoid medal_already_exists's per-row query.
    existing_set = set()
    if event_ids and athlete_ids:
        for a_id, e_id, d_id in (
            db.session.query(Medal.athlete_id, Medal.event_id, Medal.division_id)
            .filter(
                Medal.event_id.in_(event_ids),
                Medal.athlete_id.in_(athlete_ids),
            )
            .all()
        ):
            existing_set.add((a_id, e_id, d_id))

    # Bulk-prefetch the three lookups that compute_happened_at would otherwise
    # do one-at-a-time per medal.
    last_match_by_ae = {}
    last_match_by_e = {}
    last_medal_by_ae = {}
    if event_ids:
        if athlete_ids:
            for a_id, e_id, ts in (
                db.session.query(
                    MatchParticipant.athlete_id,
                    Match.event_id,
                    func.max(Match.happened_at),
                )
                .join(Match, Match.id == MatchParticipant.match_id)
                .filter(
                    MatchParticipant.athlete_id.in_(athlete_ids),
                    Match.event_id.in_(event_ids),
                )
                .group_by(MatchParticipant.athlete_id, Match.event_id)
                .all()
            ):
                last_match_by_ae[(a_id, e_id)] = ts
            for a_id, e_id, ts in (
                db.session.query(
                    Medal.athlete_id, Medal.event_id, func.max(Medal.happened_at)
                )
                .filter(
                    Medal.athlete_id.in_(athlete_ids),
                    Medal.event_id.in_(event_ids),
                )
                .group_by(Medal.athlete_id, Medal.event_id)
                .all()
            ):
                last_medal_by_ae[(a_id, e_id)] = ts
        for e_id, ts in (
            db.session.query(Match.event_id, func.max(Match.happened_at))
            .filter(Match.event_id.in_(event_ids))
            .group_by(Match.event_id)
            .all()
        ):
            last_match_by_e[e_id] = ts

    # default_gold: place-1 medals where no sibling place exists for the same
    # (event_name, division). One grouped query covers all place-1 selections.
    multi_sibling_keys = set()
    place1_event_names = {rm.event_name for rm in rms_by_id.values() if rm.place == 1}
    if place1_event_names:
        for en, div, cnt in (
            db.session.query(
                ResultMedal.event_name,
                ResultMedal.division,
                func.count(ResultMedal.id),
            )
            .filter(ResultMedal.event_name.in_(place1_event_names))
            .group_by(ResultMedal.event_name, ResultMedal.division)
            .all()
        ):
            if cnt > 1:
                multi_sibling_keys.add((en, div))

    def _happened_at(athlete_id, event):
        ts = last_match_by_ae.get((athlete_id, event.id))
        if ts is not None:
            return ts
        ts = last_match_by_e.get(event.id)
        if ts is not None:
            return ts
        ts = last_medal_by_ae.get((athlete_id, event.id))
        if ts is not None:
            return ts
        # Fallback to lib's name-based date inference; rare for recent-scan imports.
        return medal_lib.compute_happened_at(db.session, athlete_id, event, event.name)

    new_medals = []
    now = datetime.utcnow()
    for rm_id, athlete_id in pairs:
        rm = rms_by_id.get(rm_id)
        athlete = athletes_by_id.get(athlete_id)
        if not rm or not athlete:
            errors.append(f"Missing rm or athlete for {rm_id}:{athlete_id}")
            continue

        event = event_cache.get((rm.event_name, rm.event_ibjjf_id))
        if not event:
            errors.append(f"Event not found for {rm.event_name}")
            continue

        gi = not medal_lib.is_no_gi_event(event.name)
        division = medal_lib.parse_and_resolve_division(
            db.session, rm.division, gi, division_cache=division_cache
        )
        if not division:
            errors.append(f"Division not resolved: {rm.division} for {rm.event_name}")
            continue

        key = (athlete.id, event.id, division.id)
        if key in existing_set:
            skipped += 1
            continue
        # Also dedupe within this batch (rare, but safe).
        existing_set.add(key)

        team = team_cache.get(rm.team_name)
        default_gold = (
            rm.place == 1 and (rm.event_name, rm.division) not in multi_sibling_keys
        )

        new_medals.append(
            Medal(
                athlete_id=athlete.id,
                event_id=event.id,
                division_id=division.id,
                team_id=team.id,
                place=rm.place,
                happened_at=_happened_at(athlete.id, event),
                default_gold=default_gold,
                imported_via="recent_scan_manual",
                imported_at=now,
            )
        )
        imported += 1

    if new_medals:
        db.session.add_all(new_medals)

    if errors:
        db.session.rollback()
    else:
        db.session.commit()

    flash_msg = f"Imported {imported} medal(s)"
    if skipped:
        flash_msg += f"; skipped {skipped} duplicate(s)"
    if errors:
        flash_msg += f"; {len(errors)} error(s): " + "; ".join(errors[:3])
    session["scan_flash"] = flash_msg

    return redirect(url_for("missing_medals_scan", since=since, until=until, scan="1"))


# ---------------------------------------------------------------------------
# YouTube match video scanner
# ---------------------------------------------------------------------------


@app.route("/youtube_match_videos_scan", methods=["GET"])
def youtube_match_videos_scan():
    now = datetime.utcnow()
    default_since = now - timedelta(days=14)
    since = _parse_date_form(request.args.get("since"), default_since)
    until = _parse_date_form(request.args.get("until"), now)
    until_eod = until.replace(hour=23, minute=59, second=59)
    has_scanned = "scan" in request.args
    latest_youtube_scraped_at = db.session.query(
        func.max(YoutubeMatchVideo.scraped_at)
    ).scalar()
    latest_update_task = (
        BackgroundTask.query.filter(
            BackgroundTask.task_type == "update_youtube_match_videos"
        )
        .order_by(BackgroundTask.created_at.desc())
        .first()
    )

    entries = []
    summary = {
        "videos": 0,
        "matched": 0,
        "ambiguous": 0,
        "already_imported": 0,
        "conflict": 0,
        "no_match": 0,
        "no_event": 0,
        "event_review": 0,
        "unparseable": 0,
    }
    if has_scanned:
        entries = youtube_match_lib.scan_youtube_match_videos(
            db.session, since, until_eod
        )
        summary["videos"] = len(entries)
        for entry in entries:
            summary[entry["status"]] = summary.get(entry["status"], 0) + 1

    return render_template(
        "youtube_match_videos_scan.html",
        since=since.strftime("%Y-%m-%d"),
        until=until.strftime("%Y-%m-%d"),
        has_scanned=has_scanned,
        entries=entries,
        summary=summary,
        latest_youtube_scraped_at=latest_youtube_scraped_at,
        latest_update_task=latest_update_task,
    )


@app.route("/youtube_match_videos_scan/update", methods=["POST"])
def youtube_match_videos_scan_update():
    source = request.form.get("source", "auto")
    if source not in ("auto", "rss", "channel"):
        source = "auto"
    try:
        pages = max(1, min(20, int(request.form.get("pages", "2"))))
    except ValueError:
        pages = 2

    args = ["--source", source]
    params = {"source": source, "pages": pages}
    if source in ("auto", "channel"):
        args.extend(["--pages", str(pages)])

    task = BackgroundTask(
        task_type="update_youtube_match_videos",
        status="queued",
        params_json=json.dumps(params),
    )
    db.session.add(task)
    db.session.commit()

    thread = threading.Thread(
        target=_run_update_youtube_match_videos_task,
        args=(task.id, args),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("task_detail", task_id=task.id))


@app.route("/youtube_match_videos_scan/import", methods=["POST"])
def youtube_match_videos_scan_import():
    since = request.form.get("since", "")
    until = request.form.get("until", "")
    selected_by_video = {}
    errors = []

    def _add_selection(video_id, match_id):
        existing = selected_by_video.get(video_id)
        if existing is not None and existing != match_id:
            errors.append(f"Multiple matches selected for video {video_id}")
            return
        selected_by_video[video_id] = match_id

    for sel in request.form.getlist("match"):
        try:
            video_id_raw, match_id_raw = sel.split(":", 1)
            _add_selection(uuid.UUID(video_id_raw), uuid.UUID(match_id_raw))
        except (ValueError, AttributeError):
            errors.append(f"Invalid selection: {sel}")

    for key, value in request.form.items():
        if not key.startswith("ambiguous_") or not value:
            continue
        try:
            video_id = uuid.UUID(key[len("ambiguous_") :])
            match_id = uuid.UUID(value)
            _add_selection(video_id, match_id)
        except ValueError:
            errors.append(f"Invalid ambiguous selection: {key}={value}")

    imported = 0
    skipped = 0
    if errors:
        db.session.rollback()
    else:
        imported, skipped, import_errors = (
            youtube_match_lib.import_youtube_match_video_links(
                db.session, selected_by_video.items()
            )
        )
        errors.extend(import_errors)

    flash_msg = f"Imported {imported} video link(s)"
    if skipped:
        flash_msg += f"; skipped {skipped}"
    if errors:
        flash_msg += f"; {len(errors)} error(s): " + "; ".join(errors[:3])
    session["youtube_scan_flash"] = flash_msg

    return redirect(
        url_for("youtube_match_videos_scan", since=since, until=until, scan="1")
    )


# ---------------------------------------------------------------------------
# Per-athlete historical medal search (Problem 1, manual UI)
# ---------------------------------------------------------------------------


@app.route("/athlete_medals/find_missing")
def athlete_medals_find_missing():
    athlete_id = request.args.get("id", "")
    query_name = request.args.get("q", "").strip()
    has_searched = "q" in request.args

    try:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
    except (ValueError, TypeError):
        athlete = None
    if not athlete:
        return redirect(url_for("athletes"))

    if not query_name:
        query_name = athlete.name

    candidates = []
    if has_searched:
        from rapidfuzz import fuzz, process

        # Bound the work: require the first AND last 3+-char tokens of the
        # query to both appear in the candidate's name (substring). This
        # mirrors the first/last identity guard used elsewhere — it keeps
        # "Carlos Gracie" → "Carlos Eduardo Gracie" matches but drops the
        # flood of unrelated rows that share a single common token.
        normalized_q = medal_lib.normalize(query_name)
        tokens = [t for t in normalized_q.split() if len(t) >= 3]
        rm_query = db.session.query(medal_lib.ResultMedal)
        if tokens:
            from sqlalchemy import func

            anchor_tokens = {tokens[0], tokens[-1]} if len(tokens) > 1 else {tokens[0]}
            for t in anchor_tokens:
                rm_query = rm_query.filter(
                    func.lower(medal_lib.ResultMedal.athlete_name).contains(t)
                )

        candidate_rms = rm_query.all()
        name_to_rows = {}
        for rm in candidate_rms:
            name_to_rows.setdefault(rm.athlete_name, []).append(rm)
        all_names = list(name_to_rows.keys())

        if all_names:
            scored = process.extract(
                query_name, all_names, scorer=fuzz.token_ratio, limit=25
            )
        else:
            scored = []

        # Pre-cache existing medals for this athlete (event_id, division_id).
        existing_pairs = set(
            (m.event_id, m.division_id)
            for m in Medal.query.filter(Medal.athlete_id == athlete.id).all()
        )

        event_when_cache = {}

        for cand_name, score, _ in scored:
            if score < 75:
                break
            for rm in name_to_rows[cand_name]:
                division_parts = medal_lib.parse_division_parts(rm.division)
                if not division_parts:
                    candidates.append(
                        {
                            "rm": rm,
                            "score": score,
                            "division": None,
                            "event": None,
                            "status": "no_division",
                            "checkable": False,
                        }
                    )
                    continue
                belt, age, gender, _weight = division_parts
                gi = not medal_lib.is_no_gi_event(rm.event_name)
                division = medal_lib.parse_and_resolve_division(
                    db.session, rm.division, gi
                )
                event = medal_lib.find_event(
                    db.session, rm.event_name, rm.event_ibjjf_id
                )
                tentative_date = (
                    medal_lib.tentative_event_date(
                        db.session, rm.event_name, event=event, cache=event_when_cache
                    )
                    or datetime.utcnow()
                )
                belt_ok = medal_lib.medal_is_plausible(
                    db.session, athlete.id, belt, tentative_date
                )
                gender_ok = medal_lib.gender_is_plausible(
                    db.session, athlete.id, gender
                )
                age_ok = medal_lib.age_is_plausible(
                    db.session, athlete.id, age, tentative_date
                )
                advisory = False
                if division and event and (event.id, division.id) in existing_pairs:
                    status, checkable = "duplicate", False
                elif not gender_ok:
                    status, checkable = "gender_mismatch", False
                elif not division:
                    status, checkable = "no_division", False
                elif not age_ok:
                    status, checkable, advisory = "age_mismatch", True, True
                elif not belt_ok:
                    status, checkable, advisory = "belt_mismatch", True, True
                else:
                    status, checkable = "ok", True
                candidates.append(
                    {
                        "rm": rm,
                        "score": score,
                        "division": division,
                        "event": event,
                        "status": status,
                        "checkable": checkable,
                        "advisory": advisory,
                    }
                )

        candidates.sort(key=lambda c: -c["score"])

    return render_template(
        "athlete_medals_find_missing.html",
        athlete=athlete,
        query_name=query_name,
        candidates=candidates,
        has_searched=has_searched,
    )


@app.route("/athlete_medals/import_candidates", methods=["POST"])
def athlete_medals_import_candidates():
    athlete_id = request.form.get("athlete_id", "")
    try:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
    except (ValueError, TypeError):
        athlete = None
    if not athlete:
        return redirect(url_for("athletes"))

    selections = request.form.getlist("rm_id")
    imported = 0
    errors = []

    for rm_id_raw in selections:
        try:
            rm_id = uuid.UUID(rm_id_raw)
        except ValueError:
            errors.append(f"bad rm_id: {rm_id_raw}")
            continue
        rm = db.session.query(medal_lib.ResultMedal).get(rm_id)
        if not rm:
            errors.append(f"missing rm: {rm_id_raw}")
            continue
        event = medal_lib.find_event(db.session, rm.event_name, rm.event_ibjjf_id)
        if event is None:
            try:
                event = medal_lib.create_medals_only_event(db.session, rm.event_name)
            except ValueError as e:
                errors.append(f"event for {rm.event_name}: {e}")
                continue
        gi = not medal_lib.is_no_gi_event(event.name)
        division = medal_lib.parse_and_resolve_division(db.session, rm.division, gi)
        if not division:
            errors.append(f"division for {rm.event_name}: {rm.division}")
            continue
        if medal_lib.medal_already_exists(
            db.session, athlete.id, event.id, division.id
        ):
            continue
        team = medal_lib.find_or_create_team(db.session, rm.team_name)
        happened_at = medal_lib.compute_happened_at(
            db.session, athlete.id, event, event.name
        )
        default_gold = medal_lib.compute_default_gold(db.session, rm)
        medal_lib.insert_medal(
            db.session,
            athlete_id=athlete.id,
            event_id=event.id,
            division_id=division.id,
            team_id=team.id,
            place=rm.place,
            happened_at=happened_at,
            default_gold=default_gold,
            imported_via="historical_manual",
        )
        imported += 1

    if errors:
        db.session.rollback()
    else:
        db.session.commit()

    msg = f"Imported {imported} medal(s) for {athlete.name}"
    if errors:
        msg += f"; {len(errors)} error(s): " + "; ".join(errors[:3])
    session["medal_find_flash"] = msg

    return redirect(url_for("athlete_medals", id=str(athlete.id)))


application = app

if __name__ == "__main__":
    app.run()
