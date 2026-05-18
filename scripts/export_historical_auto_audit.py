#!/usr/bin/env python3
"""Audit-trail CSV for medals imported via `historical_auto`.

Reverse-engineers each Medal row (imported by `match_historical_medals.py`)
back to its likely source `result_medals` row. For each medal we find the
candidate `result_medals` that share the same event + division + place, then
pick the one most plausibly tied to the athlete:

  - If a candidate's `athlete_name` normalizes exactly to the athlete's stored
    `normalized_name` or `normalized_personal_name`, it's an ALIAS-pass match
    (guaranteed correct identity).
  - Otherwise we pick the candidate with the highest `name_score` against the
    athlete's `name` — that's the FUZZY-pass match the import script made.

Default output is fuzzy-only — the alias matches are by construction safe.
Pass `--include-alias` to dump everything.

Usage:
    ./scripts/export_historical_auto_audit.py
        [--report-csv historical_auto_audit.csv]
        [--include-alias]
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402
from models import Athlete, Division, Event, Medal, ResultMedal  # noqa: E402

import medal_import_lib as lib  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export an audit CSV of historical_auto medal imports."
    )
    parser.add_argument(
        "--report-csv",
        default="historical_auto_audit.csv",
        help="Output path for the audit CSV (default historical_auto_audit.csv).",
    )
    parser.add_argument(
        "--include-alias",
        action="store_true",
        help="Include alias-pass matches in the output (default: fuzzy only).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    with app.app_context():
        print("Loading result_medals.athlete_name index...", flush=True)
        all_names = sorted(
            n for (n,) in db.session.query(ResultMedal.athlete_name).distinct().all()
        )
        normalized_to_raw = {}
        for n in all_names:
            normalized_to_raw.setdefault(lib.normalize(n), []).append(n)
        print(f"  {len(all_names)} distinct names", flush=True)

        print("Loading divisions...", flush=True)
        division_by_id = {d.id: d for d in db.session.query(Division).all()}
        print(f"  {len(division_by_id)} divisions", flush=True)

        print("Querying historical_auto medals...", flush=True)
        medals_q = (
            db.session.query(Medal, Athlete, Event)
            .join(Athlete, Athlete.id == Medal.athlete_id)
            .join(Event, Event.id == Medal.event_id)
            .filter(Medal.imported_via == "historical_auto")
            .order_by(Athlete.name, Event.name)
        )
        total = medals_q.count()
        print(f"  {total} medals to audit", flush=True)

        # Per-athlete cache of normalized aliases -> set of raw result_medal names.
        alias_cache = {}

        def alias_raw_for(athlete):
            if athlete.id in alias_cache:
                return alias_cache[athlete.id]
            normed = {athlete.normalized_name}
            if athlete.normalized_personal_name:
                normed.add(athlete.normalized_personal_name)
            raw = set()
            for n in normed:
                raw.update(normalized_to_raw.get(n, []))
            alias_cache[athlete.id] = raw
            return raw

        # Per-event cache of result_medal candidates (event lookup is the
        # expensive part — the same event repeats across many athletes).
        event_candidates_cache = {}

        def candidates_for_event(event):
            if event.id in event_candidates_cache:
                return event_candidates_cache[event.id]
            cands = lib.find_result_medals_for_event(db.session, event)
            event_candidates_cache[event.id] = cands
            return cands

        rows_written = 0
        alias_count = 0
        fuzzy_count = 0
        no_source_count = 0

        with open(args.report_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "athlete_id",
                    "athlete_name",
                    "personal_name",
                    "matched_result_medal_name",
                    "name_score",
                    "event_name",
                    "division",
                    "place",
                    "classification",
                    "imported_at",
                    "result_medal_id",
                ],
            )
            writer.writeheader()

            seen = 0
            for medal, athlete, event in medals_q:
                seen += 1
                if seen % 1000 == 0:
                    print(f"  ... {seen}/{total}", flush=True)

                division = division_by_id.get(medal.division_id)
                if not division:
                    no_source_count += 1
                    continue
                gi_event = not lib.is_no_gi_event(event.name)

                candidates = candidates_for_event(event)

                # Filter to result_medals that match this Medal's
                # (event, division, place). gi comes from event name (we
                # never trust the division string for it), so we compare
                # the parsed division parts to the resolved Division row.
                matching = []
                for rm in candidates:
                    if rm.place != medal.place:
                        continue
                    parts = lib.parse_division_parts(rm.division)
                    if not parts:
                        continue
                    belt, age, gender, weight = parts
                    if (
                        belt != division.belt
                        or age != division.age
                        or gender != division.gender
                        or weight != division.weight
                        or gi_event != division.gi
                    ):
                        continue
                    matching.append(rm)

                if not matching:
                    no_source_count += 1
                    continue

                aliases = alias_raw_for(athlete)

                # Pick the best-matching result_medal for this athlete.
                # Alias hits override fuzzy candidates regardless of score.
                best_rm = None
                best_score = -1
                best_class = None
                for rm in matching:
                    if rm.athlete_name in aliases:
                        best_rm = rm
                        best_score = 100
                        best_class = "alias"
                        break
                if best_class is None:
                    for rm in matching:
                        score = lib.name_score(
                            athlete.name, rm.athlete_name, athlete.personal_name
                        )
                        if score > best_score:
                            best_rm = rm
                            best_score = score
                            best_class = "fuzzy"

                if best_rm is None:
                    no_source_count += 1
                    continue

                if best_class == "alias":
                    alias_count += 1
                    if not args.include_alias:
                        continue
                else:
                    fuzzy_count += 1

                writer.writerow(
                    {
                        "athlete_id": str(athlete.id),
                        "athlete_name": athlete.name,
                        "personal_name": athlete.personal_name or "",
                        "matched_result_medal_name": best_rm.athlete_name,
                        "name_score": best_score,
                        "event_name": event.name,
                        "division": best_rm.division,
                        "place": best_rm.place,
                        "classification": best_class,
                        "imported_at": (
                            medal.imported_at.isoformat() if medal.imported_at else ""
                        ),
                        "result_medal_id": str(best_rm.id),
                    }
                )
                rows_written += 1

        print()
        print("Summary:")
        print(f"  Total historical_auto medals: {total}")
        print(f"    alias-pass:                 {alias_count}")
        print(f"    fuzzy-pass:                 {fuzzy_count}")
        print(f"    no source resolved:         {no_source_count}")
        print(f"  Rows written:                 {rows_written}")
        print(f"  Output: {args.report_csv}")


if __name__ == "__main__":
    main()
