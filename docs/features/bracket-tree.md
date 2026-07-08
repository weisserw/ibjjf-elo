# Bracket Tree

## User-Facing Behavior

The bracket tree renders matches as a horizontally-arranged tournament tree with
zoom controls. It is a shared subcomponent used by the three bracket-based views:

- live brackets in `app/frontend/src/components/BracketLive.tsx`
- registration/predicted brackets in `app/frontend/src/components/BracketRegistration.tsx`
- archive brackets in `app/frontend/src/components/BracketArchive.tsx`

Users can zoom the tree, scroll around the wide bracket, open match detail from
score controls when a stored match has detail data, follow external video links,
and use view-specific controls such as refresh or rating-vs-seed number toggles.
The same underlying match/competitor data also feeds `BracketTable`, but the tree
has different layout and tree-building code because matches need to be placed by
round and visual position instead of sorted into table rows.

## Main Code Paths

Frontend tree rendering:

- `app/frontend/src/components/BracketTree.tsx`
  - Defines `BracketTree` and internal `BracketTreeMatch`.
  - Chooses tree construction with `createTreeFromMatchNums` when the API has
    canonical/display match numbers, otherwise falls back to `createTreeFromTop`.
  - Owns zoom state, resize measurement, refresh button, number-mode toggle,
    match score rendering, video links, seed/swap highlighting, winner styling,
    and `MatchDetailModal` entry points.
- `app/frontend/src/components/BracketTree.css`
  - Owns tree geometry: horizontal levels, vertical spacing, match-card sizes,
    divider placement, zoom container overflow, score grid, and match action
    positioning.
- `app/frontend/src/components/BracketUtils.ts`
  - Defines the shared `Match`, `Competitor`, `CompetitorsResponse`,
    `LiveCompetitorsResponse`, and `SideSwap` types.
  - Builds tree levels with `createTreeFromMatchNums(...)` and
    `createTreeFromTop(...)`.
  - Builds predicted registration bracket matches from seed rows with
    `createMatchesFromSeeds(...)` and `createSnakeBracketSlots(...)`.

Frontend callers:

- `BracketLive.tsx`
  - Fetches live events/categories/matches.
  - Passes `hasMatchNums={true}`, enables refresh, and uses
    `matchCount={liveBracketMatchCount || matches.length}`.
- `BracketArchive.tsx`
  - Fetches historical categories/matches.
  - Passes `hasMatchNums` from the archive API response and uses the expected
    match count for the selected category.
- `BracketRegistration.tsx`
  - Builds `seededBracket` and `idealBracket` from registration competitors,
    bracket slots, side swaps, and hypothetical athlete state.
  - Passes seed highlight maps and disables calculate/refresh actions in the
    predicted tree views.

Backend data shaping:

- `app/routes/brackets.py`
  - Registration APIs are around `registration_categories()`,
    `registration_competitors()`, and `registration_hypothetical_seed()`.
  - Live APIs are around `/api/brackets/events`,
    `/api/brackets/categories/<tournament_id>`, and
    `/api/brackets/competitors`.
  - Archive APIs are around `/api/brackets/archive/categories` and
    `/api/brackets/archive/competitors`.
  - Bracket ordering helpers include `_canonical_position_from_seeds(...)`,
    `_position_from_display_match_num(...)`, and
    `add_canonical_display_match_numbers(...)`.
- `app/seeding.py`
  - `_bracket_slots(n)` returns canonical first-round seed pairs and bracket
    size; these feed both registration predicted brackets and backend
    display-match-number calculations.

## Frontend API Calls

`BracketTree` itself does not fetch bracket data. It receives `matches` and
view state from its parent. It can open `MatchDetailModal`, which uses the match
detail API documented in `docs/features/match-detail-view.md`.

Live bracket page:

- `GET /api/brackets/events`
- `GET /api/brackets/categories/<tournament_id>`
- `GET /api/brackets/competitors` with `link`, `age`, `gender`, `gi`, `belt`,
  and `weight`

Archive bracket page:

- `GET /api/events?search=...&historical=false` for event search suggestions
- `GET /api/awards/events/recent` for recent event choices
- `GET /api/brackets/archive/categories` with `event_name`
- `GET /api/brackets/archive/competitors` with `event_name`, `age`, `gender`,
  `belt`, `weight`, and `gi`

Registration bracket page:

- `GET /api/brackets/registrations/links`
- `GET /api/brackets/registrations/categories` with `link`
- `GET /api/brackets/registrations/competitors` with `link`, `division`, and
  `gi`
- `GET /api/brackets/registrations/hypothetical_seed` with `link`, `division`,
  `gi`, and `athlete_slug`
- `GET /api/brackets/registrations/elites`
- `GET /api/brackets/registrations/competitor_medal_breakdown` from the
  adjacent medal breakdown UI

## Key Data Items

`Match` is the tree's main rendering unit, defined in
`app/frontend/src/components/BracketUtils.ts`.

Important match-level fields:

- `id`: present for DB-backed live/archive matches; required to open match
  detail.
- `match_num`: original match number from the source data.
- `display_match_num`: optional canonical visual number from the backend.
  `createTreeFromMatchNums` uses it before falling back to `match_num`.
- `final`: marks the bracket root/final.
- `when`, `where`, `fight_num`, `video_link`,
  `video_start_offset_seconds`: scheduling and video metadata shown above each
  match card.
- `finalTopPoints`, `finalTopAdvantages`, `finalTopPenalties`,
  `finalBottomPoints`, `finalBottomAdvantages`, `finalBottomPenalties`,
  `finalMatchTimeSeconds`: final-score data for live/archive score display.

Each side of a match is represented by `red_*` and `blue_*` fields:

- athlete identity: `*_id`, `*_name`, `*_personal_name`,
  `*_instagram_profile`, `*_profile_image_url`
- bracket position: `*_seed`, `*_ordinal`, `*_bye`, `*_next_description`
- match result: `*_loser`, `*_note`, `*_medal`, `*ScoreboardPosition`
- rating display: `*_rating`, `*_handicap`, `*_expected`,
  `*_match_count`, `*_percentile`, `*_percentile_age`
- affiliation/country display: `*_team`, `*_country`, `*_country_note`,
  `*_country_note_pt`

`Competitor` rows power the table and predicted registration brackets. The
registration APIs add `bracket_slots` and `bracket_match_count`; the frontend
uses those with `createMatchesFromSeeds(...)` to synthesize `Match[]` for the
tree.

`SideSwap` rows are returned by registration seeding logic when same-team
conflicts cause visual bracket positions to be swapped. The registration page
turns these into `seedHighlights` and `seedSwapDescriptions`, and
`BracketTreeMatch` applies the highlight classes/tooltips.

## Tree Construction Rules

Use `createTreeFromMatchNums(matches, matchCount)` when the data has stable
match numbers. This is the path for live/archive trees and current predicted
registration trees. The function fills missing slots with empty matches so
later rounds still line up.

Use `createTreeFromTop(matches)` only when source match numbers are unavailable
or unreliable. It infers parent/child relationships from same seeds and
`red_next_description`/`blue_next_description`, inserts BYEs, and builds levels
from the final/root match downward.

Backend live/archive ordering is sensitive. If the source match numbers do not
match the canonical visual bracket, update `add_canonical_display_match_numbers`
or related helpers in `app/routes/brackets.py` rather than changing only the CSS
or React map order.

## Layout Notes

The tree is intentionally wider than the viewport. `BracketTree` measures the
scroll container, applies `transform: scale(...)`, and adjusts the scaled
container width so horizontal scrolling remains usable. The current slider range
is `0.2` to `0.9`, with icon buttons clamped between `0.2` and `1`.

Each rendered level uses a height based on the number of matches in the
corresponding four-level block:

```tsx
height: `${155 * leveledMatches[4 * Math.floor(levelIndex/4)].length}px`
```

That block sizing interacts with `.bracket-level`, `.bracket-tree-match-container`,
and `.bracket-tree-divider` in `BracketTree.css`. Layout fixes should be checked
on small and large brackets, because a change that works for 4- or 8-person
brackets may break 64- or 128-slot brackets.

## Tests To Run

From the repository root, run:

```bash
make test
```

Run the full Python test suite for backend data-shaping changes. For targeted
work, start with these tests:

- `app/tests/test_seeding.py` for `_bracket_slots(...)`,
  `add_canonical_display_match_numbers(...)`, side swaps, and visual ordering.
- `app/tests/test_brackets_archive_competitors_api.py` for archive match payloads,
  video links, and final score fields.
- `app/tests/test_brackets_live_match_scores.py` for attaching final score and
  scoreboard-position data to bracket matches.
- `app/tests/test_brackets_hypothetical_seed_api.py` for registration predicted
  brackets and hypothetical athlete seeding.
- `app/tests/test_brackets_archive_categories_api.py` and
  `app/tests/test_brackets_registration_links_api.py` when changing selectors,
  category loading, or event/link discovery.

For frontend-only layout changes, manually verify the live, archive, and
registration bracket views. The frontend package has lint/build scripts, but do
not run `npm run build` routinely because it rewrites generated SEO snippets.
OCR tests are not needed unless OCR/livestream text scan code changes.

## Bugs And Regression History

Git history shows several recurring risk areas:

- `23d08ff` on 2026-01-16, "allow scrolling past bracket tree":
  tree overflow/scroll behavior has broken before. Recheck scroll range after
  changing scaled wrapper dimensions or overflow CSS.
- `83ed8f1` on 2026-05-23, "fix side swaps to account for divergent bracket
  shapes": side-swap logic is coupled to bracket shape, not just seed numbers.
- `45d2e96` on 2026-05-24, "fix team swap display": highlight/tooltips can
  drift from backend swap data.
- `a148428` on 2026-06-17, "fix bracket reordering bug"; `10b9462`,
  `1205728`, and `2991d35` on 2026-06-26 all mention live bracket reordering
  or ordering fixes. These touched `app/routes/brackets.py` and
  `app/tests/test_seeding.py`, so ordering regressions should usually be fixed
  and tested in backend canonical display-number logic.
- `0bbb94a` on 2026-07-04, "show scores in archive and live brackets": score
  display spans frontend rendering, `BracketUtils` typing, backend payload
  fields, and archive API tests.
- `f34fe62` on 2026-01-02, "try to fix crash": this touched
  `app/routes/brackets.py`. The commit subject is vague, but it is another
  signal to keep route-level edge cases covered when changing bracket payloads.

When investigating a tree bug, first decide whether the failure is data order,
tree construction, or CSS layout. The fastest checks are:

- inspect the API payload for `match_num`, `display_match_num`, `final`, and
  side `*_next_description` fields
- confirm the parent view passes the expected `matchCount` and `hasMatchNums`
- compare the same category in `BracketTable`; if the table is correct but the
  tree is not, focus on `BracketUtils` or `BracketTree.css`
- run the targeted backend tests above before changing frontend layout to
  compensate for bad match positioning data
