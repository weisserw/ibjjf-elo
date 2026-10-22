# Livestream Editor

The server-rendered admin page at `/event/livestreams?id=<IBJJF event ID>`
edits per-day, per-mat livestreams, Flo per-mat links, and the Flo event tag.

The **Copy streams from event** section displays an event/day picker below
the other controls and above Back to Dashboard. It offers up to six
other events with livestreams, newest tournament date first (first match date,
falling back to registration start date; unknown dates sort last). Only days
with streams are offered. Day 2 is selected by default when available,
otherwise the earliest available day is selected; day 1 remains selectable.

Import copies all streams for the selected day, including mat, platform, URL,
start/end times, drift factor, and hide-all setting. The destination day is
the source day minus one, with a minimum of 1: 1 → 1, 2 → 1, 3 → 2.
The picker previews the destination day. Existing streams remain, exact
duplicates are skipped, and the source rows are unchanged. Flo tags and
Flo per-mat links have no day field and are managed separately.

## Code and validation

- `admin/app.py`: `event_livestreams` GET/POST route.
- `admin/templates/event_livestreams.html`: editor and event/day picker.
- `app/livestream_copy.py`: source selection and stream copying.
- `app/tests/test_livestream_copy.py`: date ordering, cap, day mapping,
  settings preservation, duplicate handling, and invalid selections.

Run `make test` from the repository root. No OCR tests or frontend build
are needed for this server-rendered editor.
