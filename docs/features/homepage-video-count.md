# Homepage Video Count

## User-Facing Behavior

The banner below the main navigation shows:

```text
XX,XXX free IBJJF match videos and counting... · See Disclaimer
```

The total is loaded from `GET /api/site-statistics` and formatted for the
selected English or Portuguese locale. `See Disclaimer` links to the existing
disclaimer section on the About page. The banner is hidden while no cached value
exists and on the About page, matching the placement rules of the older
affiliation disclaimer it replaced.

## Coverage Semantics

`app/site_statistics.py` deliberately uses the ordinary mat-aware and linked
OCR/archive resolvers from `app/livestreams.py`, the same resolution paths used
by Database and bracket APIs. A match counts only when its final resolved link
is a valid YouTube URL.

This means the total:

- includes matches inside a visible livestream's event day, mat, and time range;
- includes OCR-linked matches through their visible YouTube frame archive even
  when the match has no mat number;
- includes an individual match YouTube link even without livestream coverage;
- excludes a match whose individual link is the case-insensitive `NONE` sentinel;
- excludes matching livestream ranges with `hide_all` enabled;
- excludes FloGrappling links; and
- excludes no-show, overweight, and withdrawal rows whose video icons are
  suppressed by the Database UI.

## Cached Data And API

The `site_statistics` table stores keyed integer counters and their refresh
timestamps. The covered-match row uses the key `covered_match_count`.

`GET /api/site-statistics` reads this one cached row and returns:

```json
{"coveredMatchCount": 12345}
```

It returns `null` when the cache has not been populated; it never performs the
expensive coverage scan from a public request.

## Refresh Paths

`refresh_covered_match_count()` recalculates the total in Python and updates the
cached row in the caller's transaction. Because the production scan is too long
for an HTTP request, admin mutations start an untracked background thread with a
fresh Flask app context, following the registration-import pattern. Refresh
requests within one web process are coalesced, and a change made during an
active scan causes one follow-up scan. A PostgreSQL advisory lock prevents scans
from overlapping across web workers.

A background refresh is queued after:

- adding, editing, or deleting a livestream or changing its event's Flo tag in
  the admin event page;
- syncing the livestream frame archive page;
- saving individual match video links from the athlete matches page; and
- importing individual videos from the YouTube match scanner.
- automatically or manually linking a completed livestream text scan, or
  clearing linked text-scan events.

The standalone `scripts/link_livestream_matches.py --commit` path refreshes the
counter synchronously in the same transaction and prints the new value.

After deploying the migration, populate the row once with the archive page's
Sync action. Sync returns immediately while the count runs in the background;
it does not create a tracked admin task. The direct shell equivalent is:

```bash
cd app
flask refresh-site-statistics
```

No scheduled process is required after that initial refresh.

## Main Code Paths

- `app/site_statistics.py` computes and persists the count.
- `app/livestreams.py` resolves ordinary coverage through
  `get_livestream_link()` and maps linked OCR events to segment-visible
  `LivestreamFrameArchive` YouTube URLs. The linked match time, mat when known,
  and source-video offset distinguish visible and hidden ranges of the same
  upload; ambiguous mixed-visibility associations are suppressed.
- `app/models.py` defines `SiteStatistic`.
- `app/routes/top.py` serves `GET /api/site-statistics`.
- `admin/app.py` starts untracked refresh threads after livestream and
  match-link changes, including YouTube match imports.
- `app/frontend/src/App.tsx` loads and renders the banner.
- `app/frontend/src/global.css` styles the banner.
- `app/tests/test_site_statistics.py` covers the count and API.

## Tests To Run

For focused coverage:

```bash
cd app/tests
python3 -m unittest test_site_statistics test_youtube_match_import_lib
```

For the full non-OCR suite:

```bash
make test
```

Do not run `make test-ocr`; this feature does not change OCR behavior.
