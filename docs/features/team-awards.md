# Team Awards

## Entry points

- `app/routes/awards.py`: `/api/awards/teams` and `/api/awards/events/recent`.
- `app/frontend/src/components/Teams.tsx`: event awards and country grouping.
- `app/frontend/src/components/YearlyTeamAwards.tsx`: separately maintained,
  hardcoded yearly results. Event API changes do not regenerate these results.
- `app/team_name_mapping.py`: shared Team Name Mappings loader and resolver.
- `admin/app.py`: `team_name_mappings_settings` manages mapping rules.

## Team-name grouping

Event team awards use the same resolver as athlete team history: exact matches
take precedence over case-sensitive glob patterns, and more-specific glob
patterns take precedence over broader ones. Unmatched names remain unchanged.
Resolution is a single pass, not recursive mapping through multiple rules.

`_event_team_mapping` fetches distinct team IDs/names in the selected event's
rated matches and resolves each distinct name once in Python. It supplies a
parameterized `resolved_teams` VALUES CTE to the awards SQL. UUID parameters
are typed for PostgreSQL and SQLite compatibility. Teams resolving to the same
name share a request-local canonical ID, taken from one of those team rows;
the canonical name does not need its own row in `teams`.

SQL uses this lookup for both match participants and distinct-athlete counts.
Aliases merge **before** minimum-athlete eligibility, score calculation, ranking,
and the top-result cutoff. An athlete appearing under multiple aliases counts
once toward their canonical team's eligibility. Wins and match totals combine;
win percentages and average defeated ratings are computed from the combined
match data rather than by averaging existing leaderboard values.

Mappings are loaded on each team-awards request, so admin edits apply on the
next request. There is no stored canonical-team column or mapping cache to
rebuild. Python work is proportional to distinct event team names and mapping
rules; match processing and aggregation remain in SQL. Production latency has
not been benchmarked.

Country grouping bypasses team mappings. Rated matches between athletes in
the same canonical team retain the existing scoring behavior: both participant
results count when the match otherwise qualifies.

## Scoring and eligibility

The query selects rated matches for the normalized event name, excludes the
configured white/youth belts, and requires opposing winner flags for scored
match pairs. Open-class defeated ratings receive the existing weight adjustment.
The score is win fraction multiplied by average defeated rating (or zero when
no defeated rating is available).

Minimum team size is 1% of distinct rated-event athletes, rounded and clamped
to 5–15. Per-team eligibility counts distinct athletes in rated matches with
eligible belts. Results are limited to 3, 5, or 10 teams according to event
participation. Ties sort by win percentage, average defeated rating, then name.

## Tests

- `app/tests/test_awards_team_mappings_api.py`: merged eligibility, exact/glob
  precedence, canonical names without team rows, weighted scoring, athlete
  deduplication, merging before the top-N cutoff, unchanged country grouping,
  same-team scoring, immediate mapping edits, and empty events.
- `app/tests/test_brackets_archive_awards_api.py`: baseline awards, country
  awards, and open-class rating adjustments.
- `app/tests/test_awards_recent_events_api.py`: event selection and limits.

Run `make test` from the repository root with the project's Python environment.
No OCR test or frontend build is needed for changes confined to this backend.
