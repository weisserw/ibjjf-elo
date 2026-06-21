#!/usr/bin/env python3
"""Archive one full frame per second from queued YouTube livestream segments."""

from __future__ import annotations

import argparse
import faulthandler
import os
import shutil
import subprocess
import sys
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
    claim_next_segment,
    create_missing_segments,
    recompute_archive_status,
    upsert_ocr_reading,
)
from models import LivestreamFrameArchive, LivestreamFrameCaptureSegment  # noqa: E402


DEFAULT_FORMAT_SELECTOR = "best[height<=1080]/best"
FFMPEG_PROGRESS_LOG_SECONDS = 30
DEFAULT_PADDLE_LANG = "en"
DEFAULT_OCR_ENGINE = "opencv_rules"


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


def _segment_frame_paths(
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
):
    for index, frame_path in enumerate(sorted(frames_dir.glob("*.jpg")), start=0):
        second = segment.start_second + index
        if second >= segment.end_second:
            break
        yield second, frame_path


def process_segment_frames_with_ocr(
    archive: LivestreamFrameArchive,
    segment: LivestreamFrameCaptureSegment,
    frames_dir: Path,
    ocr_engine: str = DEFAULT_OCR_ENGINE,
    paddle_lang: str = DEFAULT_PADDLE_LANG,
    ocr_progress_interval: int = 60,
    ocr_max_frames: int | None = None,
) -> tuple[int, int | None, bool]:
    from scoreboard_ocr import (
        build_paddle_ocr,
        process_frame_fast,
        process_frame_paddle,
    )

    log(
        f"Starting frame OCR segment_id={segment.id} "
        f"engine={ocr_engine} range={segment.start_second}-{segment.end_second}"
    )
    ocr = None
    if ocr_engine == "paddleocr":
        init_started_at = time.monotonic()
        ocr = build_paddle_ocr(lang=paddle_lang)
        log(
            f"PaddleOCR initialized segment_id={segment.id} "
            f"elapsed={time.monotonic() - init_started_at:.1f}s"
        )
    crops_dir = frames_dir / "ocr-crops"
    frame_count = 0
    complete_score_count = 0
    clock_count = 0
    last_second = None
    completed_segment = True
    for frame_index, (second, frame_path) in enumerate(
        _segment_frame_paths(segment, frames_dir)
    ):
        if ocr_max_frames is not None and frame_index >= ocr_max_frames:
            completed_segment = False
            log(
                f"Stopping PaddleOCR early segment_id={segment.id} "
                f"ocr_max_frames={ocr_max_frames}"
            )
            break
        frame_started_at = time.monotonic()
        if frame_index == 0:
            log(
                f"Frame OCR first frame starting segment_id={segment.id} "
                f"engine={ocr_engine} second={second} path={frame_path}"
            )
        if ocr_engine == "paddleocr":
            reading = process_frame_paddle(
                ocr,
                frame_path,
                frame_index=frame_index,
                frame_second=second,
                crops_dir=crops_dir,
            )
        elif ocr_engine == "opencv_rules":
            reading = process_frame_fast(
                frame_path,
                frame_index=frame_index,
                frame_second=second,
            )
        else:
            raise ValueError(f"Unsupported OCR engine: {ocr_engine}")
        upsert_ocr_reading(db.session, archive, segment, reading)
        frame_count += 1
        if reading.score_complete:
            complete_score_count += 1
        if reading.clock_detected:
            clock_count += 1
        last_second = second
        if frame_index == 0 or (
            ocr_progress_interval > 0 and frame_count % ocr_progress_interval == 0
        ):
            log(
                f"Frame OCR progress segment_id={segment.id} engine={ocr_engine} "
                f"frames={frame_count} last_second={last_second} "
                f"score_complete={complete_score_count}/{frame_count} "
                f"clock_detected={clock_count}/{frame_count} "
                f"last_frame_elapsed={time.monotonic() - frame_started_at:.1f}s"
            )

    segment.processed_frame_count = frame_count
    segment.last_processed_second = last_second
    log(
        f"Frame OCR complete segment_id={segment.id} engine={ocr_engine} "
        f"frames={frame_count} "
        f"score_complete={complete_score_count}/{frame_count or 1} "
        f"clock_detected={clock_count}/{frame_count or 1} "
        f"last_second={last_second}"
    )
    return frame_count, last_second, completed_segment


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
    ocr_engine: str,
    paddle_lang: str,
    paddle_home: str | None,
    ocr_progress_interval: int,
    ocr_max_frames: int | None,
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

    if paddle_home:
        os.environ["HOME"] = paddle_home
        Path(paddle_home).mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="livestream-frames-") as temp_dir:
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
        frame_count = len(list(frames_dir.glob("*.jpg")))
        log(
            f"Frame extraction produced segment_id={segment.id} "
            f"frames={frame_count}"
        )
        processed, last_second, completed_segment = process_segment_frames_with_ocr(
            archive,
            segment,
            frames_dir,
            ocr_engine=ocr_engine,
            paddle_lang=paddle_lang,
            ocr_progress_interval=ocr_progress_interval,
            ocr_max_frames=ocr_max_frames,
        )

    segment.processed_frame_count = processed
    segment.last_processed_second = last_second
    if not completed_segment:
        segment.status = "queued"
        segment.last_error = (
            f"Debug OCR run stopped after {processed} frame(s); segment requeued."
        )
        segment.finished_at = datetime.utcnow()
        recompute_archive_status(db.session, archive)
        db.session.commit()
        log(
            f"Segment requeued after debug OCR limit id={segment.id} "
            f"processed_frames={processed} last_second={last_second}"
        )
        return

    segment.status = "success"
    segment.finished_at = datetime.utcnow()
    recompute_archive_status(db.session, archive)
    db.session.commit()
    log(
        f"Segment success id={segment.id} processed_frames={processed} "
        f"last_second={last_second} "
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
                args.ocr_engine,
                args.paddle_lang,
                args.paddle_home,
                args.ocr_progress_interval,
                args.ocr_max_frames,
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
        "--ocr-engine",
        choices=("opencv_rules", "paddleocr"),
        default=DEFAULT_OCR_ENGINE,
    )
    parser.add_argument("--paddle-lang", default=DEFAULT_PADDLE_LANG)
    parser.add_argument(
        "--paddle-home",
        help="Optional HOME/cache directory for PaddleOCR model files",
    )
    parser.add_argument(
        "--ocr-progress-interval",
        type=int,
        default=60,
        help="Log OCR progress every N processed frames; set 0 to disable",
    )
    parser.add_argument(
        "--ocr-max-frames",
        type=int,
        default=None,
        help="Debug mode: process at most N extracted frames in the segment",
    )
    parser.add_argument(
        "--debug-traceback-after",
        type=int,
        default=None,
        help="Dump Python stack traces every N seconds while the runner is alive",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--background-task-id")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.debug_traceback_after:
        faulthandler.enable()
        faulthandler.dump_traceback_later(
            args.debug_traceback_after,
            repeat=True,
        )
    app = _load_app()
    with app.app_context():
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
