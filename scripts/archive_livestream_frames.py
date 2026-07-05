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
from dataclasses import dataclass
from datetime import datetime
from math import ceil, floor
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
DEFAULT_FALLBACK_FORMAT_SELECTOR = (
    "bv*[height=480][vcodec^=avc1]/135/"
    "bv*[height<=480][vcodec^=avc1]/"
    "bv*[height<=720][vcodec^=avc1]/"
    "bv*[vcodec^=avc1]/bv*"
)
FFMPEG_PROGRESS_LOG_SECONDS = 30
CROP_VARIANTS = ("score", "timer")
COOKIES_ENV_VAR = "YTDLP_COOKIES"
COOKIES_CONTENT_ENV_VAR = "YTDLP_COOKIES_CONTENT"
COOKIES_BASE64_ENV_VAR = "YTDLP_COOKIES_BASE64"
COOKIES_FROM_BROWSER_ENV_VAR = "YTDLP_COOKIES_FROM_BROWSER"
EXTRACTOR_ARGS_ENV_VAR = "YTDLP_EXTRACTOR_ARGS"
DEFAULT_EXTRACTOR_ARGS = "youtube:player_client=default,-web_embedded"
ADMIN_URL_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_URL"
ADMIN_PASSWORD_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_PASSWORD"
YOUTUBE_COOKIE_DOMAINS = ("youtube.com", "google.com", "googlevideo.com", "ytimg.com")
FORMAT_UNAVAILABLE_MARKER = "Requested format is not available"
CROP_FILTER = (
    "[0:v]fps={fps:g},split=2[score_src][timer_src];"
    "[score_src]crop=w=trunc(iw*0.27):h=trunc(ih*0.22):x=0:y=0[score];"
    "[timer_src]crop=w=trunc(iw*0.22):h=trunc(ih*0.11):x=trunc(iw*0.30):y=0[timer]"
)
DASH_FRAGMENT_PROTOCOLS = {"http_dash_segments", "http_dash_segments_generator"}


@dataclass
class StreamSource:
    url: str
    selected: dict


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


def _parse_extractor_args(value: str | None):
    if not value:
        return None

    parsed = {}
    for extractor_entry in value.split():
        if ":" not in extractor_entry:
            raise ValueError(f"invalid extractor args value: {value}")
        extractor, raw_args = extractor_entry.split(":", 1)
        if not extractor or not raw_args:
            raise ValueError(f"invalid extractor args value: {value}")
        extractor_args = parsed.setdefault(extractor, {})
        for raw_arg in raw_args.split(";"):
            if not raw_arg:
                continue
            if "=" not in raw_arg:
                raise ValueError(f"invalid extractor args value: {value}")
            key, raw_values = raw_arg.split("=", 1)
            if not key:
                raise ValueError(f"invalid extractor args value: {value}")
            extractor_args[key.replace("-", "_")] = [
                item for item in raw_values.split(",") if item
            ]
    return parsed


def _yt_dlp_options(
    format_selector,
    js_runtime,
    remote_components,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    extractor_args: str | None = None,
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
    parsed_extractor_args = _parse_extractor_args(extractor_args)
    if parsed_extractor_args:
        options["extractor_args"] = parsed_extractor_args
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
        f"extractor_args={options.get('extractor_args') or {}} "
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


def _is_dash_fragment_format(format_info: dict) -> bool:
    return format_info.get("protocol") in DASH_FRAGMENT_PROTOCOLS and bool(
        format_info.get("fragments")
    )


def _fragment_url(format_info: dict, fragment: dict) -> str:
    fragment_url = fragment.get("url")
    if fragment_url:
        return fragment_url

    fragment_base_url = format_info.get("fragment_base_url")
    fragment_path = fragment.get("path")
    if not fragment_base_url or not fragment_path:
        raise RuntimeError("DASH fragment is missing url/path metadata")
    return urljoin(fragment_base_url, fragment_path)


def _looks_like_init_fragment(format_info: dict, fragment: dict) -> bool:
    fragment_url = fragment.get("url") or fragment.get("path") or ""
    parsed = urlparse(fragment_url)
    path = parsed.path or fragment_url
    basename = Path(path).name.lower()
    return basename == "init" or basename.startswith(("init.", "init-", "init_"))


def _fragment_debug_label(fragment: dict) -> str:
    fragment_url = fragment.get("url") or fragment.get("path") or ""
    if not fragment_url:
        return "missing-url"

    parsed = urlparse(fragment_url)
    path = parsed.path or fragment_url
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "missing-path"
    if len(parts) >= 2 and parts[-2] == "sq":
        return f"sq/{parts[-1]}"
    return "/".join(parts[-2:])


def _durationless_dash_fragments_for_range(
    format_info: dict,
    start_second: int,
    duration_seconds: int,
    fragments: list[dict],
) -> tuple[list[dict], float] | None:
    total_duration = format_info.get("_archive_duration_seconds") or format_info.get(
        "duration"
    )
    if not total_duration:
        log(
            "DASH fragment range inference unavailable: "
            "missing archive duration "
            f"fragments={len(fragments)} "
            f"range={start_second}-{start_second + duration_seconds}"
        )
        return None
    try:
        total_duration = float(total_duration)
    except (TypeError, ValueError):
        log(
            "DASH fragment range inference unavailable: "
            f"invalid archive duration={total_duration!r} "
            f"fragments={len(fragments)} "
            f"range={start_second}-{start_second + duration_seconds}"
        )
        return None
    if total_duration <= 0:
        log(
            "DASH fragment range inference unavailable: "
            f"nonpositive archive duration={total_duration:g} "
            f"fragments={len(fragments)} "
            f"range={start_second}-{start_second + duration_seconds}"
        )
        return None

    init_fragments = [
        fragment
        for fragment in fragments
        if _looks_like_init_fragment(format_info, fragment)
    ]
    media_fragments = [
        fragment
        for fragment in fragments
        if not _looks_like_init_fragment(format_info, fragment)
    ]
    if not media_fragments:
        log(
            "DASH fragment range inference unavailable: "
            "no media fragments after init classification "
            f"fragments={len(fragments)} "
            f"init={len(init_fragments)} "
            f"first={_fragment_debug_label(fragments[0]) if fragments else 'none'} "
            f"last={_fragment_debug_label(fragments[-1]) if fragments else 'none'}"
        )
        return None

    inferred_fragment_duration = total_duration / len(media_fragments)
    if inferred_fragment_duration <= 0:
        log(
            "DASH fragment range inference unavailable: "
            f"nonpositive inferred fragment duration={inferred_fragment_duration:g} "
            f"duration={total_duration:g} media={len(media_fragments)}"
        )
        return None

    start_index = max(0, floor(start_second / inferred_fragment_duration))
    end_index = min(
        len(media_fragments),
        max(
            start_index + 1,
            ceil((start_second + duration_seconds) / inferred_fragment_duration),
        ),
    )
    if start_index >= len(media_fragments):
        log(
            "DASH fragment range inference selected no media fragments: "
            f"range={start_second}-{start_second + duration_seconds} "
            f"duration={total_duration:g} "
            f"media={len(media_fragments)} "
            f"inferred_fragment_duration={inferred_fragment_duration:.3f} "
            f"start_index={start_index} end_index={end_index}"
        )
        return None

    first_media_start = start_index * inferred_fragment_duration
    log(
        "DASH fragment range inferred: "
        f"range={start_second}-{start_second + duration_seconds} "
        f"duration={total_duration:g} "
        f"fragments={len(fragments)} "
        f"init={len(init_fragments)} "
        f"media={len(media_fragments)} "
        f"inferred_fragment_duration={inferred_fragment_duration:.3f} "
        f"media_indexes={start_index}-{end_index - 1} "
        f"local_start={max(0.0, start_second - first_media_start):.3f} "
        f"first={_fragment_debug_label(media_fragments[start_index])} "
        f"last={_fragment_debug_label(media_fragments[end_index - 1])}"
    )
    return (
        init_fragments + media_fragments[start_index:end_index],
        max(0.0, start_second - first_media_start),
    )


def _dash_fragments_for_range(
    format_info: dict,
    start_second: int,
    duration_seconds: int,
) -> tuple[list[dict], float]:
    end_second = start_second + duration_seconds
    fragments = list(format_info.get("fragments") or [])
    duration_count = sum(
        1 for fragment in fragments if fragment.get("duration") is not None
    )
    log(
        "DASH fragment range scan: "
        f"format_id={format_info.get('format_id') or 'unknown'} "
        f"protocol={format_info.get('protocol') or 'unknown'} "
        f"range={start_second}-{end_second} "
        f"fragments={len(fragments)} "
        f"with_duration={duration_count} "
        f"first={_fragment_debug_label(fragments[0]) if fragments else 'none'} "
        f"last={_fragment_debug_label(fragments[-1]) if fragments else 'none'}"
    )
    if fragments and all(fragment.get("duration") is None for fragment in fragments):
        inferred = _durationless_dash_fragments_for_range(
            format_info,
            start_second,
            duration_seconds,
            fragments,
        )
        if inferred is not None:
            return inferred

    selected_fragments = []
    init_fragments = []
    cursor = 0.0
    first_media_start = None

    for fragment in fragments:
        fragment_duration = fragment.get("duration")
        if fragment_duration is None:
            init_fragments.append(fragment)
            continue

        try:
            fragment_duration = float(fragment_duration)
        except (TypeError, ValueError):
            raise RuntimeError("DASH fragment has invalid duration metadata")

        fragment_start = cursor
        fragment_end = cursor + fragment_duration
        cursor = fragment_end

        if fragment_end <= start_second:
            continue
        if fragment_start >= end_second:
            break
        if first_media_start is None:
            first_media_start = fragment_start
            selected_fragments.extend(init_fragments)
        selected_fragments.append(fragment)

    if first_media_start is None:
        log(
            "DASH fragment range scan selected no fragments: "
            f"range={start_second}-{end_second} "
            f"fragments={len(fragments)} "
            f"with_duration={duration_count} "
            f"init={len(init_fragments)} "
            f"cursor={cursor:.3f}"
        )
        raise RuntimeError("No DASH fragments overlap requested segment range")

    log(
        "DASH fragment range selected: "
        f"range={start_second}-{end_second} "
        f"fragments={len(selected_fragments)} "
        f"local_start={max(0.0, start_second - first_media_start):.3f} "
        f"first={_fragment_debug_label(selected_fragments[0])} "
        f"last={_fragment_debug_label(selected_fragments[-1])}"
    )
    return selected_fragments, max(0.0, start_second - first_media_start)


def download_dash_fragment_section(
    format_info: dict,
    start_second: int,
    duration_seconds: int,
    output_path: Path,
    http_get=requests.get,
) -> float:
    fragments, local_start_second = _dash_fragments_for_range(
        format_info,
        start_second,
        duration_seconds,
    )
    log(
        "Downloading DASH fragment section: "
        f"format_id={format_info.get('format_id') or 'unknown'} "
        f"fragments={len(fragments)} "
        f"output={output_path}"
    )
    headers = format_info.get("http_headers") or None
    with output_path.open("wb") as output_file:
        for index, fragment in enumerate(fragments, start=1):
            response = http_get(
                _fragment_url(format_info, fragment),
                stream=True,
                headers=headers,
            )
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)
            if index % 100 == 0:
                log(
                    "DASH fragment download progress: "
                    f"downloaded={index} of={len(fragments)}"
                )
    return local_start_second


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
    fallback_format_selector: str | None,
    js_runtime: str | None,
    remote_components: list[str],
    cookies: str | None,
    cookies_content: str | None,
    cookies_from_browser: str | None,
    extractor_args: str | None,
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
            extractor_args=extractor_args,
        )
        _log_probe_config(options, yt_dlp.version.__version__)
        selected = None
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(archive.canonical_url, download=False)
        except DownloadError as exc:
            if FORMAT_UNAVAILABLE_MARKER not in str(exc):
                raise
            if fallback_format_selector and fallback_format_selector != format_selector:
                fallback_options = dict(options)
                fallback_options["format"] = fallback_format_selector
                log(
                    "yt-dlp format selector failed; retrying fallback selector: "
                    f"{exc}"
                )
                try:
                    with yt_dlp.YoutubeDL(fallback_options) as ydl:
                        info = ydl.extract_info(
                            archive.canonical_url,
                            download=False,
                        )
                except DownloadError as fallback_exc:
                    if FORMAT_UNAVAILABLE_MARKER not in str(fallback_exc):
                        raise
                    log(
                        "yt-dlp fallback format selector failed; probing available "
                        f"formats without selector: {fallback_exc}"
                    )
                else:
                    selected = _selected_format(info)
                    log(f"Selected fallback video format: {_format_label(selected)}")
            if selected is None:
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
    selected["_archive_duration_seconds"] = archive.duration_seconds or info.get(
        "duration"
    )
    return StreamSource(stream_url, selected)


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
    fallback_format_selector: str | None,
    js_runtime: str | None,
    remote_components: list[str],
    cookies: str | None,
    cookies_content: str | None,
    cookies_from_browser: str | None,
    extractor_args: str | None,
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
    stream_source = probe_youtube_archive(
        archive,
        state,
        format_selector,
        fallback_format_selector,
        js_runtime,
        remote_components,
        cookies,
        cookies_content,
        cookies_from_browser,
        extractor_args,
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
        input_url = stream_source.url
        input_start_second = segment.start_second
        if _is_dash_fragment_format(stream_source.selected):
            extension = stream_source.selected.get("ext") or "mp4"
            media_path = frames_dir / f"dash-section.{extension}"
            input_start_second = download_dash_fragment_section(
                stream_source.selected,
                segment.start_second,
                duration,
                media_path,
            )
            input_url = str(media_path)
            log(
                "Using local DASH fragment section for ffmpeg extraction: "
                f"path={media_path} seek={input_start_second:.3f}s"
            )
        log(
            f"Starting ffmpeg extraction segment_id={segment.id} "
            f"start={_format_duration(segment.start_second)} "
            f"duration={_format_duration(duration)} "
            f"fps={archive.frame_rate or 1.0:g} "
            f"output_dir={frames_dir}"
        )
        extract_segment_frames(
            input_url,
            input_start_second,
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
                args.fallback_format,
                args.js_runtime,
                args.remote_component,
                args.cookies,
                args.cookies_content,
                args.cookies_from_browser,
                args.extractor_args,
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
    parser.add_argument(
        "--fallback-format",
        default=DEFAULT_FALLBACK_FORMAT_SELECTOR,
        help=(
            "yt-dlp format selector used only when --format is unavailable; "
            "set to an empty string to disable"
        ),
    )
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
    parser.add_argument(
        "--extractor-args",
        default=os.environ.get(EXTRACTOR_ARGS_ENV_VAR, DEFAULT_EXTRACTOR_ARGS),
        help=(
            "yt-dlp extractor args, defaults to "
            f"${EXTRACTOR_ARGS_ENV_VAR} or {DEFAULT_EXTRACTOR_ARGS!r}; "
            "set to an empty string to disable"
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
