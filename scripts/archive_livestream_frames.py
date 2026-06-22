#!/usr/bin/env python3
"""Archive scoreboard/timer crops from queued YouTube livestream segments."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
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
    batch_s3_key,
    claim_next_segment,
    create_missing_segments,
    recompute_archive_status,
)
from models import LivestreamFrameArchive, LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


DEFAULT_FORMAT_SELECTOR = "best[height<=1080]/best"
FFMPEG_PROGRESS_LOG_SECONDS = 30
CROP_VARIANTS = ("score", "timer")
CROP_FILTER = (
    "[0:v]fps={fps:g},split=2[score_src][timer_src];"
    "[score_src]crop=w=trunc(iw*0.25):h=trunc(ih*0.20):x=0:y=0[score];"
    "[timer_src]crop=w=trunc(iw*0.22):h=trunc(ih*0.11):x=trunc(iw*0.30):y=0[timer]"
)


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


def _yt_dlp_options(
    format_selector,
    js_runtime,
    remote_components,
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
    return options


def _log_probe_config(options, yt_dlp_version):
    js_runtimes = sorted(options.get("js_runtimes") or [])
    node_path = shutil.which("node")
    log(
        "yt-dlp probe config: "
        f"version={yt_dlp_version} "
        f"format={options.get('format')} "
        f"js_runtimes={js_runtimes} "
        f"remote_components={sorted(options.get('remote_components') or [])} "
        f"node_path={node_path or 'missing'}",
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
    segment_seconds: int,
):
    import yt_dlp
    import yt_dlp.version

    log(f"Probing YouTube archive youtube_id={archive.youtube_video_id}")
    archive.status = "probing"
    db.session.commit()

    options = _yt_dlp_options(format_selector, js_runtime, remote_components)
    _log_probe_config(options, yt_dlp.version.__version__)
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(archive.canonical_url, download=False)

    selected = _selected_format(info)
    stream_url = selected.get("url") or info.get("url")
    if not stream_url:
        raise RuntimeError("yt-dlp did not return a playable stream URL")

    apply_probe_metadata(archive, info, selected)
    archive.yt_dlp_version = yt_dlp.version.__version__
    created_segments = create_missing_segments(db.session, archive, segment_seconds)
    db.session.commit()
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
    format_selector: str,
    js_runtime: str | None,
    remote_components: list[str],
    segment_seconds: int,
    fps: float,
    jpeg_quality: int,
    dry_run: bool = False,
):
    archive = segment.archive
    archive.frame_rate = fps
    log(
        f"Processing segment id={segment.id} "
        f"youtube_id={archive.youtube_video_id} "
        f"range={segment.start_second}-{segment.end_second} "
        f"fps={fps:g}"
    )
    stream_url = probe_youtube_archive(
        archive,
        format_selector,
        js_runtime,
        remote_components,
        segment_seconds,
    )

    duration = segment_duration(archive, segment)
    if duration <= 0:
        log(f"Skipping segment id={segment.id}; duration is {duration}s")
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

    segment.uploaded_frame_count = uploaded
    segment.sampled_frame_count = sampled
    segment.last_uploaded_second = last_second
    segment.batch_s3_key = batch_key
    segment.status = "success"
    segment.finished_at = datetime.utcnow()
    recompute_archive_status(db.session, archive)
    db.session.commit()
    log(
        f"Segment success id={segment.id} batch_frames={uploaded} "
        f"crop_files={uploaded * len(CROP_VARIANTS)} last_second={last_second} "
        f"archive_status={archive.status}"
    )


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

        log(
            f"Claimed segment id={segment.id} "
            f"archive_id={segment.archive_id} "
            f"range={segment.start_second}-{segment.end_second} "
            f"attempt={segment.attempt_count}"
        )
        try:
            process_segment(
                segment,
                args.format,
                args.js_runtime,
                args.remote_component,
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
    parser.add_argument("--jpeg-quality", type=int, default=2)
    parser.add_argument(
        "--sample-frame-interval",
        type=int,
        default=None,
        help="Deprecated and ignored; full-frame sample uploads are disabled",
    )
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
