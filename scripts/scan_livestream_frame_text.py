#!/usr/bin/env python3
"""Scan archived livestream frame crops for sparse scoreboard/timer text events."""

from __future__ import annotations

import argparse
import os
import re
import shutil
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
    DEFAULT_PARSER_PROFILE,
    DEFAULT_SCORE_ENGINE,
    FrameReading,
    S3FrameBatchProvider,
    TextState,
    mark_text_scan_segment_error,
    mark_text_scan_segment_success,
    reconstruct_text_state,
    scan_frame_text_segment,
    claim_next_text_scan_segment,
)
from models import LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


ADMIN_URL_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_URL"
ADMIN_PASSWORD_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_PASSWORD"
SUPPORTED_ENGINES = ("none", "tesseract", "paddle")


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


class EmptyTextParser:
    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        return FrameReading(frame_second=frame_second, score_engine="none")


class TesseractTextParser:
    def __init__(self, parser_profile: str, score_engine: str, name_engine: str | None):
        self.parser_profile = parser_profile
        self.score_engine = score_engine
        self.name_engine = name_engine
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

    def _image_from_bytes(self, image_bytes):
        if not image_bytes:
            return None
        from PIL import Image
        import io

        return Image.open(io.BytesIO(image_bytes))

    def _ocr(self, image, config: str = "") -> str:
        if image is None:
            return ""
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip()

    def _parse_timer(self, text: str) -> tuple[str | None, str | None]:
        match = re.search(r"\b(\d{1,2})\s*[:;]\s*(\d{2})\b", text)
        if not match:
            return None, None
        return "running", f"{int(match.group(1))}:{match.group(2)}"

    def _parse_score(self, text: str) -> dict:
        digits = [int(value) for value in re.findall(r"\d{1,2}", text)]
        if len(digits) < 6:
            return {}
        digits = digits[-6:]
        return {
            "top_points": digits[0],
            "top_advantages": digits[1],
            "top_penalties": digits[2],
            "bottom_points": digits[3],
            "bottom_advantages": digits[4],
            "bottom_penalties": digits[5],
        }

    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        score = self._image_from_bytes(score_image)
        timer = self._image_from_bytes(timer_image)
        timer_text = self._ocr(timer, "--psm 7")
        scoreboard_text = self._ocr(score, "--psm 6")
        timer_state, timer_value = self._parse_timer(timer_text)
        score_fields = self._parse_score(scoreboard_text)
        return FrameReading(
            frame_second=frame_second,
            **score_fields,
            timer_state=timer_state,
            timer_value=timer_value,
            profile_id=self.parser_profile,
            score_engine=self.score_engine,
            name_engine=self.name_engine,
            evidence={
                "timer_text": timer_text,
                "scoreboard_text": scoreboard_text,
            },
        )


def _load_app():
    import app as app_module

    return app_module.app


def log(message: str):
    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    print(f"{timestamp}Z {message}", file=sys.stderr, flush=True)


def validate_ocr_engines(score_engine: str, name_engine: str | None):
    engines = [score_engine]
    if name_engine:
        engines.append(name_engine)
    for engine in engines:
        if engine not in SUPPORTED_ENGINES:
            raise RuntimeError(f"unsupported OCR engine: {engine}")
        if engine == "none":
            continue
        if engine == "tesseract":
            try:
                import pytesseract  # noqa: F401
                from PIL import Image  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "tesseract engine requires pytesseract and pillow"
                ) from exc
            if not shutil.which("tesseract"):
                raise RuntimeError("tesseract engine requires the tesseract binary")
        if engine == "paddle":
            try:
                import paddleocr  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("paddle engine requires paddleocr") from exc


def build_parser(parser_profile: str, score_engine: str, name_engine: str | None):
    if score_engine == "none" and name_engine in (None, "none"):
        return EmptyTextParser()
    return TesseractTextParser(parser_profile, score_engine, name_engine)


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
    events = scan_frame_text_segment(
        provider,
        parser,
        segment.start_second,
        segment.end_second,
        initial_state=initial_state,
        coarse_interval_seconds=interval,
    )
    state.mark_success(segment, events)
    log(f"Text scan segment success id={segment.id} events={len(events)}")


def run(args, state=None) -> int:
    validate_ocr_engines(args.score_engine, args.name_engine)
    parser = build_parser(args.parser_profile, args.score_engine, args.name_engine)
    if state is None:
        state = LocalTextScanState()
    if not bucket_name:
        raise RuntimeError("S3_BUCKET is not configured")
    s3_client = get_s3_client()

    processed = 0
    while processed < args.max_segments:
        scan_id = uuid.UUID(args.scan_id) if args.scan_id else None
        archive_id = uuid.UUID(args.archive_id) if args.archive_id else None
        background_task_id = (
            uuid.UUID(args.background_task_id) if args.background_task_id else None
        )
        segment = state.claim_next_segment(
            scan_id=scan_id,
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
    parser.add_argument("--scan-id")
    parser.add_argument("--archive-id")
    parser.add_argument("--youtube-id")
    parser.add_argument("--claim-next", action="store_true")
    parser.add_argument("--max-segments", type=int, default=1)
    parser.add_argument("--parser-profile", default=DEFAULT_PARSER_PROFILE)
    parser.add_argument("--score-engine", default=DEFAULT_SCORE_ENGINE)
    parser.add_argument("--name-engine")
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
