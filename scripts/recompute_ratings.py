#!/usr/bin/env python3

import sys
import os
import argparse
from datetime import datetime
import logging
import daemon
from daemon import pidfile

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from ratings import recompute_all_ratings
from constants import (
    MALE,
    FEMALE,
)
from app import db, app

log = logging.getLogger("ibjjf")


def main():
    parser = argparse.ArgumentParser(
        description="Recompute ratings with optional filters."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--nogi",
        action="store_true",
        help="Use this flag to compute only no gi.",
    )
    group.add_argument(
        "--gi", action="store_true", help="Use this flag to compute only gi."
    )
    parser.add_argument("--gender", type=str, help="Filter by gender.")
    parser.add_argument(
        "--start-date", type=str, help="Don't rate matches earlier than date."
    )
    parser.add_argument(
        "--rank-only", action="store_true", help="Only recompute ranks, not scores."
    )
    parser.add_argument(
        "--fg",
        action="store_true",
        help="Run in foreground. If not set, the script will run in the background.",
    )

    args = parser.parse_args()

    if not args.fg:
        log_file = "recompute_ratings.log"

        log.info(f"Running in background and logging to {log_file}")

        with daemon.DaemonContext(
            working_directory=os.getcwd(),
            umask=0o002,
            pidfile=pidfile.TimeoutPIDLockFile("/tmp/recompute_ratings.pid"),
            stdout=open(log_file, "a+"),
            stderr=open(log_file, "a+"),
        ):
            return run_recompute(args)
    else:
        return run_recompute(args)


def run_recompute(args):
    if args.gender and args.gender not in (MALE, FEMALE):
        log.error(f"Invalid gender. Must be one of {MALE}, {FEMALE}")
        return -1

    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            try:
                start_date = datetime.strptime(args.start_date, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                log.error(
                    "Invalid start date format. Must be either YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss"
                )
                return -1

    with app.app_context():
        if (not args.gi and not args.nogi) or (args.gi and args.nogi):
            recompute_all_ratings(
                db,
                True,
                gender=args.gender,
                start_date=start_date,
                score=not args.rank_only,
                rerank=not args.nogi,
                rerankgi=True,
                reranknogi=False,
            )
            recompute_all_ratings(
                db,
                False,
                gender=args.gender,
                start_date=start_date,
                score=not args.rank_only,
                rerank=True,
                rerankgi=args.gi,
                reranknogi=True,
            )
        else:
            recompute_all_ratings(
                db,
                args.gi,
                gender=args.gender,
                start_date=start_date,
                score=not args.rank_only,
                rerank=True,
                rerankgi=args.gi,
                reranknogi=not args.gi,
            )

        db.session.commit()

    log.info("Complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
