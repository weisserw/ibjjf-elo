#!/usr/bin/env python3
"""Scan archived livestream frame crops for sparse scoreboard/timer text events."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from extensions import db  # noqa: E402
from livestream_frame_text_scan import (  # noqa: E402
    DEFAULT_COARSE_INTERVAL_SECONDS,
    DEFAULT_NAME_ENGINE,
    DEFAULT_PARSER_PROFILE,
    DEFAULT_SCORE_ENGINE,
    S3FrameBatchProvider,
    TextState,
    mark_text_scan_segment_error,
    mark_text_scan_segment_success,
    prepare_text_scan_segment_rescan,
    reconstruct_text_state,
    reset_text_scan_for_archive,
    scan_frame_text_segment,
    claim_next_text_scan_segment,
)
from livestream_frame_text_ocr import build_parser, validate_ocr_engines  # noqa: E402
from models import LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


ADMIN_URL_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_URL"
ADMIN_PASSWORD_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_PASSWORD"


class ApiObject:
    def __init__(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                value = ApiObject(value)
            elif isinstance(value, list):
                value = [
                    ApiObject(item) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)

    def update_from(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                current = getattr(self, key, None)
                if isinstance(current, ApiObject):
                    current.update_from(value)
                    value = current
                else:
                    value = ApiObject(value)
            elif isinstance(value, list):
                value = [
                    ApiObject(item) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)


class LocalTextScanState:
    def claim_next_segment(
        self,
        scan_id=None,
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        return claim_next_text_scan_segment(
            db.session,
            scan_id=scan_id,
            archive_id=archive_id,
            youtube_video_id=youtube_video_id,
            background_task_id=background_task_id,
        )

    def rescan_segment(self, segment_id, background_task_id=None):
        return prepare_text_scan_segment_rescan(
            db.session,
            segment_id,
            background_task_id=background_task_id,
        )

    def reset_archive(self, archive_id, background_task_id=None):
        scan = reset_text_scan_for_archive(
            db.session,
            archive_id,
            background_task_id=background_task_id,
        )
        db.session.commit()
        return scan

    def capture_segments_for_archive(self, archive_id):
        return (
            LivestreamFrameCaptureSegment.query.filter_by(
                archive_id=archive_id, status="success"
            )
            .order_by(LivestreamFrameCaptureSegment.start_second)
            .all()
        )

    def initial_state_for_segment(self, segment):
        return reconstruct_text_state(
            db.session, segment.archive_id, before_second=segment.start_second
        )

    def mark_success(self, segment, events):
        mark_text_scan_segment_success(db.session, segment, events)
        db.session.commit()

    def mark_error(self, segment, error: str):
        mark_text_scan_segment_error(db.session, segment, error)
        db.session.commit()


class AdminApiTextScanState:
    def __init__(self, base_url: str, password: str, session=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.password = password
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Admin-Password"] = self.password
        response = self.session.request(
            method,
            urljoin(self.base_url, path.lstrip("/")),
            headers=headers,
            timeout=60,
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = payload.get("error") or response.text
            raise RuntimeError(
                f"admin API {method} {path} failed "
                f"with HTTP {response.status_code}: {message}"
            )
        return payload

    def claim_next_segment(
        self,
        scan_id=None,
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        payload = self._request(
            "POST",
            "/api/livestream_frame_archives/worker/text_scan_segments/claim",
            json={
                "scan_id": str(scan_id) if scan_id else None,
                "archive_id": str(archive_id) if archive_id else None,
                "youtube_video_id": youtube_video_id,
                "background_task_id": (
                    str(background_task_id) if background_task_id else None
                ),
            },
        )
        segment = payload.get("segment")
        return ApiObject(segment) if segment else None

    def rescan_segment(self, segment_id, background_task_id=None):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment_id}/rescan",
            json={
                "background_task_id": (
                    str(background_task_id) if background_task_id else None
                ),
            },
        )
        segment = payload.get("segment")
        return ApiObject(segment) if segment else None

    def reset_archive(self, archive_id, background_task_id=None):
        payload = self._request(
            "POST",
            (
                "/api/livestream_frame_archives/worker/"
                f"archives/{archive_id}/text_scan/reset"
            ),
            json={
                "background_task_id": (
                    str(background_task_id) if background_task_id else None
                ),
            },
        )
        scan = payload.get("scan")
        return ApiObject(scan) if scan else None

    def capture_segments_for_archive(self, archive_id):
        raise RuntimeError("admin API segments include archive_capture_segments")

    def initial_state_for_segment(self, segment):
        payload = self._request(
            "GET",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/initial_state",
        )
        return TextState(**payload["state"])

    def mark_success(self, segment, events):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/complete",
            json={"events": [event_payload(event) for event in events]},
        )
        segment.update_from(payload["segment"])

    def mark_error(self, segment, error: str):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/error",
            json={"error": error},
        )
        segment.update_from(payload["segment"])


def _load_app():
    import app as app_module

    return app_module.app


def log(message: str):
    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    print(f"{timestamp}Z {message}", file=sys.stderr, flush=True)


def event_payload(event):
    payload = asdict(event)
    payload["evidence"] = payload.pop("evidence")
    return payload


def provider_for_segment(segment, state, s3_client, bucket: str):
    capture_segments = getattr(segment, "archive_capture_segments", None)
    if capture_segments is None:
        capture_segments = state.capture_segments_for_archive(segment.archive_id)
    return S3FrameBatchProvider(capture_segments, s3_client, bucket)


def process_segment(segment, state, parser, s3_client, bucket: str):
    initial_state = state.initial_state_for_segment(segment)
    provider = provider_for_segment(segment, state, s3_client, bucket)
    interval = (
        getattr(getattr(segment, "scan", None), "coarse_interval_seconds", None)
        or DEFAULT_COARSE_INTERVAL_SECONDS
    )
    log(
        f"Scanning text segment id={segment.id} "
        f"archive_id={segment.archive_id} "
        f"range={segment.start_second}-{segment.end_second} "
        f"interval={interval}"
    )

    def debug_scan(message: str):
        log(f"Text scan segment id={segment.id}: {message}")

    events = scan_frame_text_segment(
        provider,
        parser,
        segment.start_second,
        segment.end_second,
        initial_state=initial_state,
        coarse_interval_seconds=interval,
        debug_callback=debug_scan,
    )
    state.mark_success(segment, events)
    log(f"Text scan segment success id={segment.id} events={len(events)}")


def run(args, state=None) -> int:
    if args.rescan_from_start and not args.archive_id:
        print(
            "--archive-id is required when --rescan-from-start is set",
            file=sys.stderr,
        )
        return 2
    if args.rescan_from_start and args.segment_id:
        print(
            "--rescan-from-start cannot be combined with --segment-id",
            file=sys.stderr,
        )
        return 2

    validate_ocr_engines(args.score_engine, args.name_engine)
    parser = build_parser(args.parser_profile, args.score_engine, args.name_engine)
    if state is None:
        state = LocalTextScanState()
    if not bucket_name:
        raise RuntimeError("S3_BUCKET is not configured")
    s3_client = get_s3_client()

    background_task_id = (
        uuid.UUID(args.background_task_id) if args.background_task_id else None
    )
    if args.rescan_from_start:
        archive_id = uuid.UUID(args.archive_id)
        scan = state.reset_archive(archive_id, background_task_id=background_task_id)
        if not scan:
            print(f"Livestream frame text scan not found for archive: {archive_id}")
            return 0
        log(f"Reset text scan archive_id={archive_id} for rescan from start")

    if args.segment_id:
        segment_id = uuid.UUID(args.segment_id)
        segment = state.rescan_segment(
            segment_id,
            background_task_id=background_task_id,
        )
        if not segment:
            print(f"Livestream frame text scan segment not found: {segment_id}")
            return 0
        try:
            process_segment(segment, state, parser, s3_client, bucket_name)
        except Exception as exc:
            state.mark_error(segment, str(exc))
            print(f"Text scan segment {segment.id} failed: {exc}", file=sys.stderr)
            return 1
        return 0

    processed = 0
    while processed < args.max_segments:
        archive_id = uuid.UUID(args.archive_id) if args.archive_id else None
        segment = state.claim_next_segment(
            archive_id=archive_id,
            youtube_video_id=args.youtube_id,
            background_task_id=background_task_id,
        )
        if not segment:
            print("No claimable livestream frame text scan segments.")
            return 0

        try:
            process_segment(segment, state, parser, s3_client, bucket_name)
            processed += 1
        except Exception as exc:
            state.mark_error(segment, str(exc))
            print(f"Text scan segment {segment.id} failed: {exc}", file=sys.stderr)
            return 1

        if not args.claim_next:
            return 0
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment-id")
    parser.add_argument("--rescan-from-start", action="store_true")
    parser.add_argument("--archive-id")
    parser.add_argument("--youtube-id")
    parser.add_argument("--claim-next", action="store_true")
    parser.add_argument("--max-segments", type=int, default=1)
    parser.add_argument("--parser-profile", default=DEFAULT_PARSER_PROFILE)
    parser.add_argument("--score-engine", default=DEFAULT_SCORE_ENGINE)
    parser.add_argument("--name-engine", default=DEFAULT_NAME_ENGINE)
    parser.add_argument("--background-task-id")
    parser.add_argument(
        "--admin-url",
        default=os.environ.get(ADMIN_URL_ENV_VAR),
        help=(
            "Admin app base URL for REST-backed state, defaults to "
            f"${ADMIN_URL_ENV_VAR}"
        ),
    )
    parser.add_argument(
        "--admin-password",
        default=(
            os.environ.get(ADMIN_PASSWORD_ENV_VAR) or os.environ.get("ADMIN_PASSWORD")
        ),
        help=(
            "Admin password for REST-backed state, defaults to "
            f"${ADMIN_PASSWORD_ENV_VAR} or $ADMIN_PASSWORD"
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.admin_url:
        if not args.admin_password:
            print(
                "--admin-password or LIVESTREAM_ARCHIVE_ADMIN_PASSWORD is required "
                "when --admin-url is set",
                file=sys.stderr,
            )
            return 2
        return run(args, AdminApiTextScanState(args.admin_url, args.admin_password))

    app = _load_app()
    with app.app_context():
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
