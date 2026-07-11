# Livestream Frame Text Scanner

## User-Facing Behavior

The livestream frame text scanner is the second stage in the livestream video pipeline:

1. The livestream frame archiver captures scoreboard and timer crops from YouTube livestream frames and stores compressed frame batches in S3.
2. The text scanner runs OCR over those archived crops, parses sparse scoreboard/timer/name changes, and stores scan status plus text events in the database.
3. The match linker consumes completed text events to link video windows back to matches.

Admins can queue, retry, cancel, clear, inspect, and rescan text-scanning work from the admin app. OCR fixture tests are split from the normal test target because they are slow.

## Main Code Paths

- `app/livestream_frame_text_scan.py` is the scanner state machine. It owns scan queueing, segment claiming, S3 frame-batch reads, sparse event generation, state reconstruction, rescan/reset helpers, status recomputation, and success/error marking.
- `app/livestream_frame_text_ocr.py` is the image parser. It contains fixed-digit scoreboard/timer readers, name OCR support, parser profile selection, OCR engine validation, and `build_parser()`.
- `scripts/scan_livestream_frame_text.py` is the worker CLI. It can claim the next segment from the admin API, rescan a segment, reset an archive from the start, run OCR, and submit events/errors back to the admin API.
- `admin/app.py` contains the admin pages and JSON endpoints for queueing scans and for worker coordination.
- `admin/templates/livestream_frame_text_scans.html` is the scan list/action page.
- `admin/templates/livestream_frame_text_scan_detail.html` shows one archive's scan status, segments, events, livestream usages, and frame-crop download links.
- `.github/workflows/livestream-frame-text-scanner-image.yml` builds and pushes `ghcr.io/weisserw/ibjjf-elo-livestream-frame-text-scanner` from `Dockerfile.livestream-frame-text-scanner`.
- `app/migrations/versions/b2a4d8c9f103_add_livestream_frame_text_scan_tables.py`, `d9a7e4f3c2b1_add_livestream_scoreboard_state.py`, `8c7f2a91e4b3_add_ocr_match_links.py`, and `1c2d3e4f5a6b_move_text_events_to_matches.py` are the relevant schema history.

## Flow

`queue_text_scan()` creates one `LivestreamFrameTextScan` per successful archive and creates scan segments that correspond to archive capture segments. Each queue request records its position, so admin bulk queue actions preserve the dashboard's current sort order (and selected rows preserve their submitted order). `claim_next_text_scan_segment()` uses that recorded queue order before marking the next queued segment as running and incrementing attempts. The worker then:

Archives marked `is_bad` for having no scoreboard data are excluded from this
dashboard and rejected by queue, retry, reset, rescan, and worker claim paths.
Toggling an archive to bad from the frame archive dashboard clears its match links
and deletes its text scan, including text scan segments and events.

1. Builds a parser with `build_parser(parser_profile, score_engine, name_engine)`.
2. Builds an `S3FrameBatchProvider` for the archive's capture segments.
3. Gets the previous sparse state from `reconstruct_text_state()` when needed.
4. Calls `scan_frame_text_segment()` over the segment's second range.
5. Persists sparse `LivestreamFrameTextEvent` rows with `mark_text_scan_segment_success()` or records `mark_text_scan_segment_error()`.

The scanner emits sparse events, not one row per frame. Score/name/timer changes are compared against the reconstructed state. Running timer tickdown and OCR jitter are intentionally filtered so the database mostly captures meaningful score, state, timer-stop/blank, and name events.

## Admin Pages And APIs

The admin UI for this feature is server-rendered Flask. The templates submit normal forms; there is no React frontend call path for these pages.

Browser/admin routes:

- `GET/POST /livestream_frame_text_scans`
  - `queue_ready`: queue successful archives that do not already have text scans.
  - `queue_selected`: queue checked archives.
  - `retry_failed`: requeue failed scan segments.
  - `retry_cancelled`: requeue cancelled scan segments.
  - `cancel_queued`: cancel pending/queued scan segments.
  - `clear_selected`: delete text events and clear downstream match links for selected scans.
- `GET/POST /livestream_frame_text_scans/<archive_id>`
  - shows archive metadata, scan status/progress, segment status counts, events, livestream usages, and frame-crop links.
  - supports segment/archive rescan actions from the detail page.
- `GET /livestream_frame_text_scans/<archive_id>/events/<event_id>/<crop_variant>`
  - returns the archived scoreboard or timer crop for a text event.

JSON admin routes:

- `POST /api/livestream_frame_text_scans/queue`
  - body: `archive_ids`, optional `parser_profile`, `score_engine`, `name_engine`.
  - queues scans and returns queued scan payloads/counts.
- `POST /api/livestream_frame_text_scans/retry`
  - body: optional `scan_ids`.
  - retries failed segments globally or for selected scans.
- `POST /api/livestream_frame_text_scans/cancel`
  - body: optional `scan_ids`.
  - cancels pending/queued segments globally or for selected scans.

Worker API routes share `WORKER_API_PREFIX = /api/livestream_frame_archives/worker/` and skip normal admin login when authorized with the worker password:

- `POST /api/livestream_frame_archives/worker/text_scan_segments/claim`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/rescan`
- `POST /api/livestream_frame_archives/worker/archives/<archive_id>/text_scan/reset`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/complete`
- `GET /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/initial_state`
- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/error`

## Key Data Items

- `LivestreamFrameTextScan`
  - One row per archive, unique on `archive_id`.
  - Important fields: `status`, `parser_profile`, `score_engine`, `name_engine`, `total_segment_count`, `processed_segment_count`, `last_processed_second`, `background_task_id`, `last_error`, `started_at`, `completed_at`.
  - Statuses: `pending`, `queued`, `running`, `partial`, `success`, `error`, `cancelled`.
- `LivestreamFrameTextScanSegment`
  - One row per text-scan work unit, tied to a capture segment.
  - Important fields: `scan_id`, `archive_id`, `capture_segment_id`, `start_second`, `end_second`, `status`, `attempt_count`, `event_count`, `last_processed_second`, `background_task_id`, `last_error`, `started_at`, `finished_at`.
  - Statuses: `pending`, `queued`, `running`, `success`, `error`, `cancelled`, `skipped`.
- `LivestreamFrameTextEvent`
  - Sparse OCR event rows for scoreboard/timer/name changes.
  - Score fields: `top_points`, `top_advantages`, `top_penalties`, `bottom_points`, `bottom_advantages`, `bottom_penalties`.
  - State fields: `scoreboard_state`, `timer_state`, `timer_value`, `frame_second`.
  - Name fields: `top_athlete_name`, `top_team_name`, `bottom_athlete_name`, `bottom_team_name`.
  - Provenance fields: `profile_id`, `score_engine`, `name_engine`, `confidence`, `evidence_json`.
  - Downstream linking uses `match_id`; clearing text events must also clear match links.
- In-memory scan dataclasses in `app/livestream_frame_text_scan.py`
  - `FrameReading`: raw parser output for one frame.
  - `TextState`: reconstructed state before a frame/segment.
  - `TextEventData`: sparse event payload before database persistence.

Default parser settings are `parser_profile="auto"`, `score_engine="fixed_digit"`, and `name_engine="paddle"`. Supported score engines are `none` and `fixed_digit`; supported name engines are `none`, `tesseract`, and `paddle`.

## Worker CLI

Use `scripts/scan_livestream_frame_text.py` for local or containerized processing.

Common options:

- `--claim-next`: claim one or more queued segments.
- `--max-segments`: how many claimed segments to process, default `1`.
- `--archive-id`: restrict claiming/reset to one archive.
- `--youtube-id`: restrict claiming by YouTube video ID.
- `--segment-id`: rescan one segment.
- `--rescan-from-start --archive-id <uuid>`: reset an archive's text scan and process from the beginning.
- `--parser-profile`, `--score-engine`, `--name-engine`: parser controls.
- `--admin-url`, `--admin-password`: use the admin worker API instead of importing the app locally.
- `--background-task-id`: associate worker updates with an admin background task.

## Tests

Run from the repository root:

- `make test` for normal unit coverage outside the livestream frame text scanner suite.
- `make test-ocr` for livestream frame text scanner changes. The Makefile excludes `test_livestream_frame_text_scan.py` from `make test`; this target sets `RUN_OCR_TESTS=1` and runs the scanner suite, including the slow OCR fixture coverage.

Relevant tests live in `app/tests/test_livestream_frame_text_scan.py`:

- `LivestreamFrameTextScanAlgorithmTestCase`: sparse event generation, timer filtering, name/score change handling, and segment-boundary behavior.
- `LivestreamFrameTextScanDbTestCase`: queue/claim/reset/retry/cancel/clear behavior and S3 frame-batch reading.
- `ScanLivestreamFrameTextWorkerTestCase`: CLI/API worker behavior and parser/name OCR logic.
- `LivestreamFrameTextOcrFixtureTestCase`: expensive OCR fixture coverage under `app/tests/fixtures/livestream_ocr`.
- `LivestreamFrameTextScanAdminApiTestCase`: admin and worker JSON endpoint behavior.

## Known Historical Issues

Git history shows this area is sensitive to OCR edge cases and workflow/status handling. Before editing, check nearby commits and tests for regressions in these categories:

- Score digit ambiguity: fixes include `1 -> 3`, `3 -> 8`, bad `2*`, double-digit scores, smaller two-digit scores, and adaptive scoreboard width.
- Timer interpretation: previous fixes covered running/stopped mis-detection, blank timers emitting `stopped`, font differences between systems, digit errors, and extra events from clock jitter.
- Name OCR: multiple commits fixed athlete/team line selection, multi-line names, Paddle result parsing, Paddle choosing team names, and clipped/trailing initials.
- Scoreboard visibility: blank scoreboard handling and scoreboard detection have had regressions.
- Worker/admin state: requeue/rescan buttons, clear behavior, missing OCR, Docker dependencies, automatic retry/backoff, error truncation, and livestream queue ordering have all been adjusted.
- Pipeline coupling: a previous change moved text events toward match linkage, and match-linking fixes mention blank windows; clearing or changing events can affect linked matches.

When making behavior changes, prefer adding or tightening focused tests in `app/tests/test_livestream_frame_text_scan.py` before changing OCR heuristics broadly.
