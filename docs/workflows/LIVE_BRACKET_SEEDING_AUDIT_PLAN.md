# Live Bracket Seeding And Layout Audit Plan

## Status

Implemented on September 3, 2026 through Phase 3. The pure parser/comparator,
shared prediction service, persistence, sequential worker, durable admin report,
and automated coverage are complete. Phase 4 remains a manual production-data
verification step.

This plan covers an admin-only, asynchronous audit of every published bracket in
one BJJCompsystem tournament. It compares the official ranking table and actual
first-round bracket geometry with the registration-based prediction produced by
this application.

The related pre-publication identity report is planned separately in
[`REGISTRATION_IDENTITY_AUDIT_PLAN.md`](REGISTRATION_IDENTITY_AUDIT_PLAN.md).

## Implementation Principle

This is a private, best-effort admin diagnostic, not a load-bearing production
workflow. Prefer existing helpers, a small schema, and obvious sequential code.
Parsing and comparison results must be trustworthy, but operational convenience
may have some warts: the admin can refresh the page manually, ignore a stale run
after a killed worker, and rerun the whole tournament after fetch failures. Do
not add abstraction or recovery machinery until repeated real use demonstrates
that it is needed.

## Why This Is A Separate Feature

The audit has two independent questions:

1. Did we calculate each competitor's seeding criteria correctly?
2. Given the official seeds, does `_bracket_slots(n)` reproduce the actual
   first-round matchups and visual order?

Keeping those results separate is essential. A points or identity error must not
be reported as a layout error, and a layout error must remain visible even when
all point totals are correct.

## Current Implementation Facts

- `app/routes/brackets.py` owns the live and registration APIs.
  - `categories()` fetches the male and female category indexes.
  - `competitors()` parses one live category page at a time.
  - `get_bracket_page()` provides a database-backed `BracketPage` HTML cache.
  - `parse_seed_swaps()` reads IBJJF's same-team swap list.
  - `add_canonical_display_match_numbers()` reverses those swaps when mapping the
    published match-number tree into canonical seed order.
- `app/seeding.py` is the source of truth for predicted criteria and geometry.
  - `add_seeding_data()` calculates points and champion criteria.
  - `add_estimated_seeds()` sorts all six supported seeding variants.
  - `_bracket_slots(n)` returns canonical first-round seed slots.
- `app/bracket_audit.py` now owns ranking, first-round, composed team-swap,
  reconciliation, criteria, and layout helpers. `scripts/bracket_initial_pairings.py`
  calls the shared implementation.
- Registration predictions are calculated by the shared
  `build_registration_prediction()` service. Completed audit categories retain
  immutable prediction rows and compared criteria in their report JSON.
- The admin is server-rendered Flask. `BackgroundTask` records task state and
  logs, and `/tasks/<id>` polls task status. Long-running subprocesses are
  launched by a short-lived thread through `_run_logged_process()` and can be
  cancelled by process group.
- Ranking tables use `div.tournament-category__ranking > table.table`, but the
  observed headers are not limited to one English regular-division shape. The
  completed discovery review below is the parser contract's evidence base.
- `BracketAuditRun` and `BracketAuditCategory` store durable results, while
  `scripts/audit_live_brackets.py` and the admin `/bracket_audits` pages provide
  background execution and report access.

See also:

- `docs/features/bracket-predictor.md`
- `docs/features/bracket-views.md`
- `docs/features/bracket-tree.md`
- `docs/workflows/BRACKET_LAYOUT_REVERSE_ENGINEERING.md`

## Completed Discovery Review

The September 3, 2026 review inspected the local `BracketPage` corpus rather
than relying on one live page. It contained 7,940 category pages captured from
February 12, 2025 through June 23, 2026: 7,341 pages with ranking tables and 599
without one.

Findings:

- Twenty-two exact header signatures collapse into the six seeding variants.
  The extra signatures are the dynamic Master 1 through Master 7 columns, two
  English Grand Slam header spellings, and Portuguese regular, adult-black, and
  master-black labels.
- Champion cells are not one type. Recent-title cells are `-`, one year, or a
  comma-separated year list; last-title cells are `-` or one year; former-world-
  champion cells are `No` or one year; all other observed champion flags are
  `Yes`/`No`. The Portuguese pages retained English `Yes`/`No` cell values.
- Across 4,396 seed/name spans on ranked pages with swaps, every seed and name
  matched the ranking row at that same number. Identity reconciliation must
  therefore join a bracket card's displayed seed directly to the ranking row.
  Swaps alter geometry, not the official ranking identity.
- Seven sampled pages reuse a seed in more than one swap. A flat two-way swap
  dictionary is incorrect for those pages; swaps must be applied in document
  order to form a permutation and reversed as a composed permutation for layout
  comparison.
- The retained `N=21` case has three swaps, including a repeated seed. Correct
  composition yields complete seed coverage and the same non-bye pairings as
  `_bracket_slots(21)`, but a different row order. Display order is intentionally
  canonicalized by the application and is ignored by the audit. The current
  helper's flat dictionary duplicates seed 18 and drops seed 17, so Phase 1 must
  replace, not merely move, that behavior.
- A missing ranking table does not prevent complete match-card and first-round
  parsing. Criteria remain `unverifiable`, while layout still runs.

The sanitized fixtures and their source/capture manifest are in
`app/tests/fixtures/bracket_audit/README.md`. They cover all six variants, an
absent table, English and Portuguese aliases, one swap, composed swaps, byes,
a play-in, and `N=21`.

### Confirmed Header Mapping

Map headers semantically; one official cell may produce more than one typed
evidence value. Do not require a one-to-one header-to-sort-field relationship.

| Observed header aliases | Typed field or evidence |
| --- | --- |
| `Nº — Competitor`, `Nº — Competidor` | `official_rank`, `name` |
| `Team`, `Academia` | `team` |
| `Grand Slam Pts`, `Grand Slam Overall PTS`, `PTS Grand Slam` | `grand_slam_points` |
| `Overall PTS`, `Overall PTS (without Open Class)`, `PTS Geral` | `points` |
| `Grand Slam Open Class PTS` | `grand_slam_open_class_points` |
| `Overall Open Class PTS` | `open_class_points` |
| `World Champion (Last 3 Editions)`, `Camp. Mundial (últ. 3 edições)` | `world_champion_recent_years`; derive `world_champion_recent` and the most recent year |
| `Last World Title` | `last_world_title_year` |
| `World Champ. Last Edition` | derived check that the most recent listed title is the latest eligible Worlds edition |
| `World Champ. Four Years Ago`, `Camp. Mundial (4 edições atrás)` | `world_champion_4_years_ago` |
| `World Champ. Five Years Ago`, `Camp. Mundial (5 edições atrás)` | `world_champion_5_years_ago` |
| `Last Brown Belt World Champion`, `Camp. Mundial Faixa Marrom` | `previous_brown_world_champion` |
| `Former World Champ.`, `Camp. Mundial` | `former_world_champion` (`No` becomes `None`) |
| `Adult World Champ.`, `Camp. Adulto` | `adult_world_champion` |
| `M{K} World Champ.`, `Camp. Mundial M{K}` | `master_{K}_world_champion` |

The adult-black open table intentionally exposes `World Champ. Last Edition`
instead of the weight-division `Last World Title`/`Former World Champ.` pair.
Compare all exposed official values and record locally used but unexposed sort
fields as `not_officially_exposed`; their absence is not a zero or a mismatch.
Final official-versus-estimated rank comparison remains required and makes any
effect of an unexposed criterion visible.

## Goals

- Let an admin select a currently published tournament and start one audit.
- Fetch all category pages sequentially with a small fixed delay.
- Parse the official ranking table without changing the existing live response
  contract.
- Compare every official criterion with an immutable prediction snapshot.
- Classify harmless random tie ordering separately from actionable differences.
- Independently validate bracket size, first-round pairings, and visual order
  after reversing team swaps.
- Record each category as it is processed so one broken page does not discard
  the rest of the report.
- Render a durable report that can be revisited after task completion.
- Give each discrepancy enough provenance to investigate identity, medal, date,
  multiplier, parser, or layout-table errors.

## Non-Goals For The First Version

- Automatically edit medals, athlete identities, event dates, or layout tables.
- Automatically accept fuzzy athlete matches.
- Scrape multiple tournaments concurrently.
- Replace the public Live or Registrations pages.
- Treat an absent ranking table as proof that our result is correct or wrong.
- Reconstruct a prediction that was literally shown in the past if no snapshot
  was saved then. The first version captures a reproducible snapshot at audit
  start; prospective prediction snapshots are a later enhancement.
- Retry individual HTTP requests, resume an interrupted run, or preserve a
  history of attempts. Start a fresh run later instead.
- Build a general-purpose scraping framework, configurable retry policy, or
  client-side report application.

## Comparison Vocabulary

Use explicit states throughout the database, worker, and UI:

- Ranking table: `parsed`, `absent`, `unsupported`, or `parse_error`.
- Competitor reconciliation: `matched`, `registration_missing`,
  `official_missing`, `ambiguous`, or `unresolved`.
- Criteria comparison: `match`, `tie_order_only`, `criteria_mismatch`,
  `identity_mismatch`, or `unverifiable`.
- Layout comparison: `exact`, `pairing_mismatch`, `seed_coverage_mismatch`, or
  `unverifiable`. Display order alone is ignored.
- Category processing: `pending`, `running`, `complete`, `skipped`, or
  `error`. Only Adult and Master 1–7 weight divisions are eligible; open-class
  weights and all other ages are skipped during discovery. Categories with
  fewer than four live athletes are skipped before criteria or layout analysis.

An overall category is clean only when all parsed criteria match and layout is
`exact`. Missing tables and unresolved identities must be reported as unknown,
not silently counted as clean.

## Proposed Persistence

Continue using `BackgroundTask` as the execution/log envelope. Keep persistence
to two audit tables; this report does not need normalized competitor rows or an
attempt history.

Add `BracketAuditRun`:

- UUID primary key and nullable `background_task_id` foreign key.
- External tournament ID/name and nullable `registration_link_id`.
- Status and timestamps.
- Registration source timestamp, seeding reference date, and medal cutoff.
- Total/discovered/processed/error category counts and summary discrepancy
  counts.
- Fatal error text, if discovery itself fails.

Add `BracketAuditCategory`:

- Run foreign key, external category ID, canonical URL, gender, age, belt, and
  weight; unique on `(run_id, category_url)`.
- Raw category labels, per-item status, cache timestamp, and error text.
- Detected seeding variant, raw normalized headers, and unmapped headers.
- Official competitor count, parsed bracket size, and theoretical bracket size.
- Ranking-table, reconciliation, criteria, and layout statuses.
- Counts for matched competitors, mismatched competitors, unresolved rows, and
  criteria fields that differ.
- One text-encoded JSON report payload containing official and estimated rows,
  reconciliation results, raw and typed criteria, swaps, actual/expected slots,
  and mismatch reasons. Text JSON matches existing cross-database conventions.

Keep only run/category states and summary counts in normal columns because the
admin list and report table query them. Render competitor details from the
category JSON. Do not store raw full HTML because `BracketPage` is already the
source cache; persist its URL and `saved_at` timestamp as evidence.

## Parser Refactor And Fixture Discovery

Create a route-independent module, tentatively `app/bracket_audit.py`, with pure
parsers and comparison helpers. Move or wrap reusable logic so that routes,
scripts, and tests call one implementation:

- Official ranking-table parser.
- Team-swap parser.
- Complete first-round slot parser currently in
  `scripts/bracket_initial_pairings.py`.
- Official-row to live-card identity reconciliation.
- Criteria normalization and comparison.
- Layout comparison.

Do not create a second category vocabulary in the audit module. Parse category
cards with the existing `parse_categories()` helper, then canonicalize their raw
labels with `translate_age_keep_juvenile()`, `translate_belt()`,
`translate_weight()`, and `translate_gender()` from `app/constants.py`. Use the
existing `ADULT`, `BLACK`, `MASTER_PREFIX`, `OPEN_CLASS`, `OPEN_CLASS_LIGHT`,
and `OPEN_CLASS_HEAVY` constants when selecting the six seeding variants, and
preserve the raw labels in the category report. If a new external term raises
`ValueError`, save that category as `error` with the raw value instead of
silently dropping it or adding an audit-only translation table.

Before implementing the worker, save minimal sanitized HTML fixtures under
`app/tests/fixtures/bracket_audit/` for all of these cases:

- Regular weight division.
- Regular open class.
- Adult black belt weight and open class.
- Master black belt weight and open class.
- A category whose ranking table is absent.
- A category with one and multiple team swaps.
- A category with overlapping/chained team swaps.
- A bracket with byes and a play-in.
- A known `N=21` bracket.
- A localized or unexpectedly formatted table, if the live site exposes one.

For each fixture, record the source URL, capture date, expected headers, and why
the fixture is retained. Reduce fixtures to the relevant ranking, swap, and match
markup where practical so site boilerplate does not dominate the repository.

### Ranking Parser Contract

Return a structured result rather than `None`:

- Presence/status and raw normalized headers.
- A detected seeding variant.
- Rows containing official rank, name, team, and typed criterion values.
- Unknown headers and per-row validation errors.

Normalize known header aliases using the confirmed mapping above. Parse numeric
cells as integers, recent-title cells as year lists, optional-year cells as
integers or `None`, and flag cells as booleans. Preserve raw text beside typed
values for diagnostics. Header detection must be semantic, not based on fixed
column indexes alone. An unknown required column makes the table `unsupported`;
it must not shift later values into the wrong fields. A known variant that omits
a local sort field records it as `not_officially_exposed` rather than inventing
an official value.

### Identity Reconciliation Contract

The ranking table may not contain athlete IDs. Recover them conservatively:

1. Parse bracket-card competitors and their published displayed seeds.
2. Join ranking position directly to that displayed seed. Do not apply team
   swaps during identity reconciliation.
3. Verify normalized name and team; retain discrepancies instead of forcing the
   join.
4. Match official rows to registration prediction rows by local athlete ID when
   both resolve, then by unique normalized raw/known name plus team.
5. Never use fuzzy matching to make an authoritative audit join. Emit ambiguous
   candidates for review instead.

This is also how the audit can expose the otherwise-unavoidable upcoming-name
problem: the published bracket supplies an IBJJF ID that the registration page
did not.

## Prediction Snapshot

At run start, identify the `RegistrationLink` by the live tournament's
`event_id`. If there is no unique link, require an explicit admin selection and
record it.

For each category, reuse the same service path as
`registration_competitors()`:

1. Load the persisted registration rows for the division.
2. Resolve athlete identities and ratings.
3. Use `min(now, event_start_date)` as the seeding reference date.
4. Use `event_start_date` as the exclusive medal cutoff.
5. Run `add_seeding_data()`, `add_estimated_seeds()`, and `add_side_swaps()`.
6. Persist the complete compared criteria and source timestamps before marking
   that category complete.

Extract the route's calculation into a service rather than making an internal
HTTP request to the public API. The public endpoint and audit must share that
service so they cannot silently drift.

The report is not mutated after the worker exits. Running the audit again creates
a new run, whether the previous run was complete or had errors. This lets admins
distinguish “what the calculator said during this audit” from the result after
later medal or event-date corrections.

Use this notice in version one:

> This audit is an immutable recomputation created at {created_at} from the
> registration import saved at {registration_source_at}. Seeding was evaluated
> at {seeding_reference_date} with medals before {medal_cutoff}. It does not
> prove what the application displayed before bracket publication unless a
> contemporaneous prediction snapshot exists.

## Criteria Comparison Algorithm

For every reconciled competitor:

1. Select the exact ordered criterion list for the detected division variant.
2. Compare each official typed value to the corresponding predicted value.
3. Store every differing field, not only the final position.
4. Compare official ranking position with `est_seed` only after criteria.
5. If all real criteria are equal among a tied group and only ordering differs,
   classify it as `tie_order_only`; IBJJF's random tie-break is not a defect.
6. If rank differs because another competitor has different criteria, retain the
   underlying per-field mismatches so the report points toward missing medals,
   event-date/season errors, or weighting errors.
7. Treat missing registration rows, unresolved identities, unsupported headers,
   and missing tables as `unverifiable` rather than zero.

Apply category result precedence deterministically. A proven per-field
difference is `criteria_mismatch`; otherwise unresolved identity or parser
coverage is `identity_mismatch`/`unverifiable`; otherwise a rank-only difference
inside a group with identical real sort keys is `tie_order_only`; otherwise the
result is `match`. Keep mismatch and unresolved counts separately so the
category report does not hide either condition when both occur.

Include direct admin links to the local athlete, athlete medals, registration
source, live bracket, and relevant attempt task log. The report may calculate a
current medal breakdown on demand, but label it “current”; do not present it as
the saved audit snapshot unless it was actually persisted.

## Layout Comparison Algorithm

Layout auditing must use official seed numbers and must not depend on our point
calculation:

1. Parse every numbered match card and validate that `match_count + 1` is a
   power of two with a complete match-number range.
2. Compose published team swaps in document order, then map displayed seeds back
   to their original geometric slots. Validate that the result is a bijection;
   repeated seeds are valid input, but duplicate/missing output seeds are not.
3. Derive `N` from the unique real official seeds in the first-round slots and
   cross-check it against ranking rows and parsed competitors.
4. Compute `expected_slots, bracket_size = _bracket_slots(N)`.
5. Compare seed coverage and theoretical bracket size first.
6. Compare non-bye pairings while ignoring row order. A difference here is a
   `pairing_mismatch`.
7. If pairings match, the layout is `exact`; complete row order is intentionally
   ignored because the application canonicalizes display order.

Store enough structured evidence to paste a failing layout directly into the
workflow in `BRACKET_LAYOUT_REVERSE_ENGINEERING.md`. Never automatically rewrite
`_IBJJF_SEED_LAYOUTS` from one observed bracket.

## Fetching And Pacing

- Fetch the two category index pages, normalize and deduplicate category URLs,
  then process category pages sequentially.
- Route fetches through the existing `BracketPage` cache and use its existing
  request timeout. Reuse category HTML younger than ten minutes and record the
  cache timestamp.
- Sleep a fixed 500 ms between category fetch calls. Waiting on a cache hit is
  acceptable; avoiding cache-introspection and jitter code is more valuable for
  this private tool.
- Make one request attempt per page. On a category fetch or parse error, store
  the error and continue. If category-index discovery fails, mark the run
  `error` and stop.
- Do not fetch categories concurrently or add per-request recovery, refresh
  options, or resume machinery. An admin can start a new run later.
- Commit each category result after it is processed and log a short progress
  line. A run that reaches the end with category errors is `partial`.

## Background Execution

Add `scripts/audit_live_brackets.py --run-id <uuid>`. The script owns the simple
sequential loop and per-category commits. The admin POST route should:

1. Validate the tournament and registration source.
2. Create `BracketAuditRun` and `BackgroundTask(task_type="bracket_audit")` in
   one transaction.
3. Launch the script with `_run_logged_process()` in a daemon thread.
4. Redirect to the report page, which links to the generic task log.

Use the existing `BackgroundTask` process handling as-is. Do not add custom
signal handling, cancellation reconciliation, or run resumption. If a worker is
killed and leaves a stale run status, the task log remains the diagnostic and an
admin can start a new run.

## Admin Pages

Add:

- `GET /bracket_audits`: recent runs, tournament selector, launch form, status,
  progress, and summary counts.
- `POST /bracket_audits`: create and launch a run.
- `GET /bracket_audits/<run_id>`: durable report.

The report page should show:

- Provenance and an explicit snapshot-semantics notice.
- Current stored progress and a link to the existing task page. A normal page
  refresh is sufficient; do not build a separate polling API.
- Summary cards for clean, criteria mismatch, tie-only, layout mismatch,
  missing-table, unresolved, and error categories.
- One row per category with separate Criteria and Layout badges.
- Expandable competitor comparison rows with differing cells highlighted.
- Expected versus actual first-round slot evidence for layout differences.
- Links to the live bracket, registration view, task log, athlete, and medals.

Keep this server-rendered like the existing admin. Do not add this workflow to
the public React application.

Phase 0 review outcome: a server-rendered summary and category table are
sufficient. Competitor details can be rendered from the category JSON; no
client-side report application, attempt history, or advanced filter UI is
needed.

## Implementation Phases

### Phase 0 — Required Planning Iteration

- [x] Capture and review the complete fixture matrix.
- [x] Confirm whether the official table reflects pre-swap ranking positions in
  all sampled categories.
- [x] Confirm all six header mappings and champion cell encodings.
- [x] Decide the first-version snapshot wording and default throttle.
- [x] Review table schemas and report mockup before generating a migration.

### Phase 1 — Pure Parsers And Comparators

- [x] Extract common swap/first-round parsing.
- [x] Add ranking parser and typed criterion mapping.
- [x] Add reconciliation, criteria comparison, and layout comparison.
- [x] Cover all helpers with fixtures and table-driven unit tests.

### Phase 2 — Shared Prediction Service And Persistence

- [x] Extract registration prediction calculation from the route without changing
  its response.
- [x] Add models and Alembic migration.
- [x] Add straightforward run/category JSON serialization.

### Phase 3 — Worker And Admin UI

- [x] Add the CLI worker, fixed-delay cached fetch loop, and task launch path.
- [x] Add the list/report templates and evidence links.

### Phase 4 — Manual Verification

- Run one small tournament and manually verify every reported mismatch.
- Run a tournament containing a known team swap and `N=21` bracket.
- Fix only issues that prevent the report from being useful, then make it
  available to admins.

## Test Plan

- Pure HTML parser tests for every fixture variant and malformed/absent tables.
- Criteria mapping tests for all six `add_estimated_seeds()` variants.
- Reconciliation tests for direct ID matches, renamed athletes, team swaps,
  duplicate normalized names, and ambiguous joins.
- Tie tests proving random official order is non-actionable when criteria match.
- Layout tests for exact, display-only, pairing, seed-coverage, malformed match
  ranges, byes, team swaps, and `N=21`.
- Service tests proving the public registration API and audit snapshot use the
  same reference date, medal cutoff, and calculation.
- Database tests for run/category persistence, uniqueness, and partial results.
- Admin route tests for authentication, validation, task creation, and report
  rendering.
- Worker tests with mocked HTTP for cache use, fixed pacing, and continuing after
  one category-local failure.
- Run `make test` from the repository root. Do not run `make test-ocr`; this
  feature does not change OCR.
- Do not run the frontend build; the implementation is admin/server-rendered.

## Acceptance Criteria

- A 500-category tournament can be queued without tying up the request thread.
- Only one category page is requested at a time, with a fixed 500 ms pause
  between fetch calls.
- Refreshing or leaving the admin page does not lose completed report data.
- One bad/missing page produces a partial report rather than discarding the run.
- Official table absence is visible and never treated as zero points.
- Every actionable seed difference identifies its differing criterion or an
  explicit identity/reconciliation failure.
- Tie-only ordering is separated from true criteria differences.
- Team swaps are reversed before layout comparison.
- Layout results distinguish wrong pairings from correct pairings in a different
  visual order.
- Starting the audit again preserves the old result and produces a new snapshot;
  no in-place retry or resume path is required.

## Resolved Decisions For Version One

1. An immutable audit-time recomputation is sufficient. Prospective
   pre-publication snapshots remain a later enhancement, and the report uses the
   explicit notice above.
2. Reuse category HTML younger than ten minutes by default and record its cache
   timestamp.
3. Use a fixed 500 ms delay between category fetch calls, including cache hits.
4. Run layout auditing when the ranking table is absent; criteria are
   `unverifiable`.
5. Retain audit evidence until it is manually deleted. Version one has no
   retention job or cleanup UI.
6. Do not retry individual requests or resume runs. A later attempt creates a
   new `BracketAuditRun` and `BackgroundTask` and processes the tournament from
   the beginning.
7. Normal divisions read the persisted registration import. Because the
   existing importer intentionally does not persist open-class duplicates,
   open-class audit snapshots use the ten-minute cached registration page and
   record that source kind in category provenance.
