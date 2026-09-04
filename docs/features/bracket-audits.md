# Live Bracket Audits

## Purpose

The private admin audit compares a published BJJCompsystem bracket with an
immutable registration-based seeding recomputation. Criteria and first-round
geometry are reported independently so an identity or points problem cannot
hide a layout problem.

## Main Entry Points

- `admin/app.py`
  - `GET/POST /bracket_audits` lists runs and queues a new audit.
  - `GET /bracket_audits/<run_id>` renders the durable report.
  - `POST /bracket_audits/<run_id>/delete` deletes a report and its category
    evidence after its background task has stopped.
  - `_run_bracket_audit_task()` launches the worker under `BackgroundTask`.
- `scripts/audit_live_brackets.py` is the subprocess entry point.
- `app/bracket_audit_worker.py` discovers categories, checkpoints every result,
  and maintains run summary counts.
- `app/bracket_audit.py` contains the pure ranking, identity, swap, first-round,
  criteria, and layout helpers.
- `app/routes/brackets.py::build_registration_prediction()` is shared by the
  public registration API and the audit snapshot calculation.
- `BracketAuditRun` and `BracketAuditCategory` in `app/models.py` persist run
  provenance, summary fields, and category evidence JSON.

## Processing Rules

- The worker fetches male and female indexes, deduplicates category URLs, then
  processes pages sequentially with a 500 ms delay between page fetches.
- `BracketPage` content younger than ten minutes is reused. The saved cache
  timestamp and canonical category URL remain part of the report evidence.
- Unknown gender, belt, or weight vocabulary is a category error. Noneligible
  age labels are skipped. Missing or unsupported ranking tables make criteria
  unverifiable but do not prevent layout analysis.
- Only Adult and Master 1–7 weight divisions are eligible. Juvenile, teen,
  other age divisions, and all open-class weight variants are skipped during
  discovery before their category pages are fetched.
- Categories with fewer than four athletes are marked as skipped immediately
  after parsing the live competitor list. They are excluded from analysis,
  report rows, detail panels, and run progress totals.
- Official ranking rows join to bracket cards by the displayed seed before any
  team swaps are reversed. Registration rows then join by IBJJF athlete ID or a
  unique normalized name-and-team identity; fuzzy joins are never authoritative.
- Team swaps are composed in document order. This is required when a seed
  appears in more than one published swap.
- Live match HTML is parsed by `app/routes/brackets.py::parse_match()`, the same
  parser used by the public live bracket API. The audit consumes its normalized
  match numbers, seeds, and byes to evaluate first-round geometry.
- Layout status ignores display order and distinguishes matching non-bye
  pairings, changed pairings, incomplete seed coverage, and unverifiable markup.
  Expected and actual evidence pairs are normalized and sorted by seed so the
  two lists can be compared row by row.
- Each launch creates a new immutable run. Category failures are committed and
  produce a partial report rather than discarding completed results.
- Normal-weight divisions use persisted `RegistrationLinkCompetitor` rows.
  Open-class registrations are not stored by the existing importer, so those
  divisions use the ten-minute cached registration page and record
  `cached_registration_page` in their prediction provenance.

## Tests To Run

- Focused audit coverage:
  - `cd app/tests && python3 -m unittest test_bracket_audit test_bracket_audit_integration`
- Existing seeding and registration regressions:
  - `cd app/tests && python3 -m unittest test_seeding test_brackets_hypothetical_seed_api`
- Full non-OCR suite:
  - `make test`

The fixture matrix and source provenance are documented in
`app/tests/fixtures/bracket_audit/README.md`. Do not run `make test-ocr`; this
feature does not touch livestream OCR.

## Operational Notes

The report is a best-effort admin diagnostic. It has no resume, per-page retry,
or retention job. If discovery fails the run is `error`; if individual
categories fail the run is `partial`. A killed task may leave a stale run state,
so use the linked generic task log and start a fresh audit when needed. Reports
can be deleted from the audit list or detail page once the linked task is no
longer queued or running. Deleting a report also deletes its category evidence,
but preserves the generic task log. Report detail pages hide pending and fully
correct categories by default; the controls at the top reveal either group.
Fully correct means criteria status `match` or `tie_order_only` together with an
`exact` layout.
