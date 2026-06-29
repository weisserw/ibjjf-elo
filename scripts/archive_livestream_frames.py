#!/usr/bin/env python3
"""Archive scoreboard/timer crops from queued YouTube livestream segments."""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from extensions import db  # noqa: E402
from livestream_frame_archive import (  # noqa: E402
    DEFAULT_SEGMENT_SECONDS,
    apply_probe_metadata,
    batch_s3_key,
    claim_next_segment,
    create_missing_segments,
    recompute_archive_status,
)
from models import LivestreamFrameArchive, LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


DEFAULT_FORMAT_SELECTOR = "best[height=480]/18/best[height<=480]/best"
FFMPEG_PROGRESS_LOG_SECONDS = 30
CROP_VARIANTS = ("score", "timer")
COOKIES_ENV_VAR = "YTDLP_COOKIES"
COOKIES_CONTENT_ENV_VAR = "YTDLP_COOKIES_CONTENT"
COOKIES_BASE64_ENV_VAR = "YTDLP_COOKIES_BASE64"
COOKIES_FROM_BROWSER_ENV_VAR = "YTDLP_COOKIES_FROM_BROWSER"
ADMIN_URL_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_URL"
ADMIN_PASSWORD_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_PASSWORD"
YOUTUBE_COOKIE_DOMAINS = ("youtube.com", "google.com", "googlevideo.com", "ytimg.com")
FORMAT_UNAVAILABLE_MARKER = "Requested format is not available"
CROP_FILTER = (
    "[0:v]fps={fps:g},split=2[score_src][timer_src];"
    "[score_src]crop=w=trunc(iw*0.27):h=trunc(ih*0.22):x=0:y=0[score];"
    "[timer_src]crop=w=trunc(iw*0.22):h=trunc(ih*0.11):x=trunc(iw*0.30):y=0[timer]"
)


class ApiObject:
    def __init__(self, data: dict):
        for key, value in data.items():
            if key == "archive" and value is not None:
                value = ApiObject(value)
            setattr(self, key, value)

    def update_from(self, data: dict):
        for key, value in data.items():
            if key == "archive" and value is not None:
                current = getattr(self, key, None)
                if isinstance(current, ApiObject):
                    current.update_from(value)
                    value = current
                else:
                    value = ApiObject(value)
            setattr(self, key, value)


class LocalArchiveState:
    def claim_next_segment(
        self,
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        return claim_next_segment(
            db.session,
            archive_id=archive_id,
            youtube_video_id=youtube_video_id,
            background_task_id=background_task_id,
        )

    def mark_probe_started(self, archive, frame_rate: float):
        archive.frame_rate = frame_rate
        archive.status = "probing"
        db.session.commit()

    def mark_probe_complete(
        self,
        archive,
        info: dict,
        selected: dict,
        yt_dlp_version: str,
        segment_seconds: int,
        frame_rate: float,
    ) -> int:
        archive.frame_rate = frame_rate
        apply_probe_metadata(archive, info, selected)
        archive.yt_dlp_version = yt_dlp_version
        created_segments = create_missing_segments(db.session, archive, segment_seconds)
        db.session.commit()
        return created_segments

    def mark_success(
        self,
        segment,
        uploaded_frame_count: int,
        last_uploaded_second: int | None,
        sampled_frame_count: int,
        batch_s3_key_value: str,
    ):
        segment.uploaded_frame_count = uploaded_frame_count
        segment.sampled_frame_count = sampled_frame_count
        segment.last_uploaded_second = last_uploaded_second
        segment.batch_s3_key = batch_s3_key_value
        segment.status = "success"
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(db.session, segment.archive)
        db.session.commit()

    def mark_skipped(self, segment):
        segment.status = "skipped"
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(db.session, segment.archive)
        db.session.commit()

    def mark_error(self, segment, error: str):
        db.session.rollback()
        segment = db.session.get(LivestreamFrameCaptureSegment, segment.id)
        archive = db.session.get(LivestreamFrameArchive, segment.archive_id)
        segment.status = "error"
        segment.last_error = error
        segment.finished_at = datetime.utcnow()
        archive.last_error = error
        recompute_archive_status(db.session, archive)
        db.session.commit()


class AdminApiArchiveState:
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
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        payload = self._request(
            "POST",
            "/api/livestream_frame_archives/worker/segments/claim",
            json={
                "archive_id": str(archive_id) if archive_id else None,
                "youtube_video_id": youtube_video_id,
                "background_task_id": (
                    str(background_task_id) if background_task_id else None
                ),
            },
        )
        segment = payload.get("segment")
        return ApiObject(segment) if segment else None

    def mark_probe_started(self, archive, frame_rate: float):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/archives/{archive.id}/probe_start",
            json={"frame_rate": frame_rate},
        )
        archive.update_from(payload["archive"])

    def mark_probe_complete(
        self,
        archive,
        info: dict,
        selected: dict,
        yt_dlp_version: str,
        segment_seconds: int,
        frame_rate: float,
    ) -> int:
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/archives/{archive.id}/probe_complete",
            json={
                "duration": info.get("duration"),
                "selected": _selected_probe_fields(selected),
                "yt_dlp_version": yt_dlp_version,
                "segment_seconds": segment_seconds,
                "frame_rate": frame_rate,
            },
        )
        archive.update_from(payload["archive"])
        return payload["created_segments"]

    def mark_success(
        self,
        segment,
        uploaded_frame_count: int,
        last_uploaded_second: int | None,
        sampled_frame_count: int,
        batch_s3_key_value: str,
    ):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/segments/{segment.id}/complete",
            json={
                "status": "success",
                "uploaded_frame_count": uploaded_frame_count,
                "sampled_frame_count": sampled_frame_count,
                "last_uploaded_second": last_uploaded_second,
                "batch_s3_key": batch_s3_key_value,
                "batch_uploaded_at": datetime.utcnow().isoformat(),
            },
        )
        segment.update_from(payload["segment"])

    def mark_skipped(self, segment):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/segments/{segment.id}/complete",
            json={"status": "skipped"},
        )
        segment.update_from(payload["segment"])

    def mark_error(self, segment, error: str):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/segments/{segment.id}/error",
            json={"error": error},
        )
        segment.update_from(payload["segment"])


def _load_app():
    import app as app_module

    return app_module.app


def log(message: str):
    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    print(f"{timestamp}Z {message}", file=sys.stderr, flush=True)


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes:d}m{seconds:02d}s"


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


def _is_cookie_comment(line: str) -> bool:
    return line.startswith("#") and not line.startswith("#HttpOnly_")


def _cookie_domain(line: str) -> str | None:
    if line.startswith("#HttpOnly_"):
        line = line.removeprefix("#HttpOnly_")
    fields = line.split("\t")
    if not fields or len(fields) < 7:
        return None
    return fields[0].lstrip(".").lower()


def _cookiefile_stats(cookiefile: str | None) -> str:
    if not cookiefile:
        return "rows=0 youtube_related_rows=0"

    rows = 0
    youtube_related_rows = 0
    try:
        with open(cookiefile, encoding="utf-8") as cookie_file:
            for raw_line in cookie_file:
                line = raw_line.strip()
                if not line or _is_cookie_comment(line):
                    continue
                rows += 1
                domain = _cookie_domain(line)
                if domain and any(
                    domain == cookie_domain or domain.endswith(f".{cookie_domain}")
                    for cookie_domain in YOUTUBE_COOKIE_DOMAINS
                ):
                    youtube_related_rows += 1
    except OSError as exc:
        return f"unreadable={exc.__class__.__name__}"

    return f"rows={rows} youtube_related_rows={youtube_related_rows}"


def _log_probe_config(options, yt_dlp_version):
    js_runtimes = sorted(options.get("js_runtimes") or [])
    node_path = shutil.which("node")
    cookie_source = "none"
    cookie_stats = ""
    if options.get("cookiefile"):
        cookie_source = "file"
        cookie_stats = f" cookie_stats={_cookiefile_stats(options.get('cookiefile'))}"
    elif options.get("cookiesfrombrowser"):
        cookie_source = "browser"
    log(
        "yt-dlp probe config: "
        f"version={yt_dlp_version} "
        f"format={options.get('format')} "
        f"js_runtimes={js_runtimes} "
        f"remote_components={sorted(options.get('remote_components') or [])} "
        f"node_path={node_path or 'missing'} "
        f"cookies={cookie_source}"
        f"{cookie_stats}",
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


def _selected_probe_fields(selected: dict) -> dict:
    return {
        "format_id": selected.get("format_id"),
        "format_note": selected.get("format_note"),
        "width": selected.get("width"),
        "height": selected.get("height"),
        "fps": selected.get("fps"),
        "vcodec": selected.get("vcodec"),
        "acodec": selected.get("acodec"),
        "tbr": selected.get("tbr"),
        "protocol": selected.get("protocol"),
    }


def _format_int(format_info: dict, key: str) -> int:
    value = format_info.get(key)
    if value is None:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _has_video_url(format_info: dict) -> bool:
    return bool(format_info.get("url")) and format_info.get("vcodec") not in (
        None,
        "none",
    )


def _format_selection_key(format_info: dict) -> tuple[int, int, int]:
    return (
        _format_int(format_info, "height"),
        _format_int(format_info, "fps"),
        _format_int(format_info, "tbr"),
    )


def _select_available_video_format(formats: list[dict]) -> dict | None:
    video_formats = [
        format_info for format_info in formats if _has_video_url(format_info)
    ]
    if not video_formats:
        return None

    candidate_groups = [
        [
            format_info
            for format_info in video_formats
            if str(format_info.get("vcodec") or "").startswith("avc1")
            and 0 < _format_int(format_info, "height") <= 1080
        ],
        [
            format_info
            for format_info in video_formats
            if 0 < _format_int(format_info, "height") <= 1080
        ],
        [
            format_info
            for format_info in video_formats
            if str(format_info.get("vcodec") or "").startswith("avc1")
        ],
        video_formats,
    ]
    for candidates in candidate_groups:
        if candidates:
            return max(candidates, key=_format_selection_key)
    return None


def _format_label(format_info: dict) -> str:
    resolution = format_info.get("resolution")
    if not resolution:
        width = format_info.get("width") or "?"
        height = format_info.get("height") or "?"
        resolution = f"{width}x{height}"
    return (
        f"{format_info.get('format_id') or '?'}:"
        f"{resolution}:"
        f"fps={format_info.get('fps') or '?'}:"
        f"vcodec={format_info.get('vcodec') or '?'}:"
        f"acodec={format_info.get('acodec') or '?'}:"
        f"protocol={format_info.get('protocol') or '?'}"
    )


def _log_format_inventory(info: dict):
    formats = info.get("formats") or []
    video_formats = [
        format_info for format_info in formats if _has_video_url(format_info)
    ]
    audio_only_count = sum(
        1
        for format_info in formats
        if format_info.get("acodec") not in (None, "none")
        and format_info.get("vcodec") == "none"
    )
    storyboard_count = sum(
        1 for format_info in formats if format_info.get("vcodec") == "images"
    )
    top_video_formats = sorted(
        video_formats,
        key=_format_selection_key,
        reverse=True,
    )[:8]
    log(
        "yt-dlp format inventory: "
        f"total={len(formats)} "
        f"video={len(video_formats)} "
        f"audio_only={audio_only_count} "
        f"storyboard={storyboard_count} "
        f"top_video={[_format_label(format_info) for format_info in top_video_formats]}"
    )


def _extract_info_without_format(url: str, options: dict):
    import yt_dlp

    fallback_options = dict(options)
    fallback_options.pop("format", None)
    fallback_options["ignore_no_formats_error"] = True
    with yt_dlp.YoutubeDL(fallback_options) as ydl:
        return ydl.extract_info(url, download=False)


def probe_youtube_archive(
    archive: LivestreamFrameArchive,
    state,
    format_selector: str,
    js_runtime: str | None,
    remote_components: list[str],
    cookies: str | None,
    cookies_content: str | None,
    cookies_from_browser: str | None,
    segment_seconds: int,
    fps: float,
):
    import yt_dlp
    import yt_dlp.version
    from yt_dlp.utils import DownloadError

    log(f"Probing YouTube archive youtube_id={archive.youtube_video_id}")
    state.mark_probe_started(archive, fps)

    with _cookiefile_from_content(cookies, cookies_content) as cookiefile:
        options = _yt_dlp_options(
            format_selector,
            js_runtime,
            remote_components,
            cookies=cookiefile,
            cookies_from_browser=cookies_from_browser,
        )
        _log_probe_config(options, yt_dlp.version.__version__)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(archive.canonical_url, download=False)
        except DownloadError as exc:
            if FORMAT_UNAVAILABLE_MARKER not in str(exc):
                raise
            log(
                "yt-dlp format selector failed; probing available formats without "
                f"selector: {exc}"
            )
            info = _extract_info_without_format(archive.canonical_url, options)
            _log_format_inventory(info)
            selected = _select_available_video_format(info.get("formats") or [])
            if not selected:
                raise
            log(f"Selected fallback video format: {_format_label(selected)}")
        else:
            selected = _selected_format(info)

    stream_url = selected.get("url") or info.get("url")
    if not stream_url:
        raise RuntimeError("yt-dlp did not return a playable stream URL")

    created_segments = state.mark_probe_complete(
        archive,
        info,
        selected,
        yt_dlp.version.__version__,
        segment_seconds,
        fps,
    )
    log(
        f"Probe complete youtube_id={archive.youtube_video_id} "
        f"duration={_format_duration(archive.duration_seconds)} "
        f"format_id={archive.format_id or 'unknown'} "
        f"resolution={archive.width or '?'}x{archive.height or '?'} "
        f"source_fps={archive.source_fps or 'unknown'} "
        f"vcodec={archive.video_codec or 'unknown'} "
        f"protocol={archive.protocol or 'unknown'} "
        f"tbr={archive.tbr or 'unknown'} "
        f"created_segments={created_segments}"
    )
    return stream_url


def _ffmpeg_extract_command(
    stream_url: str,
    start_second: int,
    duration_seconds: int,
    fps: float,
    jpeg_quality: int,
    output_dir: Path,
    progress: bool = False,
):
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
    ]
    if progress:
        command.extend(["-progress", "pipe:1", "-nostats"])
    command.extend(
        [
            "-ss",
            str(start_second),
            "-t",
            str(duration_seconds),
            "-i",
            stream_url,
            "-filter_complex",
            CROP_FILTER.format(fps=fps),
            "-map",
            "[score]",
            "-q:v",
            str(jpeg_quality),
            str(output_dir / "%06d_score.jpg"),
            "-map",
            "[timer]",
            "-q:v",
            str(jpeg_quality),
            str(output_dir / "%06d_timer.jpg"),
        ]
    )
    return command


def _progress_seconds(progress_value: str) -> int | None:
    try:
        return max(0, int(progress_value) // 1_000_000)
    except ValueError:
        return None


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
    if run is not subprocess.run:
        run(
            _ffmpeg_extract_command(
                stream_url,
                start_second,
                duration_seconds,
                fps,
                jpeg_quality,
                output_dir,
            ),
            check=True,
        )
        return

    command = _ffmpeg_extract_command(
        stream_url,
        start_second,
        duration_seconds,
        fps,
        jpeg_quality,
        output_dir,
        progress=True,
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    last_log_at = 0.0
    last_out_second = 0
    assert process.stdout is not None
    for line in process.stdout:
        key, _, value = line.strip().partition("=")
        if key in ("out_time_ms", "out_time_us"):
            out_second = _progress_seconds(value)
            if out_second is None:
                continue
            last_out_second = out_second
            now = time.monotonic()
            if now - last_log_at >= FFMPEG_PROGRESS_LOG_SECONDS:
                last_log_at = now
                percent = min(100.0, (out_second / duration_seconds) * 100)
                log(
                    "ffmpeg progress: "
                    f"processed={_format_duration(out_second)} "
                    f"of={_format_duration(duration_seconds)} "
                    f"percent={percent:.1f}%"
                )
        elif key == "progress" and value == "end":
            last_out_second = duration_seconds

    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)
    log(
        "ffmpeg extraction complete: "
        f"processed={_format_duration(last_out_second)} "
        f"of={_format_duration(duration_seconds)}"
    )


def _segment_crop_paths(
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
):
    for index, score_path in enumerate(sorted(frames_dir.glob("*_score.jpg")), start=0):
        second = segment.start_second + index
        if second >= segment.end_second:
            break
        sequence_number = score_path.name.removesuffix("_score.jpg")
        for crop_variant in CROP_VARIANTS:
            crop_path = frames_dir / f"{sequence_number}_{crop_variant}.jpg"
            if not crop_path.exists():
                raise RuntimeError(
                    f"Missing {crop_variant} crop for extracted frame {sequence_number}"
                )
            yield second, crop_variant, crop_path


def _create_segment_batch(
    archive: LivestreamFrameArchive,
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
    batch_path: Path,
) -> tuple[int, int | None]:
    frame_seconds = set()
    last_second = None
    image_format = archive.image_format or "jpg"
    with tarfile.open(batch_path, "w:gz") as tar:
        for second, crop_variant, crop_path in _segment_crop_paths(segment, frames_dir):
            tar.add(
                crop_path,
                arcname=f"{second:09d}_{crop_variant}.{image_format}",
            )
            frame_seconds.add(second)
            last_second = second
    return len(frame_seconds), last_second


def upload_segment_artifacts(
    archive: LivestreamFrameArchive,
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
    s3_client,
    bucket: str,
    dry_run: bool = False,
) -> tuple[int, int | None, int, str]:
    key = batch_s3_key(archive, segment)
    batch_path = frames_dir / f"{segment.start_second:09d}-{segment.end_second:09d}.tgz"
    frame_count, last_second = _create_segment_batch(
        archive, segment, frames_dir, batch_path
    )
    log(
        f"Uploading crop batch segment_id={segment.id} "
        f"frames={frame_count} crop_files={frame_count * len(CROP_VARIANTS)} "
        f"bucket={bucket} key={key}"
    )
    if not dry_run:
        with batch_path.open("rb") as batch_file:
            s3_client.upload_fileobj(
                batch_file,
                bucket,
                key,
                ExtraArgs={"ContentType": "application/gzip"},
            )

    segment.uploaded_frame_count = frame_count
    segment.sampled_frame_count = 0
    segment.last_uploaded_second = last_second
    segment.batch_s3_key = key
    segment.batch_uploaded_at = datetime.utcnow()
    log(
        f"Upload complete segment_id={segment.id} "
        f"batch_frames={frame_count} crop_files={frame_count * len(CROP_VARIANTS)} "
        f"last_second={last_second}"
    )
    return frame_count, last_second, 0, key


def segment_duration(archive: LivestreamFrameArchive, segment) -> int:
    end_second = segment.end_second
    if archive.duration_seconds is not None:
        end_second = min(end_second, archive.duration_seconds)
    return max(0, end_second - segment.start_second)


def process_segment(
    segment: LivestreamFrameCaptureSegment,
    state,
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
    log(
        f"Processing segment id={segment.id} "
        f"youtube_id={archive.youtube_video_id} "
        f"range={segment.start_second}-{segment.end_second} "
        f"fps={fps:g}"
    )
    stream_url = probe_youtube_archive(
        archive,
        state,
        format_selector,
        js_runtime,
        remote_components,
        cookies,
        cookies_content,
        cookies_from_browser,
        segment_seconds,
        fps,
    )

    duration = segment_duration(archive, segment)
    if duration <= 0:
        log(f"Skipping segment id={segment.id}; duration is {duration}s")
        state.mark_skipped(segment)
        return

    if dry_run:
        print(
            f"Dry run: would extract {duration}s from {archive.youtube_video_id} "
            f"starting at {segment.start_second}"
        )
        state.mark_skipped(segment)
        return

    s3_client = get_s3_client()
    if not bucket_name:
        raise RuntimeError("S3_BUCKET is not configured")

    with tempfile.TemporaryDirectory(prefix="livestream-frame-crops-") as temp_dir:
        frames_dir = Path(temp_dir)
        log(
            f"Starting ffmpeg extraction segment_id={segment.id} "
            f"start={_format_duration(segment.start_second)} "
            f"duration={_format_duration(duration)} "
            f"fps={archive.frame_rate or 1.0:g} "
            f"output_dir={frames_dir}"
        )
        extract_segment_frames(
            stream_url,
            segment.start_second,
            duration,
            archive.frame_rate or 1.0,
            jpeg_quality,
            frames_dir,
        )
        crop_file_count = len(list(frames_dir.glob("*.jpg")))
        log(
            f"Frame extraction produced segment_id={segment.id} "
            f"crop_files={crop_file_count}"
        )
        uploaded, last_second, sampled, batch_key = upload_segment_artifacts(
            archive,
            segment,
            frames_dir,
            s3_client,
            bucket_name,
        )

    state.mark_success(segment, uploaded, last_second, sampled, batch_key)
    log(
        f"Segment success id={segment.id} batch_frames={uploaded} "
        f"crop_files={uploaded * len(CROP_VARIANTS)} last_second={last_second} "
        f"archive_status={archive.status}"
    )


def run(args, state=None) -> int:
    if state is None:
        state = LocalArchiveState()
    processed = 0
    while processed < args.max_segments:
        archive_id = uuid.UUID(args.archive_id) if args.archive_id else None
        background_task_id = (
            uuid.UUID(args.background_task_id) if args.background_task_id else None
        )
        segment = state.claim_next_segment(
            archive_id=archive_id,
            youtube_video_id=args.youtube_id,
            background_task_id=background_task_id,
        )
        if not segment:
            print("No claimable livestream frame capture segments.")
            return 0

        log(
            f"Claimed segment id={segment.id} "
            f"archive_id={segment.archive_id} "
            f"range={segment.start_second}-{segment.end_second} "
            f"attempt={segment.attempt_count}"
        )
        try:
            process_segment(
                segment,
                state,
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
            state.mark_error(segment, str(exc))
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
    parser.add_argument(
        "--sample-frame-interval",
        type=int,
        default=None,
        help="Deprecated and ignored; full-frame sample uploads are disabled",
    )
    parser.add_argument("--dry-run", action="store_true")
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
        return run(args, AdminApiArchiveState(args.admin_url, args.admin_password))

    app = _load_app()
    with app.app_context():
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
