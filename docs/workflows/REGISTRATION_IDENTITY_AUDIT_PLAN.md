# Upcoming Registration Identity Audit Plan

## Status

Planning document only. Do not begin implementation until candidate-scoring
calibration and the report review checkpoint below are complete.

This plan covers an admin-only, asynchronous report of registration names that
the existing Registrations view cannot resolve to a local athlete. It proposes
possible existing athletes using fuzzy name matching plus conservative
competition-history constraints.

The post-publication authoritative comparison is planned separately in
[`LIVE_BRACKET_SEEDING_AUDIT_PLAN.md`](LIVE_BRACKET_SEEDING_AUDIT_PLAN.md).

## Problem Boundary

Upcoming IBJJF registration pages contain names but no athlete IDs. When an
existing athlete registers under a new spelling or legal name, `get_ratings()`
may leave the row's local `id` empty. `add_seeding_data()` then correctly assigns
zero because there is no athlete identity from which to load medals, but the
prediction is misleading.

This feature is a review report, not an automatic identity merge. False merges
are more damaging than missed suggestions, especially for common names and
family members.

## Current Implementation Facts

- `RegistrationLink` stores tournament identity, source URL, update timestamp,
  and start/end dates.
- `RegistrationLinkCompetitor` stores raw athlete name, team, and division.
- `registration_competitors()` builds rows, then `get_ratings()` performs
  identity resolution.
- With no IBJJF ID, `get_ratings()` currently looks for exact
  `Athlete.normalized_name` equality. It rejects a candidate whose known highest
  belt is above the registration belt and rejects youth registrations for an
  athlete with adult/master history.
- `Athlete.personal_name` and `normalized_personal_name` exist, but the current
  registration exact-name query does not use the personal-name field.
- `scripts/medal_import_lib.py` already contains useful, tested matching pieces:
  `name_score()`, `first_and_last_match()`, `belt_rank()`, bulk belt bounds,
  known genders, known ages, and adaptive fuzzy thresholds. Application code
  should not import a script module; reusable pieces should move to an
  application module with the medal importer updated to use them.
- Gender and belt history can be hard constraints. Team and weight can change
  and should be evidence, not hard identity constraints.
- Existing admin background tasks can launch logged subprocesses and expose task
  state, but report data needs separate durable tables.

## Goals

- Let an admin choose a non-hidden upcoming registration and queue a scan.
- Optionally refresh and snapshot the registration source before analysis.
- Define “unknown” by the same resolver used by the Registrations view.
- Group duplicate occurrences without hiding conflicting division information.
- Produce a small, ranked candidate set for every unknown registration identity.
- Explain why each candidate was included and which constraints were applied.
- Preserve no-candidate and ambiguous results; do not show only apparent wins.
- Keep the report durable, filterable, and viewable after background completion.
- Build a review corpus that can later calibrate safe alias or mapping actions.

## Non-Goals For The First Version

- Automatically assign a registration row to an athlete.
- Automatically edit `Athlete.name`, `personal_name`, medals, or IBJJF IDs.
- Introduce a many-alias athlete model without separately reviewing how all
  identity consumers should use it.
- Promise that the first candidate is the same person.
- Use gender, team, academy, weight, or age as inferred demographic truth when
  the database has no evidence.
- Recalculate every predicted bracket inside this task. The report identifies
  likely identity gaps; a later audit/rerun shows the seeding effect after a
  correction.

## Proposed Persistence

Use `BackgroundTask(task_type="registration_identity_audit")` for execution and
logs.

Add `RegistrationIdentityAuditRun`:

- UUID primary key and nullable background-task foreign key.
- `registration_link_id`, tournament name, source URL, event start date, and
  source `updated_at` snapshot.
- Status/timestamps, refresh requested/completed flags, matcher version, and
  optional git/deployment revision.
- Total occurrence, distinct identity, already-resolved, unknown, candidate,
  no-candidate, ambiguous, and error counts.
- Fatal error text.

Add `RegistrationIdentityAuditEntry`:

- Run foreign key, raw and normalized registration name.
- Representative team and structured occurrence JSON containing every source
  division/team row used by the entry.
- Group key including normalized name plus compatible age/belt/gender context so
  two people with the same normalized name are not accidentally collapsed.
- Resolution status: `resolved_during_scan`, `candidates`, `no_candidates`,
  `ambiguous`, or `error`.
- Resolved local athlete ID when the shared exact resolver succeeds.
- Best/runner-up scores, score gap, candidate count, and error text.

Add `RegistrationIdentityAuditCandidate`:

- Entry and athlete foreign keys; unique on `(entry_id, athlete_id)`.
- Rank and confidence bucket.
- Score against canonical name, score against personal name, selected name
  score, first/last-token match, and team score when comparable.
- Known highest belt at the target date, known genders, relevant age-history
  summary, latest activity date, and matching alias/source.
- Structured evidence/reason JSON for display and future calibration.

Do not persist every rejected athlete. Store aggregate rejection counts by hard
constraint and only the top review candidates. Critical filter/sort values
should be normal columns; versionable evidence may be Text JSON.

## Shared Identity Resolver First

Before fuzzy matching, extract the exact registration identity logic from
`get_ratings()` into a route-independent service, tentatively
`app/athlete_identity.py`.

The service should:

- Resolve by IBJJF ID when present.
- Resolve exact normalized canonical names.
- Deliberately decide whether exact normalized personal names are aliases. The
  recommendation is yes, but duplicate aliases must yield `ambiguous`, not the
  first database row.
- Apply the same belt and youth/adult compatibility rules everywhere.
- Return a structured result (`matched`, `unmatched`, `ambiguous`, reason and
  candidates) instead of mutating response rows as its only interface.

Update `get_ratings()` to consume this service with regression tests before the
new scan uses it. This avoids a report claiming a name is unknown when the live
Registrations view would resolve it, or the inverse.

Move reusable pure fuzzy scoring and bulk history helpers out of
`scripts/medal_import_lib.py` into the same module or a small sibling module.
Update the medal importer to import the shared helpers without changing its
existing thresholds or behavior. Keep its current regression tests.

## Registration Snapshot And Grouping

At launch, default to refreshing the selected registration page once through a
shared registration-import service, then persist the source timestamp used. A
“use current persisted registration snapshot” option is useful for rerunning a
historical/debug case without network access.

Do not call a public HTTP endpoint inside the worker. Extract the parsing/save
path behind `import_registration_link()` so the route and worker share it.

After exact resolution:

1. Retain already-resolved counts for provenance but do not fuzzy-search them.
2. Group identical unknown occurrences by normalized name and compatible
   belt/gender/age context.
3. Preserve every original spelling, team, and division occurrence in the
   entry. If contexts conflict, split the group and show the conflict.
4. Use the tournament start date as the history reference date. Fall back to the
   scan time with an explicit warning if it is missing.

## Candidate Generation

Candidate generation should optimize for reviewable recall without doing an
`unknown_count × athlete_count` set of database queries.

### Candidate Pool

- Load athlete IDs plus canonical and personal normalized names in one bounded
  query/stream.
- Use RapidFuzz in process memory to select an initial top pool by the existing
  `name_score()` semantics (maximum token-sort score across canonical and
  personal names).
- Use token anchors or an indexed shortlist only after measuring recall. A hard
  first-and-last-token prefilter would miss real first/last-name changes and is
  therefore too strict for this report.
- Bulk-load belt, gender, age, latest activity, and recent team evidence for the
  union of shortlisted athlete IDs. Do not query history once per candidate.

### Hard Constraints

Reject a candidate only when evidence makes the match impossible or implausible
under the product rule:

- Gender: if the athlete has a known, consistent competition/medal gender and it
  conflicts with the registration division, reject. No known gender is
  unconstrained; conflicting historical genders should be flagged for review.
- Belt: belts do not go backward. If the highest known belt at or before the
  upcoming event is above the registration belt, reject. A lower known belt may
  progress to the registration belt and remains eligible.
- Age: reject Teen/Juvenile registration for an athlete already seen in
  Adult/Master before the target date. Keep Adult/Master transitions permissive
  unless a separately reviewed IBJJF age-progression model proves a hard
  contradiction.

Manual promotions must be included in belt evidence alongside matches, medals,
and ratings, with chronology respected. Unknown evidence must never be treated
as a contradiction.

### Soft Evidence And Ordering

- Primary signal: maximum canonical/personal `name_score()`.
- Explanatory signals: exact first and last tokens, matching token count,
  canonical versus personal-name source, team similarity, compatible belt
  progression, compatible age history, and recent competition activity.
- Weight and gi history may be shown as context but must not reject a candidate.
- Team mismatch must not reject a candidate; athletes change teams and source
  academy names vary.

Prefer transparent lexicographic ordering and confidence buckets over one
opaque “identity probability.” Every displayed candidate should show its name
score and evidence chips. Store the runner-up gap because a high score is less
convincing in a crowded namespace.

Start with a deliberately permissive display floor and at most five candidates
per entry. Final floor and High/Medium/Low bucket boundaries are not selected in
this document; choose them in the calibration checkpoint using labeled cases.
No confidence bucket authorizes an automatic change.

## Calibration Checkpoint

Before fixing thresholds:

1. Build a labeled set of known same-athlete renames and known different-person
   near matches from medal-import regressions and live bracket audits.
2. Include common Portuguese/Spanish names, reordered names, added/dropped middle
   names, suffixes, initials, accents, compound surnames, and actual first/last
   changes.
3. Measure candidate recall at top 1, top 3, and top 5 after hard constraints.
4. Inspect false candidates separately for common and rare namespaces.
5. Choose the display floor and confidence labels to favor no false certainty.
6. Record the labeled cases and chosen behavior in table-driven tests.

The live bracket audit should ideally ship first because official bracket-card
IBJJF IDs provide authoritative examples of registration names that changed.

## Background Execution

Add `scripts/audit_registration_identities.py --run-id <uuid>`. Even though it
does little network I/O, large registrations and fuzzy comparisons should not
run inside the request thread.

The admin launch route should:

1. Validate a non-hidden registration and its start date/status.
2. Prevent duplicate active runs for the same registration snapshot.
3. Create the run and `BackgroundTask` atomically.
4. Launch the CLI with `_run_logged_process()`.
5. Redirect to the report page.

The worker should checkpoint after registration refresh, after exact resolution,
and after bounded batches of unknown entries. It should be idempotent for the
same run: skip complete entries and replace incomplete candidate rows in one
transaction. Support cancellation and resumption using the same conventions as
the live bracket audit.

## Admin Pages

Add:

- `GET /registration_identity_audits`: upcoming registration selector, refresh
  option, recent runs, status, and counts.
- `POST /registration_identity_audits`: create and launch a run.
- `GET /registration_identity_audits/<run_id>`: report.
- `POST /registration_identity_audits/<run_id>/resume`: resume an incomplete
  run.

The report should include:

- Snapshot provenance and matcher version.
- Progress while running, using lightweight polling.
- Filters for confidence/status/belt/gender/age and name/team search.
- One entry per grouped unknown identity with all registration occurrences.
- Candidate rows showing names, profile link, name/personal-name score, score
  gap, team evidence, known belt/gender/age history, latest activity, and reasons.
- Explicit no-candidate, ambiguous, and rejected-by-constraint summaries.
- Links to the athlete edit page, athlete medals, public profile, registration
  bracket, generic task log, and later matching live-audit evidence.

Use server-rendered Flask/Bulma like the current admin. The first version must
not include an “Accept” button. Add that only after the alias data model and its
effects on every identity consumer are planned.

## Possible Follow-Up: Durable Athlete Aliases

A report alone can identify a likely rename but the current two-name athlete
model may not preserve a growing identity history cleanly. After observing the
report, separately evaluate an `AthleteAlias` table with source, normalized name,
validity/provenance, and audit trail.

That follow-up must define how aliases affect:

- Registration resolution and seeding.
- Medal import/backfill.
- Live bracket resolution.
- Search, athlete profiles, and duplicate-name ambiguity.
- Admin merge/edit behavior.

Do not overload `personal_name` or silently change canonical display names as an
unreviewed shortcut.

## Implementation Phases

### Phase 0 — Required Planning Iteration

- Review report wireframe and persistence schema.
- Decide refresh-by-default behavior.
- Extract and label rename/negative calibration cases.
- Approve candidate floor, result limit, evidence ordering, and confidence text.
- Decide exact personal-name alias semantics and duplicate handling.

### Phase 1 — Shared Resolver And Matcher

- Extract exact resolution from `get_ratings()`.
- Move reusable matcher/history helpers from the medal-import script.
- Add bulk chronology-aware history loading including manual promotions.
- Prove no regression in registration and medal-import tests.

### Phase 2 — Persistence And Analysis Service

- Add models and Alembic migration.
- Add registration snapshot/grouping service.
- Add candidate shortlisting, hard constraints, evidence ranking, and resumable
  checkpoints.

### Phase 3 — Worker And Admin Report

- Add CLI/background-task launch and cancellation/resume behavior.
- Add list/detail templates, filters, polling, and links.

### Phase 4 — Validation And Rollout

- Run against one small upcoming registration and manually label every result.
- Run against a large major registration; measure task time, query count, memory,
  candidate recall, and report render time.
- Compare later published live bracket IDs to the suggestions and feed confirmed
  positives/negatives back into the calibration fixtures.
- Only then consider alias-acceptance actions.

## Test Plan

- Exact resolver tests for IBJJF ID, canonical name, personal name, duplicate
  aliases, belt incompatibility, youth/adult incompatibility, and unknown rows.
- Matcher regression tests for accents, reordered names, middle-name changes,
  initials, suffixes, subset-name inflation, ties, common names, and first/last
  changes.
- Hard-constraint tests using event-time chronology, manual promotions, unknown
  evidence, and conflicting gender history.
- Tests proving lower-to-higher belt progression is allowed and higher-to-lower
  registration is rejected.
- Bulk query-count tests to prevent N+1 history loading.
- Grouping tests for duplicates and same normalized name with conflicting
  division contexts.
- Persistence tests for immutable snapshots, idempotent resume, partial errors,
  and reruns.
- Admin route tests for auth, upcoming/hidden validation, duplicate active runs,
  refresh options, task launch, filters, and report links.
- Worker tests for registration refresh failure, cancellation, resume, batching,
  and concise progress logs.
- Existing `test_medal_import_lib.py`, registration API tests, seeding tests, and
  the full `make test` suite must pass.
- Do not run `make test-ocr` or the frontend build for this admin-only feature.

## Acceptance Criteria

- Starting a scan returns immediately with a durable run and task record.
- The unknown set is exactly consistent with the shared Registrations resolver.
- Every unknown entry appears, including no-candidate and ambiguous cases.
- No candidate violating a known higher-belt or known gender contradiction is
  displayed.
- A plausible belt promotion remains eligible.
- Candidate computation uses bulk history loading rather than per-candidate
  queries.
- Candidate evidence is understandable without reading worker logs.
- No scan changes athlete identity or medals.
- Refreshing/leaving the report page does not lose results.
- A later run keeps the prior report and records a new source/matcher snapshot.

## Questions To Resolve Before Implementation

1. Should the worker refresh the registration page by default, or require an
   explicit refresh checkbox?
2. Should exact `personal_name` equality resolve automatically when unique? The
   recommendation is yes after duplicate-safe resolver tests.
3. What labeled cases and target top-5 recall are sufficient for the first
   calibration?
4. Should resolved rows be omitted entirely or retained as counts only? The
   recommendation is counts plus source provenance, not per-row report records.
5. How should same-name entries with different teams but identical division
   context be grouped?
6. How long should identity reports be retained?
7. Does the first useful release need a reviewed alias-acceptance workflow, or
   is report plus existing athlete/medal admin links sufficient?

