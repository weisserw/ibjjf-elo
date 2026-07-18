# Bracket Views

## User-Facing Behavior

The `Tournaments` navbar entry opens a three-tab bracket area:

- `/tournaments` renders live brackets from the IBJJF/BJJ Compsystem bracket site.
- `/tournaments/registrations` renders registration-based preview brackets from IBJJF registration pages.
- `/tournaments/archive` renders past-event brackets from the local match archive.

All three views share the same broad workflow: choose an event or registration
link, choose a division/category, fetch competitors and optional matches, then
render the list with `BracketTable` and, when enough structure exists, a visual
tree with `BracketTree`.

## Main Entry Points

- `app/frontend/src/App.tsx` maps the three URLs to `Brackets` with `tab="Live"`,
  `tab="Registrations"`, or `tab="Archive"`.
- `app/frontend/src/components/Navbar.tsx` links the main `Tournaments` nav item
  to `/tournaments`.
- `app/frontend/src/components/Brackets.tsx` owns the tab shell, explanatory
  copy, and tab-to-component dispatch.
- `app/frontend/src/components/BracketLive.tsx` owns the live bracket workflow.
- `app/frontend/src/components/BracketRegistration.tsx` owns the registration
  preview workflow, predicted/ideal bracket tabs, hypothetical athletes, and
  seeding controls.
- `app/frontend/src/components/BracketArchive.tsx` owns archived event search,
  recent-event selection, archived categories, and archived match display.
- `app/frontend/src/components/BracketTable.tsx` renders competitor rows,
  sorting, rating/seed columns, side-swap markers, and medal details.
- `app/frontend/src/components/BracketTree.tsx` renders match trees for live,
  archive, and registration-prediction data.
- `app/frontend/src/components/BracketUtils.ts` defines shared payload types,
  match-reference helpers, bracket seeding/tree helpers, and error handling.
- `app/frontend/src/components/Brackets.css` and
  `app/frontend/src/components/BracketTree.css` carry view and tree styling.
- `app/routes/brackets.py` contains all backend APIs for these views.

Related docs:

- `docs/features/bracket-tree.md` for tree rendering and match payload details.
- `docs/features/bracket-predictor.md` for registration seeding, side swaps, and
  hypothetical athlete behavior.
- `docs/workflows/BRACKET_LAYOUT_REVERSE_ENGINEERING.md` for IBJJF bracket layout
  reverse-engineering notes.
- `docs/workflows/LIVESTREAM_MATCH_LINKING_REGRESSIONS.md` for match-video
  linking regression work that affects live/archive bracket links.

## Frontend Flows

### Live

`BracketLive.tsx` loads events from `GET /api/brackets/events`, then categories
from `GET /api/brackets/categories/<tournament_id>`, then competitors and matches
from `GET /api/brackets/competitors`.

The live view is the closest representation of the external bracket site. The
backend parses bracket HTML into `Match` rows, attaches ratings, applies display
match numbers, and may attach final score/video data from the local archive. The
frontend renders `BracketTree` when `matches` are present and always renders the
competitor list through `BracketTable`.

Canonical live display numbers are derived from the tree positions encoded by
IBJJF `match_num` values. The backend reorders first-round subtrees by canonical
seed position and carries that permutation through every later round; winner
markers and prospective-match descriptions are not required for ordering.

### Registrations

`BracketRegistration.tsx` starts with `GET /api/brackets/registrations/links` for
upcoming registration pages. After a link is selected, it fetches divisions from
`GET /api/brackets/registrations/categories` and competitors from
`GET /api/brackets/registrations/competitors`.

This view has more local state than the other two. It persists selected
registration data, side swaps, bracket slots, bracket match count, and sort state
through `AppContext` local-storage keys such as `bracketRegistrationCompetitors`,
`bracketRegistrationSideSwaps`, `bracketRegistrationSlots`,
`bracketRegistrationMatchCount`, and `bracketRegistrationSortColumn`.

The registration page can also call:

- `GET /api/brackets/registrations/hypothetical_seed` to preview adding one
  athlete to a division.
- `GET /api/brackets/registrations/elites` for the elite athlete list.
- `GET /api/brackets/registrations/competitor_medal_breakdown` from table medal
  detail UI.

### Archive

`BracketArchive.tsx` uses archive events rather than external bracket pages. It
gets autosuggest data from `GET /api/events?search=...&historical=false`, recent
event choices from `GET /api/awards/events/recent`, division categories from
`GET /api/brackets/archive/categories`, and competitors/matches from
`GET /api/brackets/archive/competitors`.

Archive competitors and matches are DB-backed. The match payloads can include
match IDs, score summaries, video links, and offsets used by the match detail and
livestream-linking features.

## Backend Flow

All bracket view APIs live in `app/routes/brackets.py`.

Registration helpers:

- `parse_registrations(...)` handles IBJJF registration-page HTML.
- `import_registration_link(...)` fetches/caches external registration pages.
- `internal_registration_categories(...)` and
  `internal_registration_competitors(...)` handle `internal:` registration
  sources.
- `registration_links()`, `registration_categories()`,
  `registration_competitors()`, `registration_hypothetical_seed()`,
  `registration_competitor_medal_breakdown()`, and `registration_elites()` expose
  the registration API surface.

Live helpers:

- `get_bracket_page(...)` fetches/caches live bracket HTML in `BracketPage`.
- `parse_match(...)` converts source bracket match rows into frontend `Match`
  payload fields.
- `competitors()`, `categories(tournament_id)`, and `events()` expose the live
  API surface.

Archive helpers:

- `archive_categories()` derives available divisions from local match/event data.
- `archive_competitors()` returns archive competitors and matches for the selected
  event/category.

Shared backend logic:

- `format_division(...)` and `parse_division(...)` normalize division labels.
- `get_ratings(...)` attaches rating/ranking context and has special handling for
  live ratings, registration timing, open classes, juvenile divisions, and medals.
- Seeding/bracket-slot behavior is shared with `app/seeding.py`, especially
  `_bracket_slots(...)`.

## Frontend API Calls

Live:

- `GET /api/brackets/events`
- `GET /api/brackets/categories/<tournament_id>`
- `GET /api/brackets/competitors` with selected live category parameters.

Registrations:

- `GET /api/brackets/registrations/links`
- `GET /api/brackets/registrations/categories` with `link`
- `GET /api/brackets/registrations/competitors` with `link`, `division`, and
  `gi`
- `GET /api/brackets/registrations/hypothetical_seed` with `link`, `division`,
  `gi`, and `athlete_slug`
- `GET /api/brackets/registrations/elites`
- `GET /api/brackets/registrations/competitor_medal_breakdown` with `link`,
  `division`, `gi`, and `athlete_id`

Archive:

- `GET /api/events?search=...&historical=false`
- `GET /api/awards/events/recent`
- `GET /api/brackets/archive/categories` with `event_name`
- `GET /api/brackets/archive/competitors` with `event_name`, `age`, `belt`,
  `weight`, `gender`, and `gi`

## Key Data Items

Shared frontend types are in `BracketUtils.ts`.

- `Competitor`: table row data. Important fields include `ordinal`, `id`,
  `ibjjf_id`, `seed`, `name`, `slug`, `team`, `personal_name`, `country`,
  `rating`, `end_rating`, `match_count`, `rank`, `percentile`, `note`,
  `last_weight`, `next_where`, `next_when`, `medal`, `est_seed`,
  `est_seed_tied`, point-breakdown fields, world-champion flags, and
  `hypothetical`.
- `Match`: tree row data. Important fields include `id`, `match_num`,
  `display_match_num`, `final`, `when`, `where`, `fight_num`, `video_link`,
  `video_start_offset_seconds`, final score fields, red/blue competitor IDs,
  seeds, names, teams, ratings, expected values, byes, losers, notes, and
  next-description fields.
- `SideSwap`: registration-prediction swap marker shown in the table/tree.
- `CompetitorsResponse`: base response with `error`, `competitors`,
  `side_swaps`, `side_swap_bailout_teams`, `bracket_slots`, and
  `bracket_match_count`.
- `LiveCompetitorsResponse`: extends `CompetitorsResponse` with `matches` and
  `mat_links`.
- `Category` / `CategoriesResponse`: normalized division choices with `age`,
  `belt`, `weight`, `gender`, optional `link`, and optional `total`.
- `bracket_slots`: first-round seed pairings as `[seed, seed | null][]`; `null`
  means a bye.
- `bracket_match_count`: total matches implied by the bracket size; used by
  predicted registration trees.

The same concepts are represented differently by source:

- Live data starts as external bracket HTML and is normalized into `Match` and
  `Competitor` payloads.
- Registration data starts as external or internal registration rows and usually
  has competitors plus predicted slots, but not real completed matches.
- Archive data starts from local persisted match/event rows and can include DB
  match IDs, scores, video links, and event-derived categories.

## Tests To Run

For backend changes in this area, run the normal suite from the repo root:

```sh
make test
```

Focused tests worth knowing:

- `app/tests/test_brackets_registration_links_api.py` for registration link
  ordering/filtering, including pinned events.
- `app/tests/test_brackets_archive_categories_api.py` for archive category
  grouping and totals.
- `app/tests/test_brackets_archive_competitors_api.py` for archive competitor and
  match payloads.
- `app/tests/test_brackets_live_match_scores.py` for attaching final score/video
  data to live bracket matches.
- `app/tests/test_brackets_hypothetical_seed_api.py` for registration hypothetical
  athlete seeding.
- `app/tests/test_brackets_get_ratings.py` for rating/ranking behavior used by
  all three views.
- `app/tests/test_seeding.py` for `_bracket_slots(...)` and IBJJF bracket layout
  assumptions.

Do not run `make test-ocr` unless the change touches OCR or livestream text scan
behavior. Frontend builds are not routine verification for these docs; note that
`npm run build` in `app/frontend` rewrites generated SEO snippet files under
`app/seo_snippets/`.

## Previously Surfaced Bugs And Issues

Git history shows several recurring risk areas:

- Registration source changes: `98daca7` on 2026-07-06 added support for the new
  IBJJF registration page. Treat external registration HTML as unstable and keep
  parsing changes covered by API tests.
- Registration competitor totals come from `registration_link_competitors`, not
  directly from the latest registration-page HTML, and count distinct athlete
  names rather than rows. This keeps views consistent when the persisted import
  retains registrations from a division that later disappears, avoids counting
  athletes twice when they switch divisions, and excludes open-class duplicates
  because open classes are not persisted. Open-class categories remain available
  for bracket selection.
- Registration list ordering: `3270fc4` on 2026-07-03 pinned World Master to the
  top of the registration list. Be careful when changing `registration_links()`
  ordering or hidden/date filtering.
- Bracket ordering: `a148428` on 2026-06-17, `10b9462` on 2026-06-26,
  `1205728` on 2026-06-26, and `2991d35` on 2026-06-26 all fixed bracket
  reordering/order regressions. Changes to match ordering, `display_match_num`,
  first-round slots, or tree references need visual and test scrutiny.
- Predicted bracket shape and side swaps: `83ed8f1` on 2026-05-23 fixed side
  swaps for divergent bracket shapes; `45d2e96` on 2026-05-24 fixed team swap
  display. Registration changes should preserve `side_swaps`,
  `side_swap_bailout_teams`, `bracket_slots`, and `bracket_match_count`.
- Juvenile divisions: `255e873` on 2026-06-06 fixed combined juvenile age
  divisions. Avoid assuming age/weight parsing is adult-only.
- Athlete identity collisions: `adc3dfa` on 2026-05-19 fixed registration links
  pointing to the wrong athlete when two athletes of different belts shared a
  name. Prefer stable IDs/slugs when available; names alone are not enough.
- Six-person and irregular bracket shapes: `fa9747d` on 2026-06-23 fixed a
  6-man bracket shape. Cross-check unusual competitor counts against
  `docs/workflows/BRACKET_LAYOUT_REVERSE_ENGINEERING.md`.
- Live/archive scores and videos: `0bbb94a` on 2026-07-04 added scores to
  archive and live brackets; `840fef1` on 2026-07-05 fixed live links not using
  detected video offsets; `32c90cc`, `4f25948`, and `d3b15df` on 2026-07-05
  fixed match-linking problems. Preserve `id`, `video_link`,
  `video_start_offset_seconds`, scoreboard positions, and final score fields
  when changing match payloads.

## Practical Editing Notes

- Keep backend payload names aligned with `BracketUtils.ts`; these components do
  not use a generated API client.
- If a backend route can return `error`, the frontend usually surfaces it through
  `handleError(...)` or view-local error state.
- The views share table/tree components, but their source data is not equivalent:
  registration brackets are predicted, live brackets are parsed from external
  live pages, and archive brackets are DB-backed.
- When changing tree layout, ordering, or seeding, update or read
  `docs/features/bracket-tree.md`, `docs/features/bracket-predictor.md`, and
  `docs/workflows/BRACKET_LAYOUT_REVERSE_ENGINEERING.md`.
- When changing score/video links, check the livestream match-linking docs and
  tests because archive/live brackets expose those links directly.
