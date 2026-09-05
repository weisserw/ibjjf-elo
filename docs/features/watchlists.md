# Watchlists

## Public behavior

The Watchlists tab follows Archive at `/tournaments/watchlists`. The tournament
picker shows ongoing public IBJJF tournaments and upcoming tournaments starting
through the same date next calendar month (clamped to the last day of that month).
Tournaments that have ended are excluded. Users select up to
10 tournaments, then registered
athletes. A unified search matches official names, personal names, and registration
team names. Matching teams appear above athlete results with an "ADD ALL" button.
This adds trackable members of that exact team across all result pages for the
selected tournaments, deduplicates athletes, and stops at the 200-athlete limit.
Eligibility always
joins the official athlete name to the selected tournaments' registration rows.
Team search uses those registration teams, never match-history teams. Equal names
with different local UUIDs remain separate choices. Athletes without an IBJJF ID
are visible but cannot be tracked. Missing tournament dates are shown explicitly
and prevent selection. Tournaments without a start date are omitted from the picker.
Selection limits remain enforced without displaying counters. The editor starts
with helper text and no redundant page heading. The selected-athletes area shows
"None" when empty.
Expiry text is not displayed in the builder or saved page; expiry remains enforced.

Saving opens `/watchlists/:id` in the current tab after the create request succeeds.
The builder does not display a saved-watchlist link after saving. Bookmark
guidance appears only on the saved page as "Bookmark this page to quickly access your watchlist",
in an info-colored box with Edit this watchlist below it and no Copy link button. The
saved page is headed "Saved Watchlist" and has no separate tournament-freshness panel. Editing preloads the selection at
`/tournaments/watchlists?edit=:id`; changing it creates another ID and preserves
the original. Invalid selections remain visible for correction after failures.
Search keeps the previous results visible while a nonblank query is loading;
result actions stay disabled until the response arrives. Clearing the query still
hides results. The edit button has padding below it, followed by the update counter
and then the results.

Selections contain only sorted, distinct event IDs and athlete UUIDs. A fixed
application namespace and versioned canonical JSON produce a UUIDv5. Identical
submissions reuse the same mapping; canonical payloads are compared on conflict.
Names, ratings, divisions and schedules are never frozen in the selection.

Each selected athlete has exactly one card, showing their earliest listed next
match across all selected events and divisions, including open class. Both
watched sides of a match retain their own cards. Published dates and clock times
are preserved as calendar strings without timezone conversion. Timed matches
sort first; listed matches with unknown time show **Time pending**. A browser
supplies its current local calendar date when reducing cached schedules.

Card headings combine athlete and opponent names, parenthesized division-based
ratings (including open-class adjustments), and win percentages.
The heading breaks after "vs" for named opponents; "vs TBD" stays on the same line.
Provisional and semi-provisional ratings use normal text with the existing colored provisional dot
inside the parentheses, without gray styling on the rating text.
Cards are grouped by calendar date under a weekday heading, with unscheduled cards
after the dated groups. Times use compact am/pm (for example, `9:30am`), without a
numeric date or timezone conversion. Time and mat appear together on the left,
separated by a dot, in the same font size as the athlete heading. Cards show mat
and division, with the tournament name at the bottom. Division links select the
event and category in app context and open `/tournaments`, matching the athlete
profile registration table's live-bracket navigation. The API supplies canonical
`bracket_category` text in belt/age/gender/weight order even when source schedule
text is in age/gender/belt/weight order. Navigation clears previously loaded bracket
data so another tournament's bracket cannot remain visible during loading.
Profile links open separately. Exact IBJJF IDs resolve live identities; similarly
named local people are not substituted. Actual unknown opponents receive default
ratings and zero matches. Winner-of-fight placeholders retain their descriptions
and do not get invented identities or predictions. Placeholder opponents display
"TBD" while their underlying descriptions remain unchanged. Kids divisions below
Teen 1 are excluded from registration eligibility, team search/bulk-add, and
displayed schedule cards. When a selected tournament's normalized name contains
`kids`, `criancas`, or `15 anos`, the builder shows the same warning used by the
registration bracket view; the saved page does not show this notice. Teen 1–3 competitors remain selectable and retain
schedule information and bracket links without ratings or win probabilities.

Gray **Not on current schedule** cards require reliable complete coverage. This
means absence from the source, not verified elimination or completion. Future
schedules and unavailable sources get explicit statuses. A known next match
remains visible when another tournament fails, without adding a warning to the
cached match. Delayed cards are retained
until the source removes them; card colors do not establish match completion.

## Implementation

- `app/watchlist_schedule.py`: pure HTML discovery, strict URL validation, dates,
  mat/fight parsing, pagination, coverage checks and one topology retry. Only mat
  cards establish presence; search widgets are ignored.
- `app/watchlist_refresh.py`: database leases, two global slots, bounded worker
  admission, two concurrent page fetches per tournament, shared homepage discovery,
  atomic publication, backoff and ownership checks.
- `app/watchlists.py`: canonical selection, scoped search, validation, expiry,
  row reduction and shared rating adapters.
- `app/routes/watchlists.py`: public APIs, returning promptly without upstream IO.
- `app/models.py` and migration `9d3f5a7b1c20`: selections, shared snapshots,
  refresh slots, registration readiness marker and eligibility-join indexes.
- `app/frontend/src/components/WatchlistEditor.tsx`, `WatchlistView.tsx`,
  `WatchlistShared.ts`, `WatchlistParts.tsx`, `Watchlists.css`: mobile editor/view,
  typed API handling, polling, cards and shared provisional rendering.
- `app/routes/brackets.py`: `get_ratings(..., strict_ids=True)` retains existing
  callers' default identity policy. `save_competitors` records successful imports,
  including empty ones. Watchlists reuse parsing/persistence for background
  registration imports and never write live ratings from schedule cards.

`WatchlistSchedule` contains normalized snapshots, coverage, source timestamps,
snapshot versions, discovery metadata and refresh/backoff fields. A null snapshot
means no successful generation; an empty list is a successful empty generation.
The reserved `__discovery__` row caches homepage links for five minutes with its
own lease. `registration:<event_id>` rows coordinate registration imports through
the same global slots. No raw HTML is persisted in these caches.

Claims update a free slot before the event lease and roll back both if either
cannot be acquired. Publication, renewal and release require the current owner
token and an unexpired lease. Claims use database time; HTTP connections use
5-second connect and 20-second read timeouts. Refresh work has a monotonic
10-minute deadline and 90-second leases, renewed while work progresses. Page
workers have separate app contexts/sessions and release database connections
before waiting on HTTP. At most two pages per tournament are in flight, for a
global maximum of four. Admission does not create an unbounded work queue. Each
background HTTP fetch logs its start and its completed status, byte count and
duration to the application console; failures log their status and error code.

The scanner rediscovers days and pages on each refresh. It seeds four-mat page
groups, follows remaining pagination and checks advertised mat coverage. Missing
or duplicate mats and changed topology prevent publication. Failed generations
retain the last successful snapshot. A one-calendar-day scan margin accommodates
viewers whose local date is behind the server; reduction excludes their past days.

Successful schedules have a 180-second TTL. Failure backoff starts at 30 seconds,
doubles up to five minutes, adds jitter and honors a longer Retry-After. The view
always polls every 180 seconds, including during initial population and after
errors. Polling pauses while hidden and checks overdue data on return.
Below the edit button, the page shows "Updates in m:ss...", counting down to the actual next
request, and "Refreshing…" while the request runs. Loaded watchlists keep a
180-second polling interval even during a scan or near the next refresh deadline.
Worker failure backoff does not alter the browser interval. A successful, complete snapshot remains usable while a refresh lease
is active, including scans taking more than a minute. Reaching the cache TTL
alone does not invalidate coverage during an active refresh. Errors preserve the
last successful cards and scroll without adding an incompleteness warning. Until
any selected tournament has a successful snapshot, the view suppresses cards and
shows the population-in-progress message. Source freshness remains in the API.

Configuration: `WATCHLIST_MAX_TOURNAMENTS` (10), `WATCHLIST_MAX_ATHLETES` (200),
`WATCHLIST_MAX_SAVED` (10,000 persisted watchlists),
`WATCHLIST_REFRESH_ENABLED` (true; false disables worker startup in tests).
The create endpoint checks the saved-watchlist count against the global cap before
inserting, without locking. Simultaneous creates may slightly exceed the limit;
this is acceptable for this capacity guard. Existing identical selections can be
reopened at capacity. New selections receive `503 watchlist_capacity_reached`
with a user-facing message. Expired rows count until deleted by a read or purge.

## API

- `GET /api/watchlists/tournaments`: deduplicated structured event choices,
  registration availability and missing-date explanations.
- `GET /api/watchlists/athletes?event_id=...&q=...&mode=all|name|team|team_exact&cursor=...`:
  30 distinct athletes per page, ordered by display name and UUID. Repeated
  `selected_id` parameters return eligible selected IDs for editor validation.
  Queries bind parameters and escape literal wildcard input. Missing local imports
  are initiated in background, not synchronously on a keystroke.
  Empty or whitespace-only searches return no athletes or pagination cursor;
  selected-athlete eligibility validation still runs so clearing the search does
  not invalidate the selection. The editor hides results immediately on clearing.
  The default `all` mode returns matching team names alongside the combined athlete
  results. `team_exact` paginates trackable members for the bulk-add action.
- `POST /api/watchlists`: `event_ids` and `athlete_ids`; validates current
  registration eligibility and live IDs and returns `id`, `url`, `expires_at`.
- `GET /api/watchlists/:id`: current selection and athlete/event summaries.
- `GET /api/watchlists/:id/data?local_date=YYYY-MM-DD`: rows, source freshness,
  coverage, refresh state and `poll_after_seconds`. May claim background work.

Populating, stale and partial states use HTTP 200. Invalid requests are 400;
missing IDs are 404; accessing an expired existing mapping deletes it and returns
410. Subsequent access returns 404 with the same unavailable/expired UI.
Saved reads do not revalidate registration membership. Authoritative event date
changes reconcile expiry without changing the selection UUID.

## Expiration and operation

Expiry is the latest selected event end date plus two days. Reads enforce it
before triggering refresh. `flask --app app/app.py purge-expired-watchlists`
reconciles event dates, purges expired mappings and removes orphaned source caches
without deleting live leases. Register this command daily through the hosting
scheduler; no hosting scheduler configuration is present in this repository.

Apply the Alembic migration before serving the new routes. Production workers must
permit background threads to continue after responses. Worker recycling is
recoverable through lease expiry and atomic snapshots, but deployed worker
arguments/lifetime must be checked in the hosting environment.

## Verification

Run `make test` from the root in the repository Python environment. No OCR tests
or SEO-generating frontend build are needed. Focused tests:

- `app/tests/test_watchlists.py`: source parsing, anonymized source-shaped fixture,
  identity/search, canonical saves, expiry, ratings, reduction, coverage states,
  lease renewal/loss, timeout retention and failed thread startup.
- `app/tests/test_watchlist_postgres.py`: opt-in independent-process contention,
  global capacity, stale publication and migration upgrade/downgrade. Set
  `WATCHLIST_TEST_POSTGRES_URL` to a disposable PostgreSQL database. Tests use and
  remove their own uniquely named schemas.
- `app/frontend/scripts/watchlist-smoke.mjs`: browser tests against Vite using
  synthetic API responses. Covers narrow widths, reduced viewport, search races,
  popups, editing, source-error retention, scroll and visibility polling. Install
  Playwright separately and set `WATCHLIST_PLAYWRIGHT` to its module URL and
  optionally `WATCHLIST_CHROMIUM` to a browser executable.
- `dev/watchlist_query_plan.py`: opt-in synthetic PostgreSQL query-plan probe;
  takes an output filename and the same disposable-database environment variable.

All fixture athlete names, teams and competitor IDs must be synthetic. Anonymize
source fragments before adding them; remove tracking links and raw downloads.
See [release checks](../workflows/WATCHLIST_RELEASE_CHECKS.md) for measured results
and deployment-only verification.
