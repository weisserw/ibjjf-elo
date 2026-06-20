#!/usr/bin/env python3
"""Archive one full frame per second from queued YouTube livestream segments."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from extensions import db  # noqa: E402
from livestream_frame_archive import (  # noqa: E402
    DEFAULT_SEGMENT_SECONDS,
    apply_probe_metadata,
    claim_next_segment,
    create_missing_segments,
    frame_s3_key,
    recompute_archive_status,
)
from models import LivestreamFrameArchive, LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


DEFAULT_FORMAT_SELECTOR = "best[height<=1080]/best"
COOKIES_ENV_VAR = "YTDLP_COOKIES"
COOKIES_CONTENT_ENV_VAR = "YTDLP_COOKIES_CONTENT"
COOKIES_BASE64_ENV_VAR = "YTDLP_COOKIES_BASE64"
COOKIES_FROM_BROWSER_ENV_VAR = "YTDLP_COOKIES_FROM_BROWSER"


def _load_app():
    import app as app_module

    return app_module.app


def _parse_js_runtime(js_runtime: str) -> tuple[str, dict]:
    runtime, _, path = js_runtime.partition(":")
    config = {}
    if path:
        config["path"] = path
    return runtime.lower(), config


def _parse_cookies_from_browser(
    value: str,
) -> tuple[str, str | None, str | None, str | None]:
    match = re.fullmatch(
        r"""
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
        """,
        value,
        re.VERBOSE,
    )
    if not match:
        raise ValueError(f"invalid cookies-from-browser value: {value}")
    browser_name, keyring, profile, container = match.group(
        "name", "keyring", "profile", "container"
    )
    return (
        browser_name.lower(),
        profile,
        keyring.upper() if keyring else None,
        container,
    )


def _yt_dlp_options(
    format_selector,
    js_runtime,
    remote_components,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
):
    options = {
        "format": format_selector,
        "quiet": True,
        "no_warnings": True,
    }
    if js_runtime:
        runtime, config = _parse_js_runtime(js_runtime)
        options["js_runtimes"] = {runtime: config}
    if remote_components:
        options["remote_components"] = remote_components
    if cookies:
        options["cookiefile"] = cookies
    if cookies_from_browser:
        options["cookiesfrombrowser"] = _parse_cookies_from_browser(
            cookies_from_browser
        )
    return options


def _cookies_content_from_args(cookies_content: str | None, cookies_base64: str | None):
    if cookies_content:
        return cookies_content
    if cookies_base64:
        return base64.b64decode(cookies_base64).decode("utf-8")
    return None


@contextmanager
def _cookiefile_from_content(cookies: str | None, cookies_content: str | None):
    if cookies or not cookies_content:
        yield cookies
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            prefix="yt-dlp-cookies-",
            suffix=".txt",
            delete=False,
        ) as cookie_file:
            temp_path = cookie_file.name
            cookie_file.write(cookies_content)
            if not cookies_content.endswith("\n"):
                cookie_file.write("\n")
        os.chmod(temp_path, 0o600)
        yield temp_path
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def _log_probe_config(options, yt_dlp_version):
    js_runtimes = sorted(options.get("js_runtimes") or [])
    node_path = shutil.which("node")
    cookie_source = "none"
    if options.get("cookiefile"):
        cookie_source = "file"
    elif options.get("cookiesfrombrowser"):
        cookie_source = "browser"
    print(
        "yt-dlp probe config: "
        f"version={yt_dlp_version} "
        f"format={options.get('format')} "
        f"js_runtimes={js_runtimes} "
        f"remote_components={sorted(options.get('remote_components') or [])} "
        f"node_path={node_path or 'missing'} "
        f"cookies={cookie_source}",
        file=sys.stderr,
        flush=True,
    )


def _selected_format(info):
    requested = info.get("requested_formats") or []
    video_formats = [
        item
        for item in requested
        if item.get("vcodec") not in (None, "none") and item.get("url")
    ]
    if video_formats:
        return video_formats[0]
    return info


def probe_youtube_archive(
    archive: LivestreamFrameArchive,
    format_selector: str,
    js_runtime: str | None,
    remote_components: list[str],
    cookies: str | None,
    cookies_content: str | None,
    cookies_from_browser: str | None,
    segment_seconds: int,
):
    import yt_dlp
    import yt_dlp.version

    archive.status = "probing"
    db.session.commit()

    with _cookiefile_from_content(cookies, cookies_content) as cookiefile:
        options = _yt_dlp_options(
            format_selector,
            js_runtime,
            remote_components,
            cookies=cookiefile,
            cookies_from_browser=cookies_from_browser,
        )
        _log_probe_config(options, yt_dlp.version.__version__)
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(archive.canonical_url, download=False)

    selected = _selected_format(info)
    stream_url = selected.get("url") or info.get("url")
    if not stream_url:
        raise RuntimeError("yt-dlp did not return a playable stream URL")

    apply_probe_metadata(archive, info, selected)
    archive.yt_dlp_version = yt_dlp.version.__version__
    create_missing_segments(db.session, archive, segment_seconds)
    db.session.commit()
    return stream_url


def extract_segment_frames(
    stream_url: str,
    start_second: int,
    duration_seconds: int,
    fps: float,
    jpeg_quality: int,
    output_dir: Path,
    run=subprocess.run,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start_second),
        "-i",
        stream_url,
        "-t",
        str(duration_seconds),
        "-vf",
        f"fps={fps:g}",
        "-q:v",
        str(jpeg_quality),
        str(output_dir / "%06d.jpg"),
    ]
    run(command, check=True)


def upload_segment_frames(
    archive: LivestreamFrameArchive,
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
    s3_client,
    bucket: str,
    dry_run: bool = False,
    commit_progress: bool = True,
) -> tuple[int, int | None]:
    uploaded = 0
    last_second = None
    for index, frame_path in enumerate(sorted(frames_dir.glob("*.jpg")), start=0):
        second = segment.start_second + index
        if second >= segment.end_second:
            break
        key = frame_s3_key(archive, second)
        if not dry_run:
            with frame_path.open("rb") as frame_file:
                s3_client.upload_fileobj(
                    frame_file,
                    bucket,
                    key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
        uploaded += 1
        last_second = second
        segment.uploaded_frame_count = uploaded
        segment.last_uploaded_second = last_second
        archive.uploaded_frame_count = (archive.uploaded_frame_count or 0) + 1
        archive.last_uploaded_second = last_second
        if commit_progress:
            db.session.commit()
    return uploaded, last_second


def segment_duration(archive: LivestreamFrameArchive, segment) -> int:
    end_second = segment.end_second
    if archive.duration_seconds is not None:
        end_second = min(end_second, archive.duration_seconds)
    return max(0, end_second - segment.start_second)


def process_segment(
    segment: LivestreamFrameCaptureSegment,
    format_selector: str,
    js_runtime: str | None,
    remote_components: list[str],
    cookies: str | None,
    cookies_content: str | None,
    cookies_from_browser: str | None,
    segment_seconds: int,
    fps: float,
    jpeg_quality: int,
    dry_run: bool = False,
):
    archive = segment.archive
    archive.frame_rate = fps
    stream_url = probe_youtube_archive(
        archive,
        format_selector,
        js_runtime,
        remote_components,
        cookies,
        cookies_content,
        cookies_from_browser,
        segment_seconds,
    )

    duration = segment_duration(archive, segment)
    if duration <= 0:
        segment.status = "skipped"
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(db.session, archive)
        db.session.commit()
        return

    if dry_run:
        print(
            f"Dry run: would extract {duration}s from {archive.youtube_video_id} "
            f"starting at {segment.start_second}"
        )
        segment.status = "skipped"
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(db.session, archive)
        db.session.commit()
        return

    s3_client = get_s3_client()
    if not bucket_name:
        raise RuntimeError("S3_BUCKET is not configured")

    with tempfile.TemporaryDirectory(prefix="livestream-frames-") as temp_dir:
        frames_dir = Path(temp_dir)
        extract_segment_frames(
            stream_url,
            segment.start_second,
            duration,
            archive.frame_rate or 1.0,
            jpeg_quality,
            frames_dir,
        )
        uploaded, last_second = upload_segment_frames(
            archive, segment, frames_dir, s3_client, bucket_name
        )

    segment.uploaded_frame_count = uploaded
    segment.last_uploaded_second = last_second
    segment.status = "success"
    segment.finished_at = datetime.utcnow()
    recompute_archive_status(db.session, archive)
    db.session.commit()


def run(args) -> int:
    processed = 0
    while processed < args.max_segments:
        archive_id = uuid.UUID(args.archive_id) if args.archive_id else None
        background_task_id = (
            uuid.UUID(args.background_task_id) if args.background_task_id else None
        )
        segment = claim_next_segment(
            db.session,
            archive_id=archive_id,
            youtube_video_id=args.youtube_id,
            background_task_id=background_task_id,
        )
        if not segment:
            print("No claimable livestream frame capture segments.")
            return 0

        try:
            process_segment(
                segment,
                args.format,
                args.js_runtime,
                args.remote_component,
                args.cookies,
                args.cookies_content,
                args.cookies_from_browser,
                args.segment_seconds,
                args.fps,
                args.jpeg_quality,
                dry_run=args.dry_run,
            )
            processed += 1
        except Exception as exc:
            db.session.rollback()
            segment = db.session.get(LivestreamFrameCaptureSegment, segment.id)
            archive = db.session.get(LivestreamFrameArchive, segment.archive_id)
            segment.status = "error"
            segment.last_error = str(exc)
            segment.finished_at = datetime.utcnow()
            archive.last_error = str(exc)
            recompute_archive_status(db.session, archive)
            db.session.commit()
            print(f"Segment {segment.id} failed: {exc}", file=sys.stderr)
            return 1

        if not args.claim_next:
            return 0

    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-id")
    parser.add_argument("--youtube-id")
    parser.add_argument("--claim-next", action="store_true")
    parser.add_argument("--max-segments", type=int, default=1)
    parser.add_argument("--segment-seconds", type=int, default=DEFAULT_SEGMENT_SECONDS)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--format", default=DEFAULT_FORMAT_SELECTOR)
    parser.add_argument("--js-runtime", default="node")
    parser.add_argument(
        "--remote-component",
        action="append",
        default=["ejs:github"],
        help="yt-dlp remote component, repeatable",
    )
    parser.add_argument(
        "--cookies",
        default=os.environ.get(COOKIES_ENV_VAR),
        help=f"yt-dlp cookies file, defaults to ${COOKIES_ENV_VAR}",
    )
    parser.add_argument(
        "--cookies-content",
        default=_cookies_content_from_args(
            os.environ.get(COOKIES_CONTENT_ENV_VAR),
            os.environ.get(COOKIES_BASE64_ENV_VAR),
        ),
        help=(
            "yt-dlp cookies file content, defaults to "
            f"${COOKIES_CONTENT_ENV_VAR} or base64 ${COOKIES_BASE64_ENV_VAR}"
        ),
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=os.environ.get(COOKIES_FROM_BROWSER_ENV_VAR),
        help=(
            "yt-dlp browser cookie source, defaults to "
            f"${COOKIES_FROM_BROWSER_ENV_VAR}"
        ),
    )
    parser.add_argument("--jpeg-quality", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--background-task-id")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app = _load_app()
    with app.app_context():
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
