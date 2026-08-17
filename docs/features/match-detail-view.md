# Match Detail View

Also called Score Detail View.

## User-Facing Behavior

The match detail view shows a refined timeline of score events for one match. It
combines raw OCR/livestream score changes into readable score actions, appends a
final result row, and links each row to the best available YouTube offset when a
video source is known.

When a DQ result has no participant marked as the winner, the final row names
both participants and says they were disqualified instead of rendering an empty
winner name. The modal title falls back to red-versus-blue participant order in
that case. A DQ with a marked winner retains the usual "won by DQ" wording and
winner-first title order.

When the final timer is missing, the result does not infer points or submission
from the score alone. The API uses the generic `Final` method, which the UI
renders as "<winner> won" when a winner is known. DQ notes continue to take
precedence, and a positive final timer is classified as a submission.

Users can reach it from:

- bracket matches in `app/frontend/src/components/BracketTree.tsx`
- database match rows in `app/frontend/src/components/DBTableRows.tsx`
- the reusable detail component in `app/frontend/src/components/MatchDetailView.tsx`

The bracket view opens `MatchDetailModal`. Database rows can open the modal or
expand an inline `MatchDetailView`.

Score-detail controls are shown only when the match's video action is also
visible. In particular, a livestream segment with `hide_all` enabled suppresses
both the YouTube action and the score-detail (+) action; displayed final scores
remain non-interactive. OCR/archive links resolve visibility at the exact stream
segment, so this remains true when one YouTube upload contains both visible and
hidden ranges and when the tournament's matches have no mat numbers.

On mobile, the Event column wraps within the available width in both the modal
and the inline Database card so the score-detail table does not extend past the
viewport.

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
  videoLeadSeconds: number;
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
- A score decrease that returns to at least its prior value within 6 frame
  seconds is treated as a momentary scorekeeper mistake. The temporary lower
  value is ignored, and any increase beyond the prior value is emitted as the
  net positive delta from that prior value.
- Negative deltas normally cancel prior score events. Long-delay negative deltas
  are treated as review retractions and leave the original award visible with a
  retraction event.
- Consecutive score changes for the same participant are combined into one
  response event when each change occurs no more than 6 frame seconds after the
  previous change. This can form an indefinite chain; the match timer is not
  considered. A participant change starts a new response event, even at the same
  frame second. The combined event keeps the first change's match time and video
  offset.
- A penalty that brings a participant's total to 2 is combined with an adjacent
  1-advantage award for the opponent. A penalty that brings the total to 3 is
  combined with an adjacent 2-point award for the opponent. Adjacency uses the
  same 6-frame-second window.
- Opposing penalty events within the adjacency window form a double-penalty
  group. The group also includes either penalty's adjacent automatic advantage
  or point award when present. Its text starts with "Double penalties received"
  and then lists any included awards by participant.
- Combined-event text preserves each points action separately, except that
  repeated 1-point actions for the same participant are added together because
  BJJ has no standalone 1-point score. Repeated advantage actions and repeated
  penalty actions for the same participant are also added together.
- Every emitted score event includes running totals for both participants.
- Event match times count down from the latest running-timer snapshot. A stopped
  timer invalidates that running anchor, so subsequent events keep the stopped
  timer value until a new running snapshot resumes the countdown.
- A clock increase to a whole-minute starting value trims later OCR events only
  after a non-zero score has appeared and the scoreboard has subsequently gone
  blank. This filters post-match clock resets and replayed score events without
  treating a pre-start `10:00 -> 0:00 -> 10:00` correction or a stopped-clock
  adjustment such as `3:59 -> 4:00` as the end of the match.
- The final event is always appended and uses final match fields, not the last
  OCR score snapshot alone.
- `videoOffsetSeconds` is stored in seconds from the source video. Each event also
  includes the backend-computed `videoLeadSeconds`, and the frontend opens YouTube
  links that many seconds before the offset: 8 seconds for standalone
  penalty events, 15 seconds for other score events, 2 seconds for final wins by
  points, 15 seconds for submissions with a final points difference of 2 or
  less, 8 seconds for submissions with a final points difference greater than
  2, and 10 seconds for other final rows. The backend is the sole owner of this
  calculation; the frontend consumes the required field directly.
- The authenticated admin `GET /api/highlights/score-events` candidate contract
  exposes this value as `video_lead_seconds` for match-start, score, submission,
  and decision rows so downstream highlight tools use the same pre-roll as Match
  Detail.
- Its `event_type` filter accepts `submission` (the default), `match_start`,
  `decision`, `score`, and `all`. Match-start rows use the linked match's first
  running-clock video offset. Decision rows are non-DQ final events at `0:00`;
  `all` returns match starts and score actions together with submission and
  decision finals.
- The optional `days` filter limits candidates to the previous 1–90 days. When
  omitted, candidates are not date-limited. The default result `limit` is 30.
- The `gi` filter defaults to `true`; callers can explicitly request `false` or
  `all`.
- Candidate filters also support exact, case-insensitive `Athlete.name` matching
  through `athlete_name` (never `personal_name`), exact division `gender`, and `elite`
  values `tier3`, `tier2`, or `tier1`. Elite matching uses the participant's
  current Gi/No-Gi rating, requires a mature ranked adult/juvenile badge on an
  eligible belt, excludes masters badges, and applies strict percentile cutoffs
  of `.10`, `.05`, and `.02` respectively.
- Candidate match selection applies linked-event, exact event/athlete, division,
  Gi/No-Gi, gender, and elite filters in SQL before loading match rows. Remaining
  event-type and score-action checks are derived from OCR details while candidate
  matches stream in batches of 100. Thus even an unfiltered all-time request does
  not materialize the full match database in application memory.
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
  - `test_momentary_score_dip_is_folded_into_restored_total`
  - `test_momentary_score_dip_and_exact_restore_are_suppressed`
  - `test_score_dip_recovery_outside_grace_period_remains_visible`
  - `test_score_change_in_other_field_does_not_restore_dip`
  - `test_partial_score_dip_recovery_is_not_suppressed`
  - `test_same_first_names_use_cleaned_full_names`
  - `test_same_timestamp_scores_are_combined_into_one_event`
  - `test_event_time_uses_running_timer_anchor_and_frame_offset`
  - `test_event_time_pauses_while_timer_is_stopped`
  - `test_prestart_zero_timer_flip_does_not_hide_match_events`
  - `test_stopped_timer_adjustment_to_whole_minute_keeps_later_events`
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
