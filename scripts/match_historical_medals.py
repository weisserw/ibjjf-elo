#!/usr/bin/env python3
"""Auto-import high-confidence historical medals for athletes whose names changed.

For each athlete, fuzzy-matches against `result_medals.athlete_name` via rapidfuzz's
token_ratio. The single top-scoring name's medals get auto-imported when the score
is high and clearly beats the runner-up. Lower-confidence matches go into a CSV
report for manual review via the per-athlete admin "Find missing medals" page.

Belt-rank plausibility (an athlete can't have been at a higher belt than their
known matches show on a given date) is the first filter applied.

Idempotent: existing medals are skipped via `medal_already_exists`.

Usage:
    ./scripts/match_historical_medals.py [--dry-run] [--limit N] [--athlete-id UUID]
        [--auto-threshold 92] [--review-threshold 80] [--gap-threshold 8]
        [--report-csv missing_medals_review.csv]
"""

import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402
from models import Athlete, ResultMedal  # noqa: E402

import medal_import_lib as lib  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Auto-import high-confidence historical medals."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most N athletes."
    )
    parser.add_argument(
        "--athlete-id",
        type=str,
        default=None,
        help="Restrict to a single athlete UUID (useful for testing).",
    )
    parser.add_argument(
        "--auto-threshold",
        type=int,
        default=92,
        help="Token-ratio score required for auto-import (default 92).",
    )
    parser.add_argument(
        "--review-threshold",
        type=int,
        default=80,
        help="Token-ratio score required to be written to the review CSV (default 80).",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=8,
        help="Required gap between best and runner-up score for auto-import (default 8).",
    )
    parser.add_argument(
        "--soft-threshold",
        type=int,
        default=75,
        help=(
            "Secondary auto-import tier: score floor when paired with --soft-gap-threshold. "
            "Catches the 'extra middle name / abbreviation' case where exact match isn't 100 "
            "but the gap to the runner-up is wide (default 75)."
        ),
    )
    parser.add_argument(
        "--soft-gap-threshold",
        type=int,
        default=12,
        help="Gap required in the soft tier (default 12).",
    )
    parser.add_argument(
        "--similar-threshold",
        type=int,
        default=85,
        help=(
            "Score floor for counting a candidate as a 'plausible alias' when "
            "deciding whether the athlete's name space is crowded (default 85)."
        ),
    )
    parser.add_argument(
        "--max-similar-candidates",
        type=int,
        default=3,
        help=(
            "When more than N candidates score >= --similar-threshold, the "
            "athlete is treated as a common-name case: only a UNIQUE perfect "
            "match (top == 100 and runner-up < 100) auto-imports; everything "
            "else goes to review (default 3)."
        ),
    )
    parser.add_argument(
        "--report-csv",
        type=str,
        default="missing_medals_review.csv",
        help="CSV path for ambiguous/review-needed matches.",
    )
    return parser.parse_args()


def merge_extracts(extracts_a, extracts_b):
    merged = {}
    for n, s, _ in list(extracts_a) + list(extracts_b):
        if n not in merged or s > merged[n]:
            merged[n] = s
    return sorted(merged.items(), key=lambda kv: -kv[1])


def main():
    args = parse_args()
    from rapidfuzz import fuzz, process

    with app.app_context():
        print("Building division cache...", flush=True)
        division_cache = lib.build_division_cache(db.session)
        print(f"  {len(division_cache)} divisions cached", flush=True)
        print("Loading distinct athlete names from result_medals...", flush=True)
        # Don't load full ORM rows — with ~850k result_medals that's gigabytes.
        # Keep only the distinct name strings in memory for process.extract;
        # fetch the actual rows on demand for the few top-candidate names per athlete.
        all_names = sorted(
            n for (n,) in db.session.query(ResultMedal.athlete_name).distinct().all()
        )
        print(f"  {len(all_names)} distinct names", flush=True)

        athletes_q = db.session.query(Athlete)
        if args.athlete_id:
            athletes_q = athletes_q.filter(Athlete.id == args.athlete_id)
        if args.limit:
            athletes_q = athletes_q.limit(args.limit)

        report_rows = []
        imported = 0
        athletes_seen = 0
        athletes_with_imports = 0
        athletes_with_review = 0

        for athlete in athletes_q.all():
            athletes_seen += 1

            # Fuzzy candidate names (top 10) via rapidfuzz.process — much faster
            # than scoring every candidate explicitly.
            extracts = process.extract(
                athlete.name, all_names, scorer=fuzz.token_sort_ratio, limit=10
            )
            if athlete.personal_name:
                more = process.extract(
                    athlete.personal_name,
                    all_names,
                    scorer=fuzz.token_sort_ratio,
                    limit=10,
                )
                merged = merge_extracts(extracts, more)
            else:
                merged = [(n, s) for n, s, _ in extracts]

            if not merged:
                continue
            best_score = merged[0][1]
            if best_score < args.review_threshold:
                continue

            runner_up = merged[1][1] if len(merged) > 1 else 0
            top_name = merged[0][0]
            gap = best_score - runner_up
            # Adaptive rule: with a crowded name space (many similar candidates)
            # only auto on a unique perfect match; otherwise the standard
            # dual-tier rule (HIGH score+gap OR SOFT score+wide-gap) applies.
            top_gap_satisfied = lib.decide_auto_import(
                merged,
                auto_threshold=args.auto_threshold,
                gap_threshold=args.gap_threshold,
                soft_threshold=args.soft_threshold,
                soft_gap_threshold=args.soft_gap_threshold,
                similar_threshold=args.similar_threshold,
                max_similar_candidates=args.max_similar_candidates,
            )

            athlete_imported_this_run = 0
            athlete_review_this_run = 0

            for cand_name, score in merged:
                if score < args.review_threshold:
                    break
                # Only top_name can be auto-imported; everything else is review.
                is_top_name = cand_name == top_name

                # Fetch this name's result_medals rows on demand (index hit on
                # ix_result_medals_athlete_name). Usually <50 rows.
                rms_for_name = (
                    db.session.query(ResultMedal)
                    .filter(ResultMedal.athlete_name == cand_name)
                    .all()
                )
                for rm in rms_for_name:
                    division_parts = lib.parse_division_parts(rm.division)
                    if not division_parts:
                        continue
                    belt, age, gender, _weight = division_parts

                    # Tentative date for belt-rank filter: midpoint of the event's year.
                    year_match = lib.YEAR_SUFFIX_RE.search(rm.event_name)
                    if not year_match:
                        continue
                    tentative_date = datetime(int(year_match.group(1)), 6, 1)

                    if not lib.medal_is_plausible(
                        db.session, athlete.id, belt, tentative_date
                    ):
                        continue
                    if not lib.gender_is_plausible(db.session, athlete.id, gender):
                        continue
                    if not lib.age_is_plausible(db.session, athlete.id, age):
                        continue

                    gi = not lib.is_no_gi_event(rm.event_name)
                    division = lib.parse_and_resolve_division(
                        db.session, rm.division, gi, division_cache=division_cache
                    )
                    if division is None:
                        continue

                    event = lib.find_event(db.session, rm.event_name, rm.event_ibjjf_id)
                    created_event = False
                    if event is None:
                        try:
                            event = lib.create_medals_only_event(
                                db.session, rm.event_name
                            )
                            created_event = True
                        except ValueError:
                            continue

                    if lib.medal_already_exists(
                        db.session, athlete.id, event.id, division.id
                    ):
                        if created_event:
                            # We created an event we didn't end up using. Roll back.
                            db.session.rollback()
                        continue

                    if is_top_name and top_gap_satisfied and not args.dry_run:
                        team = lib.find_or_create_team(db.session, rm.team_name)
                        happened_at = lib.compute_happened_at(
                            db.session, athlete.id, event, rm.event_name
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
                            imported_via="historical_auto",
                        )
                        athlete_imported_this_run += 1
                        imported += 1
                    elif is_top_name and top_gap_satisfied and args.dry_run:
                        print(
                            f"  [dry-run] {athlete.name} <- {rm.athlete_name} "
                            f"({score}, gap={best_score-runner_up}) | "
                            f"{rm.event_name} | {rm.division} place {rm.place}"
                        )
                        if created_event:
                            db.session.rollback()
                        athlete_imported_this_run += 1
                        imported += 1
                    else:
                        report_rows.append(
                            {
                                "athlete_id": str(athlete.id),
                                "athlete_name": athlete.name,
                                "result_medal_id": str(rm.id),
                                "score": score,
                                "best_score": best_score,
                                "runner_up_score": runner_up,
                                "matched_result_name": rm.athlete_name,
                                "event_name": rm.event_name,
                                "division": rm.division,
                                "place": rm.place,
                                "raw_team_name": rm.team_name,
                            }
                        )
                        if created_event:
                            db.session.rollback()
                        athlete_review_this_run += 1

            if athlete_imported_this_run > 0:
                athletes_with_imports += 1
                if not args.dry_run:
                    db.session.commit()
            if athlete_review_this_run > 0:
                athletes_with_review += 1

            if athletes_seen % 100 == 0:
                print(
                    f"  ... {athletes_seen} athletes processed, "
                    f"{imported} imported, {len(report_rows)} review",
                    flush=True,
                )

        if args.report_csv and report_rows:
            with open(args.report_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "athlete_id",
                        "athlete_name",
                        "result_medal_id",
                        "score",
                        "best_score",
                        "runner_up_score",
                        "matched_result_name",
                        "event_name",
                        "division",
                        "place",
                        "raw_team_name",
                    ],
                )
                writer.writeheader()
                for row in report_rows:
                    writer.writerow(row)
            print(f"\nReview CSV written: {args.report_csv} ({len(report_rows)} rows)")

        print()
        print("Summary:")
        print(f"  Athletes processed:        {athletes_seen}")
        print(f"  Athletes with imports:     {athletes_with_imports}")
        print(f"  Athletes with review rows: {athletes_with_review}")
        print(f"  Medals imported:           {imported}")
        print(f"  Review rows:               {len(report_rows)}")
        if args.dry_run:
            print("  (dry-run; no rows written)")


if __name__ == "__main__":
    main()
