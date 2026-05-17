#!/usr/bin/env python3
"""Find and import medals that the IBJJF posted to their results page after we
imported the bracket for an event.

Run this against prod once for the April-2025-to-now backfill, then optionally
every 1-2 weeks for ongoing coverage. The admin UI at /missing_medals_scan
covers the ongoing case for non-technical users.

Idempotent: re-runs skip medals already in the canonical medals table.

Usage:
    ./scripts/import_recent_missing_medals.py [--since 2025-04-01] [--until today]
        [--dry-run] [--no-fuzzy]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402

import medal_import_lib as lib  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import missing medals for events with brackets in a date range."
    )
    parser.add_argument(
        "--since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=None,
        help="Start date (YYYY-MM-DD). Default: 28 days ago.",
    )
    parser.add_argument(
        "--until",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=None,
        help="End date (YYYY-MM-DD), inclusive. Default: today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be imported without writing to the DB.",
    )
    parser.add_argument(
        "--no-fuzzy",
        action="store_true",
        help="Disable fuzzy name matching (exact normalized match only).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    now = datetime.utcnow()
    until = args.until or now
    since = args.since or (now - timedelta(days=28))
    if until < since:
        print(
            f"--until ({until.date()}) is before --since ({since.date()})",
            file=sys.stderr,
        )
        sys.exit(1)
    until_end_of_day = until.replace(hour=23, minute=59, second=59)
    fuzzy = not args.no_fuzzy

    with app.app_context():
        print("Building division cache...", flush=True)
        division_cache = lib.build_division_cache(db.session)
        print(f"  {len(division_cache)} divisions cached", flush=True)
        print("Finding events in range...", flush=True)
        events = lib.find_events_with_matches_in_range(
            db.session, since, until_end_of_day
        )
        print(
            f"Scanning {len(events)} events from {since.date()} to {until.date()}",
            flush=True,
        )
        print(f"Fuzzy matching: {'on' if fuzzy else 'off'}", flush=True)
        print(flush=True)

        total_imported = 0
        total_no_match = 0
        total_ambiguous = 0
        total_no_division = 0
        total_already = 0
        events_with_imports = 0

        for idx, event in enumerate(events, start=1):
            print(
                f"[{idx}/{len(events)}] scanning: {event.name} ...",
                flush=True,
            )
            entries = lib.scan_event_for_missing_medals(
                db.session, event, fuzzy=fuzzy, division_cache=division_cache
            )
            event_imports = 0
            event_no_match = 0
            event_ambiguous = 0
            event_no_division = 0
            event_already = 0
            for entry in entries:
                rm = entry["result_medal"]
                status = entry["status"]
                if status == "matched":
                    athlete = entry["matched_athlete"]
                    division = entry["division"]
                    prefix = "[dry-run]" if args.dry_run else "[import]"
                    print(
                        f"  {prefix} {division.belt}/{division.age}/{division.gender}/{division.weight} | "
                        f"place {rm.place} | {rm.athlete_name} -> {athlete.name}",
                        flush=True,
                    )
                    if not args.dry_run:
                        team = lib.find_or_create_team(db.session, rm.team_name)
                        happened_at = lib.compute_happened_at(
                            db.session, athlete.id, event, event.name
                        )
                        default_gold = lib.compute_default_gold(db.session, rm)
                        lib.insert_medal(
                            db.session,
                            athlete_id=athlete.id,
                            event_id=event.id,
                            division_id=division.id,
                            team_id=team.id,
                            place=rm.place,
                            happened_at=happened_at,
                            default_gold=default_gold,
                            imported_via="recent_scan_auto",
                        )
                    event_imports += 1
                    total_imported += 1
                elif status == "no_division":
                    total_no_division += 1
                    event_no_division += 1
                    print(
                        f"  [no division] division={rm.division!r} | "
                        f"{rm.athlete_name} place {rm.place}",
                        flush=True,
                    )
                elif status == "ambiguous":
                    total_ambiguous += 1
                    event_ambiguous += 1
                    alt_names = ", ".join(
                        f"{a['athlete'].name}({a['score']})"
                        for a in entry["alternatives"][:3]
                    )
                    print(
                        f"  [ambiguous] {rm.athlete_name} place {rm.place} "
                        f"| candidates: {alt_names}",
                        flush=True,
                    )
                elif status == "no_match":
                    total_no_match += 1
                    event_no_match += 1
                    alt_names = ", ".join(
                        f"{a['athlete'].name}({a['score']}{' '+a.get('reason','') if a.get('reason') else ''})"
                        for a in entry["alternatives"][:3]
                    )
                    print(
                        f"  [no match] {rm.athlete_name} place {rm.place} "
                        f"| division={rm.division} | best: {alt_names or '(none)'}",
                        flush=True,
                    )
                elif status == "already_imported":
                    total_already += 1
                    event_already += 1

            if event_imports > 0:
                events_with_imports += 1
                if not args.dry_run:
                    db.session.commit()

            # Per-event recap line so progress is visible even when nothing happens.
            print(
                f"    -> {event_imports} match{'es' if event_imports != 1 else ''}, "
                f"{event_already} already, {event_ambiguous} ambiguous, "
                f"{event_no_match} no-match, {event_no_division} no-division "
                f"(running: imported={total_imported})",
                flush=True,
            )

        if args.dry_run:
            db.session.rollback()

        print()
        print("Summary:")
        print(f"  Events scanned:               {len(events)}")
        print(f"  Events with imports:          {events_with_imports}")
        print(f"  Medals imported:              {total_imported}")
        print(f"  Already imported (skipped):   {total_already}")
        print(f"  No-division (skipped):        {total_no_division}")
        print(f"  Ambiguous matches:            {total_ambiguous}")
        print(f"  No match:                     {total_no_match}")
        if args.dry_run:
            print("  (dry-run; no rows written)")


if __name__ == "__main__":
    main()
