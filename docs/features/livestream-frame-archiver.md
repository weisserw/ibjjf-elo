# Livestream Frame Archiver

## User-Facing Behavior

The livestream frame archiver takes YouTube livestreams attached to IBJJF event/mat/day records, extracts scoreboard and timer crops at a fixed frame rate, stores those crops in S3 batches, and tracks processing status in the admin app.

In the admin app, operators can sync known livestreams into archive rows, queue missing work, queue selected streams, retry failed or cancelled work, cancel queued/running work, flag archives with no scoreboard data, inspect archive segment details, queue OCR text scans, clear scan events, and manually relink completed OCR scans to matches.

This is the first part of the livestream match pipeline:

1. Archive frames from YouTube into cropped S3 batches.
2. Scan the cropped frames for sparse scoreboard/timer/name OCR events.
3. Link completed OCR event windows to match rows and fill match video/score metadata.

## Main Code Paths

- `app/livestream_frame_archive.py` contains archive discovery, queueing, segment range creation, retry/cancel/requeue logic, status recomputation, S3 key helpers, and dashboard row assembly.
- `scripts/archive_livestream_frames.py` is the capture worker. It claims capture segments, probes YouTube with `yt-dlp`, extracts scoreboard/timer crops with `ffmpeg`, writes a segment `.tgz`, uploads it to S3, and marks segment success/error.
- `scripts/livestream_admin_api.py` provides the shared, replay-safe HTTP retry loop used by both remote workers.
- `admin/app.py` contains the server-rendered admin pages and worker JSON endpoints.
- `admin/templates/livestream_frame_archives.html` is the archive list/admin action page.
- `admin/templates/livestream_frame_archive_detail.html` is the archive detail/segment inspection page.
- `app/livestream_frame_text_scan.py` contains text scan queueing, S3 batch reading, sparse event generation, scan status recomputation, rescan/reset helpers, and segment success/error handling.
- `scripts/scan_livestream_frame_text.py` is the OCR worker. It claims text-scan segments, reads archived S3 batches, runs OCR parsers, and posts sparse text events.
- `admin/templates/livestream_frame_text_scans.html` and `admin/templates/livestream_frame_text_scan_detail.html` are the scanner admin pages.
- `app/livestream_match_linking.py` consumes completed text scans, extracts match windows, chooses candidate matches, stores match links, match video offsets, final scores, and participant scoreboard positions.
- `scripts/link_livestream_matches.py` is the CLI/debug surface for match linking.
- `.github/workflows/livestream-worker-image.yml` builds `ghcr.io/weisserw/ibjjf-elo-livestream-worker`.
- `.github/workflows/livestream-frame-text-scanner-image.yml` builds `ghcr.io/weisserw/ibjjf-elo-livestream-frame-text-scanner`.

## Archive Flow

`sync_archives_from_livestreams()` discovers YouTube IDs from `LiveStream.link` rows and creates one `LivestreamFrameArchive` per video ID. `queue_archive_capture()` creates missing `LivestreamFrameCaptureSegment` rows. If duration is unknown, the first queued segment is `0..DEFAULT_SEGMENT_SECONDS`; after probe completes, `create_missing_segments()` fills gaps across the discovered duration.

The admin page's `sync` action also starts an untracked background refresh of
the cached homepage count of YouTube-covered matches. The expensive count no
longer runs inside the Sync HTTP request or creates an admin task-history row.
This provides the initial backfill after the `site_statistics` migration and
keeps the counter aligned when operators sync newly configured streams.

The capture worker can run in two modes:

- Local DB mode: no `--admin-url`; imports the Flask app and writes through SQLAlchemy.
- Remote/admin API mode: `--admin-url` plus `--admin-password`; uses `X-Admin-Password` and the worker endpoints under `/api/livestream_frame_archives/worker/`.

`scripts/archive_livestream_frames.py` selects a YouTube format, with fallback handling for unavailable primary formats. It prefers 480p/default selector behavior but has a fallback video-only selector for `avc1` formats. DASH fragment formats are handled specially: the worker downloads only the overlapping fragment section before calling `ffmpeg`.

The default YouTube player-client order is `web_embedded,default`. Keep the
embedded client first: current yt-dlp default clients can return media URLs that
probe successfully but fail with HTTP 403 when ffmpeg reads them. Operators can
override the order with `YTDLP_EXTRACTOR_ARGS` when YouTube client behavior
changes.

`CROP_FILTER` creates two crops per sampled second:

- `score`: left/top scoreboard area, currently `w=iw*0.27`, `h=ih*0.22`, `x=0`, `y=0`.
- `timer`: top timer area, currently `w=iw*0.22`, `h=ih*0.11`, `x=iw*0.30`, `y=0`.

Admins can upload a JPG/PNG preview frame on an archive detail page and drag/resize
scoreboard and timer overlays. Uploads are orientation-corrected, converted to RGB
JPEG, and stored under `livestream-frame-previews/<youtube_video_id>.jpg`. Crop coordinates and sizes
are stored as normalized values on `LivestreamFrameArchive`, so the same rectangles
scale to the resolution selected by the capture worker. When all eight custom crop
values are present, the worker uses them instead of `CROP_FILTER` defaults.

`upload_segment_artifacts()` stores only cropped images in a gzip tarball. Batch keys use:

```text
livestream-frame-batches/<youtube_video_id>/<start_second>-<end_second>.tgz
```

Archive rows still also have an older `s3_prefix` of:

```text
livestream-frames/<youtube_video_id>/
```

The scanner reads from `batch_s3_key`, so preserve that field and tar member naming:

```text
<frame_second>_<score|timer>.jpg
```

## Admin Pages And APIs

The admin UI for this feature is server-rendered Flask. The templates submit normal forms; there is no React frontend call path for these pages.

Browser/admin routes:

- `GET/POST /livestream_frame_archives`
  - The list is paged at 50 rows and has text search for event name/event ID or
    YouTube ID. Status links group pending/cancelled as ready and
    probing/ready/running as in progress; bad rows are classified only as bad,
    regardless of their stored worker status. Only capture segments for the
    current page are loaded during normal list views.
  - Event-date sorting uses descending maximum day number and then descending
    maximum mat number within each event date.
  - `sync`: discover archive rows from livestreams.
  - `queue_missing`: queue every non-success archive.
  - `queue_selected`: queue checked YouTube IDs.
  - `retry_failed`: requeue error segments.
  - `retry_cancelled`: requeue cancelled segments.
  - `cancel_queued`: cancel pending/queued segments.
  - `cancel_running`: cancel running segments.
  - `toggle_bad`: toggles the no-scoreboard-data flag for checked archive rows. With
    no checked rows it is a no-op. Marking an archive bad removes its text scan,
    text scan segments, and text events after clearing downstream match links.
  - Actions labeled for selected rows remain page-scoped through their checkboxes;
    queue-missing and unselected retry/cancel actions retain their global behavior.
- `GET/POST /livestream_frame_archives/<archive_id>`
  - shows archive metadata, segment rows, S3 batch prefix, errors, and livestream usages.
  - uploads a custom S3 preview and saves draggable scoreboard/timer crop rectangles.
  - `requeue_completed`: requeues successful/skipped capture segments and clears upload metadata.
- `GET/POST /livestream_frame_text_scans`
  - `queue_ready`: queue scans for successful archives with successful capture segments and no scan yet.
  - `queue_selected`: queue selected successful archives.
  - `retry_failed`, `retry_cancelled`, `cancel_queued`, `cancel_running`.
  - `clear_selected`: deletes text events, clears match links, resets eligible scan segments.
- `GET/POST /livestream_frame_text_scans/<archive_id>`
  - shows scan segments and OCR events.
  - POST relinks a completed scan via `link_completed_text_scan()`.
- `GET /api/livestream_frame_text_scans/<archive_id>/events/<event_id>/captures/<scoreboard|timer>`
  - downloads the archived crop used by a text event.

Capture worker JSON endpoints:

- `POST /api/livestream_frame_archives/worker/segments/claim`
- `POST /api/livestream_frame_archives/worker/archives/<archive_id>/probe_start`
- `POST /api/livestream_frame_archives/worker/archives/<archive_id>/probe_complete`
- `POST /api/livestream_frame_archives/worker/segments/<segment_id>/complete`
- `POST /api/livestream_frame_archives/worker/segments/<segment_id>/error`

Text scanner JSON endpoints:

- `POST /api/livestream_frame_text_scans/queue`
- `POST /api/livestream_frame_text_scans/retry`
- `POST /api/livestream_frame_text_scans/cancel`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/claim`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/rescan`
- `POST /api/livestream_frame_archives/worker/archives/<archive_id>/text_scan/reset`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/complete`
- `GET /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/initial_state`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/error`

Remote workers depend on the payload helpers in `admin/app.py`: `_archive_payload()`, `_segment_payload()`, `_text_scan_payload()`, `_text_scan_segment_payload()`, and `_text_event_payload()`. Keep those in sync with worker `ApiObject` expectations when adding fields.

In remote mode, the worker clients retry connection/timeouts and transient HTTP
responses (`429`, `500`, `502`, `503`, `504`) up to four total attempts with
exponential backoff, but only for replay-safe calls. Capture probe and segment
success/error updates, text-scan initial-state reads, and text-scan
success/error updates are replay-safe. Segment claims are intentionally not
retried because a lost claim response may still have assigned the segment;
text-scan rescan/reset calls are also one-shot because they clear state or
increment attempt counts.

## Key Data Items

`LivestreamFrameArchive` is one row per YouTube video:

- Identity/source: `youtube_video_id`, `canonical_url`, `s3_prefix`.
- Classification: `is_bad` marks an archive as having no scoreboard data.
- Status/progress: `status`, `frame_rate`, `image_format`, `duration_seconds`, `expected_frame_count`, `uploaded_frame_count`, `last_uploaded_second`.
- Probe metadata: `format_id`, `format_note`, `width`, `height`, `source_fps`, `video_codec`, `audio_codec`, `tbr`, `protocol`, `yt_dlp_version`.
- Operations: `last_error`, `queue_requested_at`, `started_at`, `completed_at`.

Archive statuses are:

```text
pending, probing, ready, queued, running, partial, success, error, cancelled
```

`LivestreamFrameCaptureSegment` is one YouTube time range for a capture worker:

- Range: `start_second`, `end_second`.
- Status/progress: `status`, `attempt_count`, `uploaded_frame_count`, `sampled_frame_count`, `last_uploaded_second`.
- S3 batch: `batch_s3_key`, `batch_uploaded_at`.
- Operations: `background_task_id`, `last_error`, `started_at`, `finished_at`.

Capture segment statuses are:

```text
pending, queued, running, success, error, cancelled, skipped
```

`LivestreamFrameTextScan` is one OCR scan per archive:

- `archive_id`, `status`, `parser_profile`, `score_engine`, `name_engine`.
- `total_segment_count`, `processed_segment_count`, `last_processed_second`.
- `background_task_id`, `last_error`, `started_at`, `completed_at`.

`LivestreamFrameTextScanSegment` maps one successful capture segment into scanner work:

- `scan_id`, `archive_id`, `capture_segment_id`.
- `start_second`, `end_second`, `status`, `attempt_count`, `event_count`.
- `last_processed_second`, `background_task_id`, `last_error`, timestamps.

Text scan statuses are:

```text
pending, queued, running, partial, success, error, cancelled
```

Text scan segment statuses are:

```text
pending, queued, running, success, error, cancelled, skipped
```

`LivestreamFrameTextEvent` is a sparse OCR state change:

- Foreign keys: `scan_id`, `archive_id`, `scan_segment_id`, `capture_segment_id`, optional `match_id`.
- Position: `frame_second`.
- Scoreboard fields: top/bottom points, advantages, penalties.
- State fields: `scoreboard_state`, `timer_state`, `timer_value`.
- Name fields: top/bottom athlete/team names.
- OCR metadata: `profile_id`, `score_engine`, `name_engine`, `confidence`, `evidence_json`.

Events are unique per `(archive_id, frame_second)`. Scanner code only emits events when scoreboard/timer state changes; names are read and attached for those event frames rather than emitted as name-only events.

## Match Linking

`mark_text_scan_segment_success()` automatically calls `link_completed_text_scan()` when the scan reaches `success`. The admin detail page can also relink manually.

`link_completed_text_scan()`:

- Reconstructs text state from sparse events.
- Extracts match windows from visible zero-score starts, running timers, blank scoreboards, victory screens, and final score/timer states.
- Loads candidate `Match` rows by the archive's `LiveStream` usages.
- Scores candidate orientation with OCR names using `rapidfuzz`.
- Stores event `match_id`, match `video_start_offset_seconds`, final score/time fields, and participant `scoreboard_position`.

Requeueing or clearing scanner work calls `clear_livestream_match_links()`, which removes event associations and clears match/participant livestream-derived fields for the archive.

## Operational Notes

- `claim_next_segment()` orders archive capture work by `queue_requested_at`, archive creation time, then segment start. Admin `queue_missing` and `queue_selected` deliberately assign slightly offset `queue_requested_at` values so streams process in selected/dashboard order.
- Failed capture segments are automatically claimable after exponential backoff. Defaults are 300 seconds base and 1800 seconds max. When fresh and retry-eligible work coexist, claims reserve one retry after every three fresh segments by default; `--fresh-segments-per-error-retry` changes that ratio without tying retry progress to queue size or segment duration.
- Text scan segments are claimed sequentially within a scan; a later segment is blocked until earlier segments are successful/skipped. This preserves correct `reconstruct_text_state()` behavior across segment boundaries.
- `queue_text_scan()` requires a successful archive and clears existing match links for that archive.
- Bad archives cannot be queued or claimed for capture or text scanning. They show
  `Bad / no scoreboard data` in the archive dashboard's Segments column and are omitted
  from the text scan dashboard.
- `reset_text_scan_for_rescan()` refuses to reset while scan segments are running.
- `S3_BUCKET` must be configured for both capture upload and scanner read paths.
- Remote workers require `LIVESTREAM_ARCHIVE_ADMIN_URL` and `LIVESTREAM_ARCHIVE_ADMIN_PASSWORD` or `ADMIN_PASSWORD`.
- YouTube extraction behavior is sensitive to `yt-dlp`, cookies, JS runtime, extractor args, and available formats. See `YTDLP_COOKIES`, `YTDLP_COOKIES_CONTENT`, `YTDLP_COOKIES_BASE64`, `YTDLP_COOKIES_FROM_BROWSER`, and `YTDLP_EXTRACTOR_ARGS`.

## Tests To Run

For ordinary changes to archive queueing, worker API contracts, admin actions, match linking, or non-OCR scanner state logic:

```bash
make test
```

Focused files covered by `make test` include:

- `app/tests/test_livestream_frame_archive.py`
- `app/tests/test_livestream_match_linking.py`
- `app/tests/test_livestreams.py`

For OCR/parser/image fixture changes, run the expensive OCR target:

```bash
make test-ocr
```

`make test-ocr` runs `app/tests/test_livestream_frame_text_scan.py` with `RUN_OCR_TESTS=1`. Do not run it for routine archive/admin/linking-only changes.

Useful targeted commands while iterating:

```bash
cd app/tests && python3 -m unittest test_livestream_frame_archive
cd app/tests && python3 -m unittest test_livestream_match_linking
cd app/tests && RUN_OCR_TESTS=1 python3 -m unittest test_livestream_frame_text_scan
```

Check the repository root shell environment before assuming global `python3` is correct; this repo may rely on a local pyenv.

## Previously Surfaced Issues From Git History

The git history for these files shows recurring problem areas:

- YouTube format selection and `yt-dlp` behavior:
  - `75b6bb7 add fallback video format when best* fails`
  - `7c56e7a Fallback when livestream format selector fails`
  - `daed071 Prefer video formats for livestream frame worker`
  - `7c587b7 change default format`
  - `9c9c17b set video format selector back`
  - `60e7470 get 1080p videos when available`
  - `472b0cd Revert "get 1080p videos when available"`
- DASH fragment handling and ffmpeg download behavior:
  - `f069639 work around ffmpeg downloading error`
  - `5703675 fix another DASH error`
  - `dc4d438 fix another DASH issue and add debug logging`
- YouTube cookies and extractor diagnostics:
  - `afd4c88 Add livestream worker cookie support`
  - `1e5d937 Log livestream worker cookie diagnostics`
  - `b987443 try changing yt-dlp flags to avoid embedding error`
- Retry/cancel/error handling:
  - `2976a08 Clear archive errors when retrying livestream segments`
  - `b68ddd8 clear all errors`
  - `f20f743 clear errors from archives`
  - `d518b8f add automatic error retry with backoff`
  - `9ea3999 retry errors earlier`
  - `6a5480e truncate errors`
  - `7132eda fix clear button`
  - `0eb6cce try to improve ffmpeg performance and requeue cancelled segments`
- Segment coverage and batching:
  - `e3b2b0a upload frames in batches`
  - `20ae725 cover partial ranges`
  - `2f1e0df change default segment size`
  - `b928ffe make initial segment size configurable`
  - `ce613d9 store only cropped images`
- Crop dimensions:
  - `2176213 increase scoreboard crop size`
  - `bb1cc73 Revert "increase scoreboard crop size"`
  - `c063910 Reapply "increase scoreboard crop size"`
  - `4ad68f6 increase crop size slightly`
- Text scan and linker instability:
  - `d55f2e1 add livestream frame text scan worker / tables`
  - `c4a37c4 add text scan admin panel`
  - `94403c2 support blank scoreboards and fix formatting`
  - `3fee424 athlete name scanning fix`
  - `aaa36f9 allow re-scanning streams`
  - `67fb82a change --scan-id to --archive-id`
  - `0f822c5 add match linking prototype`
  - `6161268 move text events to matches table`

Before changing extraction, crop dimensions, queue ordering, or retry semantics, inspect nearby tests and consider adding regression coverage. These areas have changed repeatedly because production YouTube streams and OCR inputs vary more than local fixtures.
