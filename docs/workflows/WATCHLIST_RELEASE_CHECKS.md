# Watchlist release checks

## Local verification, 2026-09-04

- Python tests run in `/Users/will/.pyenv/versions/ibjjf`, not global Python.
  Final `make test` with the PostgreSQL integration tests enabled: 601 tests,
  passing with one existing skip.
- PostgreSQL tests use an isolated local test cluster and disposable schemas.
  Six simultaneous processes establish one tournament owner, at most two global
  owners, and recovery after the old owner exits. Expired owners cannot publish
  over replacements. Migration upgrade/downgrade is exercised in its own schema.
- HTTP timeout tests verify the background session has no open transaction when
  requesting source data. Failed scans retain previous snapshots and release
  their owned slots; a complete scan publishes only after coverage validation.
- Browser smoke tests use synthetic data at 320, 375, 390 and 430 pixels, with
  long names and teams. A reduced viewport approximates keyboard space; this is
  not a physical-device keyboard test. The test verifies search cancellation,
  popup/fallback, edit preloading, separate profile tabs, scroll retention,
  three-minute polling, five-second initial population, hidden-page pause/overdue
  refresh, expired links and error retention.
- TypeScript uses `tsc --noEmit -p tsconfig.app.json`; lint is scoped to watchlist
  components. No frontend build or OCR test run is part of this feature.
- The source-shaped HTML fixture is anonymized: synthetic names, teams, athlete
  IDs and source event/day links, without tracking links. Raw downloads are removed.

## Search performance sample

`dev/watchlist_query_plan.py` builds synthetic data in a disposable PostgreSQL
schema: 50,000 athletes, 100 events, 200,000 registration rows. Two events are
selected. Local execution measured about 12.3 ms for empty name search, 8.6 ms for
filtered name search and 1.4 ms for team search. The selected-registration index
is used in all three; team lookup also uses the athlete-name index. See
[`watchlist-query-plan.txt`](watchlist-query-plan.txt) for the query plans.

These are synthetic local results, not production load-test claims. Check query
plans against production-scale cardinalities and match-history/rating costs in
staging before increasing selection caps or adding further indexes.

## Deployment gates

1. Apply migration `9d3f5a7b1c20` before making the routes available.
2. Verify authoritative tournament start/end dates. Missing dates disable choices;
   date corrections reconcile existing selection expiration on reads and cleanup.
3. Confirm actual web-worker arguments permit threads to continue after responses.
   In staging, start a slow refresh, return the response, recycle the worker and
   confirm a subsequent request recovers after lease expiry without partial data.
4. Register `flask --app app/app.py purge-expired-watchlists` daily in the hosting
   scheduler and check that it runs with the application environment.
5. Observe a busy weekend: claim outcomes, pages/bytes, duration, source freshness,
   topology errors, rating query cost and source throttling. Logs contain event
   and token metadata, not upstream HTML. Tune only after observing the bounds.
6. Check real mobile keyboards, accessibility and the final live source experience.
   Local browser checks use synthetic intercepted API responses.

Hosting worker configuration and scheduler access are not available in this
repository. These gates require the deployment environment.
