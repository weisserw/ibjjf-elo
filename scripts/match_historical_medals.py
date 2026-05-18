#!/usr/bin/env python3
"""Auto-import high-confidence historical medals for athletes whose names changed.

Per athlete, two passes:

  1. KNOWN-ALIAS PASS: any `result_medals.athlete_name` that normalizes to the
     athlete's `name` or `personal_name` is auto-imported. No fuzzy scoring.
  2. FUZZY PASS: rapidfuzz `token_sort_ratio` against the athlete's legal name
     (`athlete.name`) discovers unknown spelling variants. The adaptive
     heuristic (HIGH/SOFT thresholds + crowded-namespace fallback) decides
     auto vs review per candidate name.

Plausibility filters (belt rank, gender, age progression) gate both passes.
Idempotent: existing medals are skipped via `medal_already_exists`.

Resume support: after each athlete the script writes the just-finished
athlete's UUID to `--resume-file`. On the next run, `--resume` reads that
file, jumps past the last-processed athlete, and appends to the review CSV.

Usage:
    ./scripts/match_historical_medals.py [--dry-run] [--limit N] [--athlete-id UUID]
        [--auto-threshold 92] [--review-threshold 80] [--gap-threshold 8]
        [--report-csv missing_medals_review.csv]
        [--resume-file .match_historical_medals.resume] [--resume]
"""

import argparse
import csv
import os
import sys
import uuid as _uuid
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
    parser.add_argument(
        "--resume-file",
        type=str,
        default=".match_historical_medals.resume",
        help=(
            "Path to the resume checkpoint. After each athlete finishes, the "
            "script writes that athlete's UUID here so a future --resume run "
            "can skip past them (default .match_historical_medals.resume)."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Read --resume-file, skip past the last-processed athlete, and "
            "append to the review CSV instead of overwriting it. Errors if "
            "the resume file is missing or invalid."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    from rapidfuzz import fuzz, process

    resume_from_id = None
    if args.resume:
        if not os.path.exists(args.resume_file):
            print(
                f"ERROR: --resume given but {args.resume_file!r} does not exist.",
                file=sys.stderr,
            )
            sys.exit(1)
        with open(args.resume_file) as rf:
            raw = rf.read().strip()
        try:
            resume_from_id = _uuid.UUID(raw)
        except ValueError:
            print(
                f"ERROR: contents of {args.resume_file!r} is not a valid UUID: {raw!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"Resuming after athlete {resume_from_id} "
            f"(read from {args.resume_file}).",
            flush=True,
        )

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

        # Index distinct result_medals names by their normalized form so the
        # alias pass (below) can find every raw spelling that normalizes to one
        # of an athlete's stored aliases in O(1) per athlete.
        print("Indexing names by normalized form...", flush=True)
        normalized_to_raw = {}
        for n in all_names:
            normalized_to_raw.setdefault(lib.normalize(n), []).append(n)
        print(f"  {len(normalized_to_raw)} distinct normalized forms", flush=True)

        # Ordering by id is required so --resume picks up deterministically
        # after an interruption.
        athletes_q = db.session.query(Athlete).order_by(Athlete.id)
        if args.athlete_id:
            athletes_q = athletes_q.filter(Athlete.id == args.athlete_id)
        if resume_from_id is not None:
            athletes_q = athletes_q.filter(Athlete.id > resume_from_id)
        if args.limit:
            athletes_q = athletes_q.limit(args.limit)

        # Open the review CSV once at startup and stream rows into it. This
        # bounds memory and survives mid-run interruptions — partial review
        # data is on disk by the time of any crash.
        csv_fieldnames = [
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
        ]
        csv_file = None
        csv_writer = None
        if args.report_csv:
            csv_exists = os.path.exists(args.report_csv)
            if args.resume and csv_exists:
                csv_file = open(args.report_csv, "a", newline="", encoding="utf-8")
                csv_writer = csv.DictWriter(csv_file, fieldnames=csv_fieldnames)
                print(
                    f"Appending review rows to existing {args.report_csv}.", flush=True
                )
            else:
                csv_file = open(args.report_csv, "w", newline="", encoding="utf-8")
                csv_writer = csv.DictWriter(csv_file, fieldnames=csv_fieldnames)
                csv_writer.writeheader()

        review_count = 0
        imported = 0
        imported_via_alias = 0
        imported_via_fuzzy = 0
        athletes_seen = 0
        athletes_with_imports = 0
        athletes_with_review = 0

        def try_import_rm(
            rm, athlete, *, is_auto, source, score, best_score, runner_up
        ):
            """Plausibility-check a result_medal and either import it, write a
            review row, or skip. Returns 'imported' | 'review' | 'skipped'.

            `source` is 'alias' for known-alias matches (skips fuzzy logging)
            or 'fuzzy' for fuzzy-matched candidates (logs score/gap).
            """
            division_parts = lib.parse_division_parts(rm.division)
            if not division_parts:
                return "skipped"
            belt, age, gender, _weight = division_parts

            year_match = lib.YEAR_SUFFIX_RE.search(rm.event_name)
            if not year_match:
                return "skipped"
            tentative_date = datetime(int(year_match.group(1)), 6, 1)

            if not lib.medal_is_plausible(db.session, athlete.id, belt, tentative_date):
                return "skipped"
            if not lib.gender_is_plausible(db.session, athlete.id, gender):
                return "skipped"
            if not lib.age_is_plausible(db.session, athlete.id, age):
                return "skipped"

            gi = not lib.is_no_gi_event(rm.event_name)
            division = lib.parse_and_resolve_division(
                db.session, rm.division, gi, division_cache=division_cache
            )
            if division is None:
                return "skipped"

            event = lib.find_event(db.session, rm.event_name, rm.event_ibjjf_id)
            created_event = False
            if event is None:
                try:
                    event = lib.create_medals_only_event(db.session, rm.event_name)
                    created_event = True
                except ValueError:
                    return "skipped"

            if lib.medal_already_exists(db.session, athlete.id, event.id, division.id):
                if created_event:
                    db.session.rollback()
                return "skipped"

            if is_auto:
                if not args.dry_run:
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
                else:
                    if source == "alias":
                        print(
                            f"  [dry-run alias] {athlete.name} <- {rm.athlete_name} | "
                            f"{rm.event_name} | {rm.division} place {rm.place}"
                        )
                    else:
                        print(
                            f"  [dry-run] {athlete.name} <- {rm.athlete_name} "
                            f"({score}, gap={best_score-runner_up}) | "
                            f"{rm.event_name} | {rm.division} place {rm.place}"
                        )
                    if created_event:
                        db.session.rollback()
                return "imported"
            else:
                if csv_writer is not None:
                    csv_writer.writerow(
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
                return "review"

        for athlete in athletes_q.all():
            athletes_seen += 1

            # Stored aliases for this athlete — `name` plus optional
            # `personal_name`. Any result_medals row that normalizes to one of
            # these is, by definition, this athlete: auto-import without fuzzy.
            alias_normalized_set = {athlete.normalized_name}
            if athlete.normalized_personal_name:
                alias_normalized_set.add(athlete.normalized_personal_name)
            alias_raw_names = set()
            for nrm in alias_normalized_set:
                alias_raw_names.update(normalized_to_raw.get(nrm, []))

            athlete_imported_this_run = 0
            athlete_review_this_run = 0

            # ---- Pass 1: known-alias matches ----
            for cand_name in alias_raw_names:
                rms_for_name = (
                    db.session.query(ResultMedal)
                    .filter(ResultMedal.athlete_name == cand_name)
                    .all()
                )
                for rm in rms_for_name:
                    result = try_import_rm(
                        rm,
                        athlete,
                        is_auto=True,
                        source="alias",
                        score=100,
                        best_score=100,
                        runner_up=0,
                    )
                    if result == "imported":
                        athlete_imported_this_run += 1
                        imported += 1
                        imported_via_alias += 1

            # ---- Pass 2: fuzzy candidates (unknown spelling variants only) ----
            # Fuzzy discovery is anchored to the athlete's legal name only.
            # Exact-match cases under either stored alias were already handled
            # in Pass 1, so fuzzing the personal_name (an alias) would just
            # rediscover what we already have — wasted work and a source of
            # confusion when two stored aliases produce overlapping top hits.
            extracts = process.extract(
                athlete.name, all_names, scorer=fuzz.token_sort_ratio, limit=10
            )
            merged = [(n, s) for n, s, _ in extracts]

            # Drop names already handled by the alias pass — fuzzy only decides
            # for spellings we don't already have stored.
            merged = [(n, s) for n, s in merged if n not in alias_raw_names]

            if merged and merged[0][1] >= args.review_threshold:
                best_score = merged[0][1]
                runner_up = merged[1][1] if len(merged) > 1 else 0
                auto_names = lib.decide_auto_import_names(
                    merged,
                    auto_threshold=args.auto_threshold,
                    gap_threshold=args.gap_threshold,
                    soft_threshold=args.soft_threshold,
                    soft_gap_threshold=args.soft_gap_threshold,
                    similar_threshold=args.similar_threshold,
                    max_similar_candidates=args.max_similar_candidates,
                )

                for cand_name, score in merged:
                    if score < args.review_threshold:
                        break
                    is_auto = cand_name in auto_names

                    rms_for_name = (
                        db.session.query(ResultMedal)
                        .filter(ResultMedal.athlete_name == cand_name)
                        .all()
                    )
                    for rm in rms_for_name:
                        result = try_import_rm(
                            rm,
                            athlete,
                            is_auto=is_auto,
                            source="fuzzy",
                            score=score,
                            best_score=best_score,
                            runner_up=runner_up,
                        )
                        if result == "imported":
                            athlete_imported_this_run += 1
                            imported += 1
                            imported_via_fuzzy += 1
                        elif result == "review":
                            athlete_review_this_run += 1
                            review_count += 1

            if athlete_imported_this_run > 0:
                athletes_with_imports += 1
                if not args.dry_run:
                    db.session.commit()
            if athlete_review_this_run > 0:
                athletes_with_review += 1

            # Flush review CSV + write checkpoint after every athlete. If the
            # connection drops mid-run, the next `--resume` picks up at the
            # athlete after this one without losing the review rows we've
            # already produced.
            if csv_file is not None:
                csv_file.flush()
            try:
                with open(args.resume_file, "w") as rf:
                    rf.write(str(athlete.id))
            except OSError as exc:
                print(
                    f"WARNING: could not write resume file {args.resume_file!r}: {exc}",
                    file=sys.stderr,
                )

            if athletes_seen % 100 == 0:
                print(
                    f"  ... {athletes_seen} athletes processed, "
                    f"{imported} imported ({imported_via_alias} alias, "
                    f"{imported_via_fuzzy} fuzzy), {review_count} review",
                    flush=True,
                )

        if csv_file is not None:
            csv_file.close()
            print(f"\nReview CSV: {args.report_csv} ({review_count} rows this run)")

        print()
        print("Summary:")
        print(f"  Athletes processed:        {athletes_seen}")
        print(f"  Athletes with imports:     {athletes_with_imports}")
        print(f"  Athletes with review rows: {athletes_with_review}")
        print(f"  Medals imported:           {imported}")
        print(f"    via known alias:         {imported_via_alias}")
        print(f"    via fuzzy match:         {imported_via_fuzzy}")
        print(f"  Review rows (this run):    {review_count}")
        if args.dry_run:
            print("  (dry-run; no rows written)")


if __name__ == "__main__":
    main()
