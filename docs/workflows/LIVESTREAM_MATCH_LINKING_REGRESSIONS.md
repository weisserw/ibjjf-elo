# Livestream Match Linking Regressions

Use this workflow when a livestream OCR match-linking issue shows up in
`scripts/link_livestream_matches.py --verbose` output and you want to turn it
into a regression test.

## Quick Handoff Prompt

If you are starting a new coding session, this is enough context to provide:

```text
I found a livestream match-linking issue. The verbose log is in log.txt.
Find the bad match window, choose a small frame-second range around it, and give
me the command to export a test fixture with scripts/export_livestream_text_events.py.
Then add a regression test in app/tests/test_livestream_match_linking.py.
```

If you already know the archive or scan id and the relevant log times, include
them:

```text
Archive/scan id: <uuid>
Problem log span: <start time> through <end time>
Expected behavior: <one sentence, for example "these stopped-clock score updates
should remain linked to the same match">
```

## Find the Export Range

The verbose linker log prints windows like this:

```text
[38] 3:01:44-3:03:01 cursor=22 video_offset=3:03:01 ...
[39] 3:03:13-3:03:34 cursor=23 video_offset=- ...
```

Pick a range that includes:

- the previous match ending or blank/victory reset
- the problem match start
- the events that were skipped or linked incorrectly
- the next match start, when the boundary matters

Prefer a small span of real OCR events over a whole archive. A good starting
range is usually 5-15 minutes around the issue.

## Export Raw OCR Events

Run this from the repository root in an environment that has access to the
database containing the scan/archive id:

```bash
python scripts/export_livestream_text_events.py \
  <scan-or-archive-id> \
  --start <h:mm:ss-or-m:ss> \
  --end <h:mm:ss-or-m:ss> \
  --out app/tests/fixtures/livestream_match_linking/<fixture_name>.json \
  --review app/tests/fixtures/livestream_match_linking/<fixture_name>.md
```

Example:

```bash
python scripts/export_livestream_text_events.py \
  2939fc39-0197-47fa-85bb-8a059626e01a \
  --start 2:53:00 \
  --end 3:15:00 \
  --out app/tests/fixtures/livestream_match_linking/joao_maycon_stopped_score_update.json \
  --review app/tests/fixtures/livestream_match_linking/joao_maycon_stopped_score_update.md
```

The JSON file is the test fixture. The Markdown file is only a review table to
help verify the export by eye.

## Review the Fixture

Open the generated `.md` review file and verify:

- the exported span contains the intended match
- the problem events are present
- the span includes enough context to prove the correct boundary
- the expected result is obvious from timer, score, names, victory, or blank
  rows

The `.md` review file is derived from the JSON and can be regenerated. Commit
the JSON fixture; committing the review file is optional.

## Add the Regression Test

Add a test in `app/tests/test_livestream_match_linking.py` using the existing
helpers:

- `_fixture_events("<fixture_name>.json")`
- `_stored_events(...)`
- `_match_setup(...)` when candidate matches are needed
- `_linked_seconds(match)` for event-to-match assertions
- `extract_match_windows(...)` for pure boundary assertions

Use assertions that describe the behavior you care about, for example:

- a stopped-clock score update remains linked to the same match
- a blank/victory reset splits two appearances of the same athletes
- a later adjacent match still links separately
- `video_start_offset_seconds` remains the first running-clock frame
- final score/timer fields reflect the complete match

Then run:

```bash
python app/tests/test_livestream_match_linking.py -v
make test
```

## Current Fixture Pattern

Real replay fixtures live in:

```text
app/tests/fixtures/livestream_match_linking/
```

The tests currently cover:

- stopped-clock score updates that should continue the same match
- longer stopped-clock continuation before a blank reset
- repeated same-athlete matches that must split after a blank reset
