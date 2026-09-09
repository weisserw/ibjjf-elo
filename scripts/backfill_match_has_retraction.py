#!/usr/bin/env python3
"""Backfill Match.has_retraction for OCR-linked matches.

The database column is the checkpoint: every batch commits non-null values, so
rerunning the script automatically resumes with the remaining null rows.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import LivestreamFrameTextEvent, Match  # noqa: E402
from routes.matches import has_score_retraction  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    with app.app_context():
        pending_query = Match.query.filter(
            Match.has_retraction.is_(None),
            Match.id.in_(
                db.session.query(LivestreamFrameTextEvent.match_id).filter(
                    LivestreamFrameTextEvent.match_id.isnot(None)
                )
            ),
        )
        initial_pending = pending_query.count()
        processed = 0
        retractions = 0
        print(f"Starting backfill: pending={initial_pending}", flush=True)

        while True:
            matches = pending_query.order_by(Match.id).limit(args.batch_size).all()
            if not matches:
                break

            match_ids = [match.id for match in matches]
            events_by_match = defaultdict(list)
            events = (
                LivestreamFrameTextEvent.query.filter(
                    LivestreamFrameTextEvent.match_id.in_(match_ids)
                )
                .order_by(
                    LivestreamFrameTextEvent.match_id,
                    LivestreamFrameTextEvent.frame_second,
                )
                .all()
            )
            for event in events:
                events_by_match[event.match_id].append(event)

            batch_retractions = 0
            for match in matches:
                match.has_retraction = has_score_retraction(events_by_match[match.id])
                batch_retractions += int(match.has_retraction)

            db.session.commit()
            processed += len(matches)
            retractions += batch_retractions
            print(
                f"Progress: processed={processed}/{initial_pending} "
                f"retractions={retractions} last_match_id={matches[-1].id}",
                flush=True,
            )

        print(
            f"Backfill complete: processed={processed} retractions={retractions}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
