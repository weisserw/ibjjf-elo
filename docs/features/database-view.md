# Database View

Also called the database tab or database results table. This is an end-user
match results view; it is not the internal database that powers the app.

## User-Facing Behavior

The Database view is a top-level UI tab at `/database`. It shows paginated match
results for the active Gi/No-Gi tab and lets users filter those matches by
athlete, team, country, event, division, date, mat, DQ type, score/result,
rating range, and elite status. Score controls live in their own filter
accordion rather than under Tournament. The technical and disciplinary DQ
controls appear below the other Score filters.

Rows link out to related paths and components:

- athlete names navigate to `/athlete/<slug>`
- event names set an exact event filter in the Database view
- division labels set age/gender/belt/weight filters
- bracket buttons open `/tournaments/archive` with the row's event/category
- video icons open a direct match/livestream video URL
- score/detail controls open `MatchDetailModal` on desktop and inline
  `MatchDetailView` on mobile cards

Wide screens render a table. Touch/mobile screens render card rows. The two
layouts share the same `DBRow` data but have separate markup in
`DBTableRows.tsx`.

## Main Code Paths

Frontend:

- `app/frontend/src/App.tsx`
  - Routes `/database` to `Database`.
- `app/frontend/src/components/Database.tsx`
  - Owns the top-level Database tab container and renders `DBTable`.
- `app/frontend/src/components/DBTable.tsx`
  - Fetches `GET /api/matches`.
  - Reads `activeTab`, `filters`, `openFilters`, and `dbPage` from
    `useAppContext`.
  - Owns loading/reloading state and API result state.
  - Handles pagination clicks.
  - Handles row-link callbacks for athlete, event, division, and archive
    bracket navigation.
- `app/frontend/src/components/DBFilters.tsx`
  - Defines `FilterValues`, `FilterKeys`, and filter control behavior.
  - Debounces text/rating filters before updating app context.
  - Calls athlete and event suggestion APIs.
- `app/frontend/src/components/DBTableRows.tsx`
  - Renders desktop table rows and mobile card rows.
  - Renders athlete/name metadata, ratings, score columns, submission value,
    event/division links, bracket buttons, notes, video links, and match-detail
    controls.
  - Decides when score columns/details are visible from final score fields.
- `app/frontend/src/components/DBTable.css`
  - Styles shared Database table/card controls, row affordances, and responsive
    details.
- `app/frontend/src/components/DBPagination.tsx`
  - Renders pager controls used by `DBTable`.
- `app/frontend/src/components/MatchDetailView.tsx`
  - Used when a row opens score details.
- `app/frontend/src/utils.ts`
  - Defines `DBRow` and `DBResults`.

Backend:

- `app/routes/matches.py`
  - `matches()` handles `GET /api/matches`.
  - Builds SQL filters from query params.
  - Converts joined match/participant rows into one response row per match.
  - Adds S3-backed athlete photo URLs when present.
  - Rewrites `videoLink` through mat-aware livestream lookup and visible
    OCR/archive associations before returning.
  - `match_detail_events(match_id)` handles
    `GET /api/matches/<match_id>/detail-events` for row score details.
- `app/livestream_match_linking.py`
  - Upstream source of persisted video offsets, final scores, final match time,
    and linked OCR rows that Database row videos/details depend on.

## Frontend APIs

Primary results API:

```text
GET /api/matches
```

`DBTable` calls it directly with Axios:

```ts
axios.get<DBResults>('/api/matches', {
  params: {
    gi: gi ? 'true' : 'false',
    ...filters,
    page
  }
})
```

Important query params accepted by `matches()`:

- `gi` is mandatory and is parsed as a boolean string.
- Identity/search filters: `athlete_id`, `athlete_name`, `athlete_name2`,
  `team_name`, `country`, `event_name`.
- Division filters: `gender_male`, `gender_female`, `age_adult`,
  `age_master1` through `age_master7`, `age_juvenile`, `age_teen`,
  `belt_grey`, `belt_yellow`, `belt_orange`, `belt_green`, `belt_white`,
  `belt_blue`, `belt_purple`, `belt_brown`, `belt_black`,
  `weight_rooster`, `weight_light_feather`, `weight_feather`, `weight_light`,
  `weight_middle`, `weight_medium_heavy`, `weight_heavy`,
  `weight_super_heavy`, `weight_ultra_heavy`, `weight_open_class`.
- Other filters: `date_start`, `date_end`, `mat_number`,
  `dq_type_technical`, `dq_type_disciplinary`, `has_score`, `submission`,
  `comeback_submission`, `minimum_points`, `minimum_advantages`,
  `minimum_penalties`, `score_differential`, `referee_decision`,
  `rating_start`, `rating_end`, `elite_only`, `page`.

Supporting frontend calls:

- `DBFilters` calls `GET /api/athletes?...&search=<value>` for athlete
  suggestions. Watch the backend spelling if editing this path:
  `athletes.py` reads `allow_teen`, while the current component sends
  `allowteen=true`.
- `DBFilters` calls `GET /api/events?search=<value>&gi=<boolean>` for event
  suggestions.
- Opening row score details calls
  `GET /api/matches/<match_id>/detail-events` from `MatchDetailView`.

## Response Shape

The Database results API returns:

```ts
interface DBResults {
  rows: DBRow[];
  totalPages: number;
}
```

`DBRow` is defined in `app/frontend/src/utils.ts`. Important field groups:

- Match identity/navigation: `id`, `event`, `date`, `matchLocation`,
  `videoLink`.
- Division: `age`, `gender`, `belt`, `weight`.
- Winner/loser identity: `winner`, `winnerSlug`, `winnerId`,
  `winnerPersonalName`, `loser`, `loserSlug`, `loserId`,
  `loserPersonalName`.
- Athlete metadata: country fields, Instagram profile, and profile image URL
  for each side.
- Ratings: start/end ratings, match counts, and rating notes for each side.
- Result/details: `rated`, `notes`, final top/bottom points, advantages, and
  penalties, `submission`, and winner/loser scoreboard positions.
- Open-class display helpers: `winnerWeightForOpen` and
  `loserWeightForOpen`.

Backend response construction in `matches()` still carries temporary internal
keys such as event IBJJF id, match number, division size, and video start
offset while filling livestream links. Those are deleted before JSON is
returned.

## Data Semantics

- One API row represents one match, but the SQL query reads two participant
  rows. `matches()` groups adjacent participant rows by `m.id`.
- Winner/loser order comes from `MatchParticipant.winner`. If neither
  participant is marked as winner, the first participant is treated as winner
  and the second as loser for display.
- Exact athlete/team/event searches use surrounding quotes in the filter value.
  Non-exact athlete search uses Postgres full-text search when `DATABASE_URL`
  is set and SQLite `LIKE` fallback otherwise.
- Athlete names respect `hide_full_name` by searching/displaying normalized
  personal names where required.
- `age_juvenile` expands to the combined juvenile age list, while `age_teen`
  expands to teen age constants. `DBTable.divisionClicked` also maps concrete
  `Teen *` and `Juvenile *` row ages back to their combined filter keys.
- `weight_open_class` includes Open Class, Open Class Light, and Open Class
  Heavy. `DBFilters.weightToFilter` maps the split open classes back to the
  shared filter.
- DQ filters inspect participant notes and distinguish technical and
  disciplinary DQ note text.
- `has_score` includes matches with at least one non-null final score field.
- `submission` includes matches with a positive `final_match_time_seconds` and
  excludes DQ notes, matching the visible Sub column.
- `comeback_submission` applies the submission rules and also requires the
  winner's scoreboard position to be known and the winner to have strictly
  fewer final points than the loser.
- `minimum_points`, `minimum_advantages`, and `minimum_penalties` are
  non-negative inclusive thresholds. A match qualifies when either scoreboard
  side has at least the requested value.
- `score_differential` is a non-negative minimum absolute difference between
  the two final point totals. Both point totals must therefore be known.
- `referee_decision` requires `final_match_time_seconds = 0`, equal known
  points, advantages, and penalties on both sides, and no DQ note.
- Score filters are combined with each other and all other filters using AND.
- `submission` is derived from `final_match_time_seconds`: `null` means the
  value is unknown, positive values render as submission, zero renders as not a
  submission. DQ notes suppress the visible submission checkbox/value.
- Score/detail affordances are shown only when final score fields exist.
- Historical events are detected client-side with `isHistorical` and get
  historical styling/warnings. Bracket links are suppressed for historical
  events.
- Video links prefer a segment-visible OCR-linked YouTube archive, including the
  stored match video offset. Visibility is resolved from the linked upload,
  event day/time, mat when known, and source-video offset, so a hidden range of
  an otherwise visible upload suppresses both controls for mat-aware and
  mat-less tournaments. Ambiguous mixed-visibility associations fail closed.
  Otherwise rows use ordinary mat-aware livestream resolution and fall back to
  the match's stored `video_link`.
- The case-insensitive `NONE` sentinel still suppresses every video source.
- The homepage's cached YouTube-covered match count uses the same ordinary and
  OCR/archive resolvers and also excludes no-match notes that suppress Database
  video icons. See `docs/features/homepage-video-count.md`.

## Tests To Run

For backend API/filter/response changes:

```bash
(cd app/tests && python3 -m unittest test_matches_api)
make test
```

For changes touching row score details, final score fields, video offsets, or
`MatchDetailView` integration:

```bash
(cd app/tests && python3 -m unittest test_match_detail_events)
make test
```

For upstream livestream matching/link selection changes that affect Database
row video links or final score fields:

```bash
(cd app/tests && python3 -m unittest test_livestream_match_linking)
make test
```

Run `make test` from the repository root. Dependencies may come from the local
pyenv, so use the same shell environment that normally runs project tests.

Do not run `make test-ocr` unless OCR/livestream text scan behavior changes.
Do not run the frontend build as routine verification; `npm run build` in
`app/frontend` rewrites generated SEO snippet files.

Focused coverage exists in `app/tests/test_matches_api.py` for athlete/team/
country/event/rating/elite/DQ/juvenile/score filters and mandatory/invalid
params.
There is no obvious dedicated frontend unit test for `DBTableRows` responsive
rendering, so manually inspect desktop and mobile layouts when changing row
markup or CSS.

## Previously Surfaced Issues From Git History

- `231fe63 fix paging in database ui`
  - Pagination behavior has regressed before. Recheck page reset, next/previous
    bounds, empty result handling, and `totalPages` when touching paging.
- `f90b717 fix slow query`
  - The match search query can become expensive. Be careful with new filters,
    joins, `EXISTS` clauses, and sort changes.
- `2f48cdc fix postgres date handling`, `e0854ed fix another postgres error`,
  `26e884e fix error`
  - SQLite/Postgres differences have broken this route before. Preserve typed
    date parsing and UUID handling across both local tests and production DB.
- `e4b263a fix next going back to first page when rows is multiple of 12` and
  `4e64d48 fix page not resetting`
  - Page-size and extra-row pagination logic is easy to get subtly wrong.
- `2722c62 fix table being empty while loading`
  - Loading/reloading state affects whether rows, empty state, and pagination
    appear.
- `ba6a184 check for invalid page and change header`
  - The API validates page values and returns `400` for invalid pages.
- `57b89af fix db links`, `16aa0e3 link to athlete pages`, `ef79856 use
  athlete ID for profile page matches`
  - Row links have changed repeatedly. Check athlete slug/id behavior and
    `eventClicked`/`divisionClicked` side effects when editing links.
- `ce724b5 fix age filter not selecting when clicking on juvenile or teen
  division`, `f5f7b0c combine juvenile age divisions`, `255e873 fix combined
  juvenile age divisions`
  - Juvenile/teen filter mapping is a known edge case across frontend and API.
- `08b913d fix database card padding / overflow / alignment`, `49b6c36 fix db
  card y overflow`, `22fd4fa fix header layout`, `0f4a421 fix icon location`
  - Responsive row/card layout has had visual regressions. Check both desktop
    table and mobile card versions after CSS or markup changes.
- `4231d91 dont leak info from search`, `15a0654 add ability to hide athlete
  name`, `12dfb60 use personal name everywhere by default`
  - Name search/display must respect hidden full names and personal-name
    behavior.
- `0655871 Add separate DQ filters for disciplinary vs technical (#25)`,
  `3996c66 don't set submission flag for DQs`, `d6d7bfc fix submission labels`
  - DQ note semantics affect both filtering and visible result/submission text.
- `8e69232 show match videos in database`, `51d6439 add time editors and direct
  video links`, `44ca8f2 prefer livestream videos over single-match videos
  where we have scoreboard info`
  - Video links depend on both stored match links and livestream-derived
    offsets. Test rows with and without linked livestream data.
- `0f822c5 add match linking prototype`, `892514b better match linking`,
  `da7d7b2 fix linked field display`
  - Match linking fields feed the row video/detail experience and have had
    display bugs.
- `0a276cb match detail view first pass`, `a74bc3a match detail improvements`,
  `a0164b2 fix score cancellations leaving a +1 score event`
  - Database rows now expose match details. Score correction bugs usually belong
    in `matches.py` detail-event helpers and `test_match_detail_events.py`.
