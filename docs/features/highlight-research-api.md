# Highlight Research API

## Purpose

`/api/highlights/v1` is the compact, versioned public research boundary used by
the private highlight worker. It is additive to the website APIs and returns
only public facts. The routes do not accept admin authentication and do not
provide a privacy bypass.

Every JSON response has `schema_version: 1` and an `as_of` timestamp. Requests
reject unknown parameters and bound searches and pages. Canonical entity IDs
are UUID strings; public display names follow the existing hidden-name and
personal-name behavior.

The authenticated admin `GET /api/highlights/score-events` route is the separate
schema-v3 discovery hot path for the same worker. It groups clip moments by match
and returns canonical subject/opponent identity, match-time rating, Elo win
probability, rating maturity, division baselines, exact-category current standing,
stage/result context, scoreboard significance, and coverage. Win probability is
null when either match-time rating is unavailable; otherwise the two participant
values are complementary numbers between 0 and 1 using the bracket-card Elo
expected-score calculation. This private route has one consumer and
is changed in lockstep with the worker's strict parser; it does not carry a legacy
flat response or version fallback.

## Routes

- `GET /api/highlights/v1/athletes?query=...&limit=...`
- `GET /api/highlights/v1/athletes/<athlete_uuid>?gi=true|false`
- `GET /api/highlights/v1/athletes/<athlete_uuid>/matches?gi=...&page=...&page_size=...`
- `GET /api/highlights/v1/matches/<match_uuid>`
- `GET /api/highlights/v1/rankings?...`
- `GET /api/highlights/v1/events?query=...&limit=...`
- `GET /api/highlights/v1/events/<event_uuid>`
- `GET /api/highlights/v1/assets/<asset_ref>`

Ranking filters and semantics delegate to the existing `/api/top` implementation.
Profile facts delegate to `get_athlete_data` without materializing a presigned
photo URL. Match results reuse match-detail ending semantics and the same
livestream/archive visibility helpers used by the Database view.

Athlete-profile rank and medal rows repeat the canonical `athlete_id` so the
worker can normalize them into independent, ownership-checked entities. Medal
rows carry `status: valid|forfeited|suspended`; a medal dated inside an
anti-doping suspension is `forfeited` and must not be presented as an ordinary
valid medal.

Match detail also returns `match_card`, a `contract_version: 1` card snapshot.
It contains one explicit `red` and one explicit `blue` bracket row, each row's
`top|bottom|null` scoreboard position, match-time rating, optional public
country/Instagram fields, winner semantics, and the score selected through that
scoreboard position. Historical Elite badges stay null because the database does
not store a match-time percentile; the API does not mix current profile status
into an archived match. The card repeats result method/time semantics so `SUB`
can only be shown for a researched Submission result.

Athlete profile Elo history reuses its existing match, division, and team joins
to avoid per-row relationship loads. Athlete search resolves current teams with
one ranked query that returns only the latest team row per result rather than
materializing every historical team assignment.

## Logical assets

Research responses never include a presigned profile-photo URL. An available
photo is represented by `athlete-photo.<athlete_uuid>`. The asset route accepts
only a previously representable logical reference, reads the fixed athlete-photo
S3 key with bounded client timeouts, and validates the actual bytes, decoded format,
and pixel count. Legacy JPEG/PNG objects remain usable when their S3 metadata has a
generic content type; the response emits the verified normalized media type.
Successful responses include dimensions, an ETag, and bounded public caching.
Missing objects return `404`; invalid or unavailable upstream objects fail closed.

## Main code paths

- `app/routes/highlights.py` owns request validation and response construction.
- `app/routes/athletes.py` owns athlete privacy, profile, medal, promotion, and
  team-history behavior shared by the research profile.
- `app/routes/top.py` owns ranking filters and pagination shared by research.
- `app/routes/matches.py` owns result and ending-method semantics.
- `app/livestreams.py` owns visible public video-link resolution.
- `app/photos.py` owns the logical athlete-photo storage key.
- `app/highlight_discovery.py` owns the private grouped discovery query and
  schema-v3 serialization.
- `admin/app.py` owns authentication and the thin private discovery route.

## Tests

Run the focused contract suite from `app/tests`:

```sh
python3 -m unittest test_highlights_research_api test_admin_highlights_api test_elo
```

The suite covers schema/version envelopes, strict query bounds, hidden-name
privacy, ambiguity, pagination, rankings, match/event facts, query counts, and
asset validation/caching. Run `make test` from the repository root before
shipping related changes.

## Downstream acceptance

The private highlight worker treats this API as untrusted, versioned research
data. Its Milestone 5 acceptance gate combines at least one route above with the
private highlight-event search, validates every StoryPlan reference against the
per-run catalog, and creates an unapproved editable draft without generating
speech, downloading video, preparing media, or rendering.

When changing a response, run the worker's deterministic platform-contract and
agent regression suites as well as this repository's focused contract suite. A
live worker acceptance run must be explicitly enabled because it calls deployed
services and a configured planning model. The worker records logical routes and
opaque evidence/asset references; it must not persist presigned URLs, credentials,
raw private payloads, or downloaded image bytes in its research catalog.

## Editing notes

- Keep unknown-field behavior strict because the private worker parses exact DTOs.
- Update the private worker parser and its fixtures in the same change as a private
  discovery response-shape change. The private endpoint and its sole consumer cut
  over together; do not add dual response shapes or fallback parsing.
- Do not return presigned asset URLs, admin fields, hidden names, or internal UI
  payloads.
- Preserve SQLite/Postgres behavior and constant query counts for bounded lists.
