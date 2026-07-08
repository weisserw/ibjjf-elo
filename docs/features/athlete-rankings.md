# Athlete Rankings

## User-Facing Behavior

Athlete rankings show the current standing for a gender/age/belt/gi/weight
division. The rankings are generated from recent match history and stored in
`athlete_ratings`; division averages are stored in `athlete_rating_averages`.

The main ranking table is `EloTable.tsx`. The same data also appears in athlete
profiles, bracket registration rows, live/archive bracket competitor rows, and
batch athlete lookups used by integrations.

## Main Code Paths

- `app/ratings.py` is the recomputation entry point. It recalculates match
  participant Elo values through `elo.compute_ratings`, then calls
  `current.generate_current_ratings`.
- `app/current.py` builds and persists the ranking boards. This file contains
  the expensive SQL. The temporary-table split is intentional: the queries use
  temp tables plus indexes and `ANALYZE` so Postgres does not misplan a giant
  CTE chain.
- `app/models.py` defines `AthleteRating` and `AthleteRatingAverage`.
- `app/routes/top.py` serves the paginated rankings API used by `EloTable.tsx`.
- `app/routes/athletes.py` serves profile, autocomplete, explicit ratings, and
  batch athlete rating APIs.
- `app/routes/brackets.py` attaches rating/rank data to registration and bracket
  competitors.
- `app/frontend/src/components/EloTable.tsx` renders the rankings page.
- `app/frontend/src/components/Athlete.tsx` renders the athlete header, rank
  table, percentile badges, and links from profile ranks back to rankings.

## Generation Flow

`app/ratings.py:recompute_all_ratings` iterates matches in chronological order
for gi/no-gi, writes `MatchParticipant.start_rating`, `end_rating`,
`start_match_count`, `end_match_count`, and rating notes, then regenerates the
ranking boards.

`app/current.py:create_ratings_tables` is run twice:

- `temp_current_ratings` for the current board.
- `temp_previous_ratings` for the previous comparison date, normally the
  previous Tuesday unless `rank_previous_date` is provided.

The helper creates these important temp tables:

- `{name}_athlete_belts`: athlete/belt history from match divisions.
- `{name}_promotion_belts`: manual promotions before the rating date.
- `{name}_athlete_rating_belts`: belt/rating contexts from matches,
  registrations, and promotions.
- `{name}_athlete_adults`: athletes with adult or master history.
- `{name}_athlete_won_matches` and `{name}_athlete_lost_matches`: recent ranked
  match facts by athlete/division context.
- `{name}`: final per-athlete/division rows with end rating, match count, rank,
  percentile, and match date.

`generate_current_ratings` deletes existing rows for the selected gi/no-gi
boards, inserts current rows into `athlete_ratings`, joins the previous temp
board for `previous_rating`, `previous_rank`, `previous_match_count`, and
`previous_percentile`, then rebuilds `athlete_rating_averages`.

## Frontend APIs

- `GET /api/top`: used by `EloTable.tsx`.
  Query params are `gender`, `age`, `belt`, `gi`, `weight`, `country`, `name`,
  `changed`, `upcoming`, and `page`. It returns `{ rows, totalPages }`. Rows
  include athlete identity fields, `rating`, `rank`, `match_count`,
  `previous_rating`, `previous_rank`, `previous_match_count`, and active/upcoming
  registration links.
- `GET /api/athlete/<id>`: used by `Athlete.tsx`.
  Query params include `gi` and `all_medals`. The response includes the athlete
  header rating, Elo history, and `ranks` entries with `rank`, rounded `rating`,
  `percentile`, `age`, `belt`, `weight`, `gender`, and rounded `avg_rating`.
- `GET /api/athletes?search=...`: used by `EloTable.tsx` for the ranking name
  filter/autocomplete.
- `GET /api/athletes/ratings`: accepts `name` and `gi`, returns the latest
  match-participant rating context for that normalized athlete name, including
  `slug`, `rating`, `age`, `weight`, `belt`, and `team_history`. It applies
  registration/manual-promotion belt bumps before returning.
- `POST /api/athletes/batch?event_id=...`: accepts an array of IBJJF athlete ids.
  If `event_id` resolves gi/no-gi, it returns one rounded `rating`; otherwise it
  returns gi `rating` and `nogi-rating`. It also returns `provisional`, `slug`,
  `instagram_profile`, and `country` when present. It falls back to latest match
  ratings plus registration/manual-promotion belt bumps for athletes not present
  on a stored ranking board.
- Bracket APIs in `app/routes/brackets.py` do not simply mirror `/api/top`.
  `get_ratings` matches scraped/registration competitors to athletes, reads
  stored `AthleteRating.rank` when available, derives current rating and
  `match_count` from recent `MatchParticipant` rows, and may overlay `LiveRating`
  during active tournaments.

## Key Data Items

- `AthleteRating`: one current board row per athlete/gender/age/gi/weight.
  Fields include `belt`, `rating`, `match_happened_at`, nullable `rank` and
  `percentile`, `match_count`, and previous-board comparison fields. The unique
  constraint is on `athlete_id`, `gender`, `age`, `gi`, and `weight`; belt is not
  part of the uniqueness rule, so promotion logic must avoid duplicate contexts.
- `AthleteRatingAverage`: one average row per gender/age/belt/gi/weight.
  Athlete profiles join it to rank rows for percentile/badge display.
- `MatchParticipant.start_rating` / `end_rating`: chronological Elo values.
  Stored ranking rows are derived from these, but bracket views can also use the
  latest match participant row directly when no stored rank exists.
- `match_count`: count of ranked matches in the rolling window. The frontend uses
  `RATING_VERY_IMMATURE_COUNT` and `RATING_IMMATURE_COUNT` through
  `immatureClass` to mark provisional and semi-provisional ratings.
- `rank`: computed only for sufficiently mature board rows. UI code should allow
  null ranks even when a rating exists.
- `percentile`: used for athlete profile badges and elite filtering; beware that
  provisional rows have had ordering bugs before.
- `canonical_rating_age`: normalizes juvenile age variants and adult/master
  contexts before matching rankings to divisions.

## Tests

Run Python tests from the repository root:

```sh
make test
```

Useful focused tests while editing ranking behavior:

- `app/tests/test_top_api.py` for `/api/top` filters, pagination, changed rows,
  and upcoming registrations.
- `app/tests/test_athlete_profile_api.py` for profile ratings, rank display, and
  profile payload shape.
- `app/tests/test_athletes_batch_api.py` for batch rating fallback and promoted
  or non-ranked athletes.
- `app/tests/test_current_ratings_promotions.py` for promotion handling in stored
  ranking generation.
- `app/tests/test_current_ratings_juvenile.py` for juvenile age handling.
- Bracket tests such as `app/tests/test_brackets_hypothetical_seed_api.py` and
  `app/tests/test_brackets_archive_competitors_api.py` when touching
  `app/routes/brackets.py`.

Do not run OCR tests for ranking-only changes.

## Regression History

These issues have already surfaced in git history and are worth keeping in mind:

- `5c421e3` fixed athletes disappearing from rankings on promotion by changing
  `app/current.py` and adding promotion-generation tests.
- `a408d45` fixed promotion bumps in athlete profiles and added batch API
  fallback coverage for non-ranked athletes.
- `865410c` fixed the white-to-blue rating bump, which is a special case because
  kids belts sit between white and blue in belt ordering.
- `255e873` fixed combined juvenile age divisions; `3f8c4dc` removed
  juveniles/teens from adult registrations.
- `6edfba3` and `c2a4b34` fixed default rating and rounded default rating
  behavior.
- `bf2f7f9`, `e054297`, `9f2f13e`, and related percentile commits fixed
  percentile checks, factors, ordering, and clamping.
- `91fa3fd` made a bracket query deterministic when multiple athletes share the
  same name.
- `725dc08`, `1ae03f8`, `adb1e93`, and `5859057` changed how registration and
  live ratings use date cutoffs; avoid using stale live ratings or ratings from
  after a registration reference date.
- `13ee652` fixed wrong belt display in gi/no-gi profile states when no rank
  exists.
- `1c975f0` handled athletes promoted from juvenile to adult in registrations.

## Editing Notes

- Preserve the temp-table/index/`ANALYZE` pattern in `app/current.py` unless you
  have verified query plans on realistic data. The split exists because Postgres
  misplanned the fully materialized CTE version.
- Treat promotion logic as shared behavior. Changes in `app/current.py`,
  `app/routes/athletes.py`, and `app/routes/brackets.py` should stay consistent.
- Keep null rank handling in the frontend. A rating without a rank is valid for
  provisional or fallback cases.
- When changing ranking age or belt matching, check adult/master, juvenile,
  registration, and manual-promotion cases together.
