# Match Detail View

Also called Score Detail View.

## User-Facing Behavior

The match detail view shows a refined timeline of score events for one match. It
combines raw OCR/livestream score changes into readable score actions, appends a
final result row, and links each row to the best available YouTube offset when a
video source is known.

Users can reach it from:

- bracket matches in `app/frontend/src/components/BracketTree.tsx`
- database match rows in `app/frontend/src/components/DBTableRows.tsx`
- the reusable detail component in `app/frontend/src/components/MatchDetailView.tsx`

The bracket view opens `MatchDetailModal`. Database rows can open the modal or
expand an inline `MatchDetailView`.

## Main Code Paths

Frontend:

- `app/frontend/src/components/MatchDetailView.tsx`
  - Defines the response interfaces used by the UI.
  - Fetches match details with Axios.
  - Formats score/retraction/final text.
  - Builds YouTube watch links from `videoSourceUrl` and `videoOffsetSeconds`.
  - Exports both the inline `MatchDetailView` and portal-based
    `MatchDetailModal`.
- `app/frontend/src/components/MatchDetailView.css`
  - Styles the modal, status text, table, score summary, and video link cells.
- `app/frontend/src/components/BracketTree.tsx`
  - Opens `MatchDetailModal` from bracket match score controls.
- `app/frontend/src/components/DBTableRows.tsx`
  - Opens `MatchDetailModal` from match actions/final score controls.
  - Expands inline `MatchDetailView` for card-style rows.

Backend:

- `app/routes/matches.py`
  - `match_detail_events(match_id)` handles
    `GET /api/matches/<match_id>/detail-events`.
  - `build_match_detail_payload(match, raw_events)` builds the JSON response.
  - `_build_match_detail_score_events(...)` turns raw OCR score snapshots into
    semantic score/retraction events.
  - `_cancel_prior_score_events(...)` handles score corrections.
  - `_match_detail_video_source_url(...)` prefers the linked archive canonical
    URL from raw OCR events and falls back to `match.video_link`.
  - `_final_video_offset_seconds(...)` picks the final row's video offset.
  - `_final_totals(...)`, `_ending_method(...)`, and `_winner_key(...)` derive
    the final score/result display.

Upstream dependency:

- `app/livestream_match_linking.py` links OCR events to matches and persists
  `LivestreamFrameTextEvent.match_id`, match video offsets, final score fields,
  and final timer fields. Bad linking or offset detection usually surfaces here
  as missing/wrong detail rows or wrong video links.

## Frontend API

`MatchDetailView` calls:

```text
GET /api/matches/<match_id>/detail-events
```

The route:

- parses `<match_id>` as a UUID
- returns `404 {"error": "Match not found"}` for invalid or missing matches
- loads `LivestreamFrameTextEvent` rows with `match_id == match.id`
- orders raw events by `frame_second`
- returns `build_match_detail_payload(match, raw_events)`

No separate frontend API client exists for this feature; the component calls the
endpoint directly with:

```ts
axios.get<MatchDetailResponse>(`/api/matches/${matchId}/detail-events`)
```

## Response Shape

The frontend expects this shape:

```ts
interface MatchDetailResponse {
  matchId: string;
  matchTime: string | null;
  videoSourceUrl?: string | null;
  participants: MatchDetailParticipant[];
  events: MatchDetailEvent[];
}
```

Participants are red/blue UI participants with scoreboard orientation:

```ts
interface MatchDetailParticipant {
  key: 'red' | 'blue';
  name: string;
  fullName: string;
  titleName: string;
  scoreboardPosition: 'top' | 'bottom';
}
```

Events are either score events or the final event:

```ts
interface MatchDetailEvent {
  kind: string;
  time: string | null;
  videoOffsetSeconds?: number | null;
  actions?: MatchDetailAction[];
  endingMethod?: string;
  endingMethodAmount?: number | null;
  winnerKey?: 'red' | 'blue' | null;
  athleteName?: string | null;
  totals: Record<'red' | 'blue', MatchDetailScore>;
}
```

Score actions carry one semantic score mutation:

```ts
interface MatchDetailAction {
  kind: string;
  participantKey: 'red' | 'blue';
  athleteName: string;
  category: 'points' | 'advantages' | 'penalties';
  delta: number;
  verb?: string;
}
```

## Data Semantics

- Raw OCR rows are `LivestreamFrameTextEvent` snapshots, not already-refined
  score events.
- Score state is tracked by scoreboard position (`top` / `bottom`) and category
  (`points`, `advantages`, `penalties`).
- Participant display maps scoreboard position to UI participant key
  (`red` / `blue`) through match participants.
- Positive deltas become score events.
- Negative deltas normally cancel prior score events. Long-delay negative deltas
  are treated as review retractions and leave the original award visible with a
  retraction event.
- Multiple score changes at the same timestamp are combined into one response
  event with multiple `actions`.
- Every emitted score event includes running totals for both participants.
- The final event is always appended and uses final match fields, not the last
  OCR score snapshot alone.
- `videoOffsetSeconds` is stored in seconds from the source video. The frontend
  opens YouTube links before that offset by event type: 15 seconds for score
  events, 2 seconds for final wins by points, and 10 seconds for submissions
  and other final rows.
- `videoSourceUrl` prefers the OCR event archive's `canonical_url`; if no
  archive URL is available, it falls back to the match's `video_link`.

## Tests To Run

For ordinary backend/detail payload changes:

```bash
(cd app/tests && python3 -m unittest test_match_detail_events)
make test
```

Run `make test` from the repository root. The local pyenv may matter, so use the
same shell environment that normally runs project tests.

For changes that affect upstream livestream matching, linked OCR events, final
scores, or detected video offsets, also run:

```bash
(cd app/tests && python3 -m unittest test_livestream_match_linking)
make test
```

Do not run `make test-ocr` unless changing OCR/livestream text scan behavior.
Do not run the frontend build as routine verification; `npm run build` in
`app/frontend` rewrites generated SEO snippet files.

Focused test file:

- `app/tests/test_match_detail_events.py`
  - `test_wrong_athlete_correction_cancels_previous_score`
  - `test_partial_correction_rewrites_previous_score_amount`
  - `test_correction_can_cancel_earlier_matching_score`
  - `test_review_retraction_keeps_award_and_adds_retraction`
  - `test_same_first_names_use_cleaned_full_names`
  - `test_same_timestamp_scores_are_combined_into_one_event`
  - `test_event_time_uses_running_timer_anchor_and_frame_offset`
  - `test_payload_includes_livestream_source_url_from_archive`
  - `test_final_event_includes_video_offset`
  - `test_final_method_classification`

## Previously Surfaced Issues From Git History

- `0a276cb match detail view first pass`
  - Added the backend endpoint, payload builder, frontend component, and initial
    unit coverage. Use this as the baseline when reconstructing intent.
- `a74bc3a match detail improvements`
  - Added per-event video offsets and `videoSourceUrl`, changed the loading text
    to "Loading score details", made the modal title winner-first, and added
    tests for archive source URLs and final event video offsets.
- `d082d53 add + icon for showing match details and change "awarded" to "was awawarded"`
  - Touched the visible affordance/copy for opening details and award wording.
    Be careful with translation keys in `app/frontend/src/translate.ts`.
- `a0164b2 fix score cancellations leaving a +1 score event`
  - `_cancel_prior_score_events` needed exact-delta matching before partial
    cancellation. Without it, corrections could leave an extra `+1` score event.
- `44ca8f2 prefer livestream videos over single-match videos where we have scoreboard info`
  - Live/video link selection changed to prefer livestream links with detected
    offsets when scoreboard-derived info exists. This affects the video source
    used by detail links.
- `840fef1 fix live links not using the detected video offset`
  - Similar offset bug in bracket live links. It was fixed in bracket code, but
    it is a reminder to verify that source URLs and offsets are paired
    correctly when changing video-link logic.
- `32c90cc fix matches linking to blank window`
  - Upstream linker could attach matches to blank/skipped OCR windows. Detail
    view symptoms are missing or wrong raw events for a match.
- `4f25948 fix more match linking problems`
  - Upstream issues around stopped zero timers, closed matches, cursor rollback,
    and continuation fallback could misassign windows.
- `d3b15df fix another linking error`
  - Active continuations needed to beat duplicate-name rematches before a true
    terminal boundary. Detail view symptoms are events from adjacent repeated
    athlete matches appearing on the wrong match.

When a detail view bug appears to be "wrong rows for this match", first check
whether `LivestreamFrameTextEvent.match_id` links and match final fields are
correct before changing display code.
