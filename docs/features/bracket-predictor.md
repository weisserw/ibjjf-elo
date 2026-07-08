# Bracket Predictor

## Purpose

Bracket Predictor lets users and admins preview registration-based brackets before an official bracket is available, and test how the bracket changes when a hypothetical athlete is added. It combines the registration scrape/import data, rating lookup, estimated seeding, same-team side-swap logic, and bracket-slot layout into the registration page UI.

## Main Entry Points

- Backend API routes: `app/routes/brackets.py`
  - `registration_competitors()` at `/api/brackets/registrations/competitors`
  - `registration_hypothetical_seed()` at `/api/brackets/registrations/hypothetical_seed`
  - registration parsing/helpers near `_registration_competitor_row()` and `_registration_rows_for_division()`
- Backend bracket/seeding logic: `app/seeding.py`
  - `_bracket_slots(n)`
  - `_side(seed, n)`
  - side-swap helpers used through `add_side_swaps()`
  - seeding helpers used through `add_seeding_data()` and `add_estimated_seeds()`
- Frontend registration page: `app/frontend/src/components/BracketRegistration.tsx`
- Frontend helper components/types:
  - `app/frontend/src/components/HypotheticalAthleteSearch.tsx`
  - `app/frontend/src/components/BracketUtils.ts`
  - `app/frontend/src/components/BracketTree.tsx`
  - `app/frontend/src/components/BracketTable.tsx`
- Focused tests:
  - `app/tests/test_brackets_hypothetical_seed_api.py`
  - `app/tests/test_seeding.py`

## Backend Flow

`/api/brackets/registrations/competitors` accepts `link`, `division`, and `gi`.

The route:

1. Loads registration rows with `_registration_rows_for_division(link, division, gi)`.
2. Looks up ratings with `get_ratings(...)`.
3. For juvenile divisions, skips seeding/side-swap calculations and returns rows plus bracket slots.
4. For other divisions, runs `add_seeding_data(...)`, `add_estimated_seeds(...)`, and `add_side_swaps(...)`.
5. Builds first-round slot layout with `_bracket_slots(len(rows))`.
6. Returns competitors, side swaps, bailout teams, `bracket_slots`, and `bracket_match_count`.

`/api/brackets/registrations/hypothetical_seed` accepts `link`, `division`, `gi`, and `athlete_slug`.

The route:

1. Rejects missing params with `400`.
2. Looks up the athlete by slug; missing athletes return `404`.
3. Loads the current registration rows and rating context.
4. Rejects athletes who are already registered by matching normalized athlete names against the row name and personal name, returning `409`.
5. Creates a temporary row with `_registration_competitor_row(...)`, fills known athlete identity/team fields, marks it with `hypothetical: true`, and appends it only to the in-memory `rows` list.
6. Reruns ratings, seeding, side swaps, and bracket slots against the temporary list.
7. Returns the same shape as `/competitors`, plus `hypothetical_athlete_id`.

The hypothetical route does not persist a registration row. `test_hypothetical_seed_returns_temporary_row_without_persisting` verifies that a later `/competitors` request still returns only the real registered athletes.

## Frontend Flow

`BracketRegistration.tsx` loads normal competitors with:

- `GET /api/brackets/registrations/competitors`
- params: `link`, `division`, `gi`

The component stores normal results in app context:

- `bracketRegistrationCompetitors`
- `bracketRegistrationSideSwaps`
- `bracketRegistrationSideSwapBailoutTeams`
- `bracketRegistrationSlots`
- `bracketRegistrationMatchCount`

`HypotheticalAthleteSearch.tsx` searches athletes through `GET /api/athletes`, then applies a hypothetical athlete with:

- `GET /api/brackets/registrations/hypothetical_seed`
- params: `link`, `division`, `gi`, `athlete_slug`

On success, `BracketRegistration` stores the response in local `hypotheticalRegistration` state:

- `competitors`
- `sideSwaps`
- `sideSwapBailoutTeams`
- `bracketSlots`
- `bracketMatchCount`

The UI reads through effective values, so a hypothetical response temporarily replaces the normal registration snapshot:

- `effectiveRegistrationCompetitors`
- `effectiveSideSwaps`
- `effectiveSideSwapBailoutTeams`
- `effectiveBracketSlots`
- `effectiveBracketMatchCount`

Changing the event, category, or reloading competitors clears `hypotheticalRegistration`.

## Data Items

`Competitor` is defined in `BracketUtils.ts`. Important fields for this feature:

- Identity/display: `id`, `ibjjf_id`, `slug`, `name`, `personal_name`, `team`, `instagram_profile`, `profile_image_url`, `country`, `country_note`, `country_note_pt`
- Division: `age`, `belt`, `weight`, `gender`, `gi`
- Rating: `rating`, `end_rating`, `match_count`, `end_match_count`, `rank`, `percentile`, `percentile_age`, `note`, `last_weight`
- Seeding: `seed`, `est_seed`, `est_seed_tied`, `points`, `open_class_points`, `grand_slam_points`, `grand_slam_open_class_points`, champion flags, and `ordinal`
- Hypothetical marker: `hypothetical?: boolean`

`CompetitorsResponse` is:

- `error?: string`
- `competitors?: Competitor[]`
- `side_swaps?: { name_a: string; name_b: string }[]`
- `side_swap_bailout_teams?: string[]`
- `bracket_slots?: [number, number | null][] | null`
- `bracket_match_count?: number | null`

`bracket_slots` comes from `_bracket_slots(n)` and is an ordered list of first-round `(red_seed, blue_seed)` pairs. `null` means a bye. `bracket_match_count` is `bracket_size - 1`.

The frontend turns backend slots into matches with `createMatchesFromSeeds(...)`. For the idealized comparison view, it builds a snake layout with `createSnakeBracketSlots(...)` instead of using IBJJF slots.

## Tests To Run

For backend/API changes:

```sh
make test
```

For a focused pass while editing this feature:

```sh
python -m unittest app.tests.test_brackets_hypothetical_seed_api
python -m unittest app.tests.test_seeding
```

Run the full `make test` before handing off changes that affect `app/routes/brackets.py`, `app/seeding.py`, or shared registration/seeding models.

Do not run `make test-ocr` unless OCR/livestream text scan code changed. Do not run the frontend build for routine changes; `npm run build` in `app/frontend` rewrites generated SEO snippets.

## Previously Surfaced Bugs And Issues

- Hypothetical rows must be temporary. The dedicated API test verifies the hypothetical athlete appears in that response but does not appear in a later normal competitor response.
- Already-registered athletes must be rejected. The route checks both registration row names and personal names to avoid adding duplicate athletes under alternate display names.
- Juvenile divisions intentionally skip estimated seeding and side-swap details, but still return bracket slots and match count.
- IBJJF bracket geometry and visual order have been fragile. See `docs/workflows/BRACKET_LAYOUT_REVERSE_ENGINEERING.md` before changing `_bracket_slots(n)` or `_side(seed, n)`.
- Known bracket layout regression areas include 5-, 6-, 7-, 9-, 11-, and 13-person play-in brackets, seed 1/2 visual side mapping, all-seeds-present checks, and same-team swap behavior.
- Same-team side swaps can create bailout teams when the algorithm cannot cleanly resolve conflicts. Preserve `side_swap_bailout_teams` in API and frontend state when changing this flow.

## Practical Editing Notes

- Treat `app/seeding.py` as the source of truth for bracket slot geometry. The frontend should consume backend-provided `bracket_slots` for estimated IBJJF layout.
- Keep `/competitors` and `/hypothetical_seed` response shapes aligned; the frontend swaps between them using the same `CompetitorsResponse` shape.
- If adding response fields, update `BracketUtils.ts` and both routes.
- If changing bracket slot geometry, add exact regression tests to `app/tests/test_seeding.py` using observed IBJJF rows.
- If changing hypothetical behavior, update or extend `app/tests/test_brackets_hypothetical_seed_api.py`.
