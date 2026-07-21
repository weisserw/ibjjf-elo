# Livestream Match Linker

## User-Facing Behavior

The livestream match linker connects completed OCR text-scan events to `Match`
rows. It groups sparse `LivestreamFrameTextEvent` rows into logical match
windows, chooses the most likely scheduled match for each window, and stores:

- `LivestreamFrameTextEvent.match_id` on every linked event in the window.
- `Match.video_start_offset_seconds`.
- `Match.final_match_time_seconds`.
- `Match.final_top_*` and `Match.final_bottom_*` score fields.
- `MatchParticipant.scoreboard_position` as `top` or `bottom`.

Participant positions are inferred from the first sufficiently confident pair
of names OCR observes after the timer starts. Pre-start name history remains
available for identifying the scheduled match, but it cannot override a
scoreboard-side correction made before the clock begins. Once the initial
window stores the positions, continuation windows do not rewrite them from
later OCR noise.

It can run automatically as the final step of the livestream archive pipeline,
or manually through the admin detail page or CLI.

## Main Code Paths

- `app/livestream_match_linking.py` owns the linking logic.
  - `extract_match_windows()` converts sparse OCR events into `MatchWindow`
    objects.
  - `load_candidates_for_archive()` loads candidate `Match` rows from
    `LiveStream` usages that point at the archive's YouTube video.
  - `choose_match_for_window()`, `choose_active_continuation_for_window()`,
    and `choose_continuation_for_window()` score candidates and handle windows
    that split or continue across OCR resets.
  - `link_completed_text_scan()` is the main write path.
  - `clear_livestream_match_links()` removes links and livestream-derived
    match/participant fields for one archive.
  - `analyze_text_scan_links()`, `analyze_candidate_loading()`, and
    `livestream_rows_for_archive()` support CLI diagnostics.
- `app/livestream_frame_text_scan.py`
  - `mark_text_scan_segment_success()` calls `link_completed_text_scan()` when
    the whole scan reaches `success`.
  - `replace_segment_events()` clears existing links before replacing events
    for a segment.
- `scripts/link_livestream_matches.py` is the standalone diagnostic and write
  script.
- `docs/workflows/LIVESTREAM_MATCH_LINKING_REGRESSIONS.md` describes how to
  export production OCR spans into regression fixtures.
- `app/tests/test_livestream_match_linking.py` contains the focused unit and
  regression coverage.

## Flow

Automatic pipeline flow:

1. Frame archiver captures cropped scoreboard/timer images.
2. Text scanner OCR creates sparse `LivestreamFrameTextEvent` rows.
3. When the last scan segment completes and scan status becomes `success`,
   `mark_text_scan_segment_success()` invokes `link_completed_text_scan()`.

`link_completed_text_scan()`:

1. Resolves either a scan ID, archive ID, or scan object through
   `_scan_from_id()`.
2. Skips unless the text scan status is `success`.
3. Loads events ordered by `frame_second`.
4. Extracts match windows from zero-score starts, running timers, blank
   scoreboards, victory screens, stopped timers, and score changes.
5. Clears prior links for the archive unless running in dry-run mode.
6. Loads candidate matches for the archive's livestream rows.
7. Scores name history and time alignment to identify the match, locks athlete
   orientation from confident post-start name pairs, tracks used/closed
   matches, and applies continuation fallback for split windows.
8. Writes event links and match summary fields, then returns a summary with
   `linked`, `windows`, `candidates`, and optional `skipped`.

Full tournament CSV imports also relink every successful text scan whose
archived YouTube video is used by that tournament. This runs after replacement
matches and participants have been flushed and before the import transaction is
committed, so replacing match rows does not require manual relink actions for
every mat and day. Partial-tournament imports do not trigger this relink.

## Admin Pages And APIs

There is no React frontend call path for this feature in `app/frontend`.
The UI is server-rendered Flask admin pages and worker JSON endpoints.

Admin/browser routes:

- `GET/POST /livestream_frame_text_scans`
  - `clear_selected` calls scanner cleanup (`clear_text_scan_events()`), which
    deletes text events, clears match links, and resets eligible scan segments.
- `GET/POST /livestream_frame_text_scans/<archive_id>`
  - `GET` displays scan segments and OCR events.
  - `POST` manually relinks a completed scan with `link_completed_text_scan()`.

Worker/API route involved in automatic linking:

- `POST /api/livestream_frame_archives/worker/text_scan_segments/<segment_id>/complete`
  - Marks a scan segment successful through `mark_text_scan_segment_success()`.
  - If this completes the scan, linking runs inside the same worker completion
    path.

Related scan management APIs are documented in
`docs/features/livestream-frame-text-scanner.md`.

## CLI

Run from the repository root:

```bash
python scripts/link_livestream_matches.py <scan_or_archive_id>
```

By default the script is diagnostic only. Use `--commit` to persist links.

Useful flags:

- `--verbose`: print top candidates for each OCR window.
- `--limit`: limit printed windows.
- `--match-id`: focus diagnostics on one match.
- `--around-second`: show windows near a stream second.
- `--candidate-coverage`: print all loaded candidates.
- `--candidate-load-debug`: show include/exclude diagnostics for match loading.
- `--livestream-rows`: show `live_streams` rows for the archive YouTube ID.
- `--skip-choice-debug`: explain why skipped windows did not link.

## Key Data Items

`LivestreamFrameTextEvent` is the OCR event stream:

- Identity/position: `scan_id`, `archive_id`, `scan_segment_id`,
  `capture_segment_id`, `frame_second`.
- Link: nullable `match_id`.
- Score: `top_points`, `top_advantages`, `top_penalties`, `bottom_points`,
  `bottom_advantages`, `bottom_penalties`.
- State: `scoreboard_state`, `timer_state`, `timer_value`.
- Names: top/bottom athlete and team names.

`MatchWindow` is an in-memory group of events:

- `start_second`, `end_second`, and `video_start_offset_seconds`.
- `events`.
- Deduped `top_names` and `bottom_names`.
- Chronological `position_name_pairs` observed after the timer starts, used to
  choose the first confident orientation.
- `final_state`, `final_timer_seconds`, and `has_running_timer`.

`Candidate` is an in-memory scheduled match:

- `match`.
- `participants`.
- `stream`.
- `order_index`.
- `expected_start_second`.

`MatchChoice` is an in-memory scoring result:

- `candidate`.
- `top_participant` and `bottom_participant`.
- `score`, `raw_score`, and `time_delta_seconds`.

Persistent match outputs live on `Match` and `MatchParticipant`:

- `Match.video_start_offset_seconds`.
- `Match.final_match_time_seconds`.
- `Match.final_top_points`, `final_top_advantages`, `final_top_penalties`.
- `Match.final_bottom_points`, `final_bottom_advantages`,
  `final_bottom_penalties`.
- `MatchParticipant.scoreboard_position`.

## Tests To Run

For ordinary linker changes:

```bash
make test
```

Focused iteration target:

```bash
cd app/tests && python3 -m unittest test_livestream_match_linking
```

Use `make test-ocr` only when OCR/parser/image behavior changes. Linker-only
changes should not need OCR tests.

When adding a production regression, follow
`docs/workflows/LIVESTREAM_MATCH_LINKING_REGRESSIONS.md`. The current fixture
directory is:

```text
app/tests/fixtures/livestream_match_linking/
```

Existing real-world fixtures cover stopped score updates, linking until blank
windows, and repeated athlete names split by blank resets. Synthetic
regressions also cover a pre-start top/bottom correction and reject later
continuation-window OCR swaps after positions have been locked.

## Previously Surfaced Issues From Git History

History for `app/livestream_match_linking.py`,
`app/tests/test_livestream_match_linking.py`, and
`scripts/link_livestream_matches.py` is dense with regression fixes. Before
changing heuristics, scan these commits and nearby tests:

- `32c90cc fix matches linking to blank window`
  - Non-cursor matches needed stronger top and bottom name evidence before a
    skipped or blank-ish window could link forward.
- `4f25948 fix more match linking problems`
  - Stopped zero timers, closed matches, cursor rollback, and continuation
    fallback could resurrect or misassign matches.
- `a0fe3fd dont link events after 0:00 timer`
  - Events after a terminal zero timer should not keep attaching to the match.
- `d3b15df fix another linking error`
  - Active continuations should beat duplicate-name rematches when the same
    names reappear before a true boundary.
- `603fad9 add new link window regressions and fix bugs`
  - Added coverage around continuation name matching and window boundary edge
    cases.
- `71958a8 fix another submission / no-submission mistake`
  - Submission/no-submission timer interpretation has affected final window
    extraction.
- `0cc7a34 fix some matches ending link events early`
  - Link windows previously ended too soon around timer/score transitions.
- `8b18599 tweak scoreboard-reset fix`, `432e81c update "zerod-scoreboard"
  fix to actually stop matching events`, and `6bbb685 small fix to maintain
  final score when scoreboard resets`
  - Zeroed scoreboard resets can wrongly erase final scores or keep matching
    events after a match has ended.
- `cdae3b2 fix video start times and tournament start days`
  - Candidate timing depends on event day calculation and livestream start
    times, not just OCR names.
- `892514b better match linking` and `0f822c5 add match linking prototype`
  - Baseline implementation and CLI/debug surface.

Current regression tests show the main risk areas:

- Real OCR fixtures:
  - `test_real_joao_maycon_fixture_links_stopped_score_update`
  - `test_real_atlanta_jasmine_kendra_fixture_links_until_blank`
  - `test_real_nashville_repeated_athletes_split_after_blank_reset`
- Window extraction and final state:
  - `test_extract_match_windows_tracks_final_score_and_submission_timer`
  - `test_zero_score_reset_after_blank_does_not_overwrite_nonzero_final_score`
  - `test_zero_score_correction_without_stopped_timer_does_not_end_window`
  - `test_prestart_names_survive_noisy_early_timer_events`
    - A stopped pre-start row and the first running row with the same opening
      timer stay in one window, preserving stronger names loaded before the
      clock starts even when the running row's OCR is noisy.
- Candidate choice:
  - `test_ambiguous_repeated_athlete_without_bottom_name_is_not_linked`
  - `test_forward_match_with_weak_opponent_side_waits_for_both_names`
  - `test_ambiguous_window_prefers_next_match_in_mat_order`
- Continuations and cursor behavior:
  - `test_over_split_same_match_window_links_as_continuation`
  - `test_duplicate_name_rematch_does_not_steal_active_continuation`
  - `test_closed_match_is_not_resurrected_by_continuation_fallback`
  - `test_time_aligned_match_can_link_beyond_cursor_lookahead`
  - `test_time_aligned_unused_match_can_link_after_cursor_passed_it`
  - `test_out_of_order_forward_link_can_be_reused_when_turn_arrives`
