#!/usr/bin/env python3
"""Insert newly scraped IBJJF/CBJJ medal result rows into result_medals.

This is the incremental companion to get_medals.py. It does not truncate or
update existing rows; ResultMedal.id is deterministic, so existing medals are
counted and skipped.
"""

import argparse
import os
import sys
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402
from models import ResultMedal  # noqa: E402

import get_medals  # noqa: E402


DEFAULT_BATCH_SIZE = 1000


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--year",
        default=str(datetime.utcnow().year),
        help="Four-digit result year to scrape. Default: current UTC year.",
    )
    parser.add_argument(
        "--tournament",
        help="Only scrape event-years whose tournament name contains this substring.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after this many event-year pages. Useful for smoke tests.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per DB commit. Default: {DEFAULT_BATCH_SIZE}.",
    )
    return parser.parse_args()


def result_medal_from_row(row):
    return ResultMedal(
        id=uuid.UUID(row["id"]),
        event_name=row["event_name"],
        event_ibjjf_id=row["event_ibjjf_id"] or None,
        division=row["division"],
        athlete_name=row["athlete_name"],
        team_name=row["team_name"],
        place=int(row["place"]),
        source=row["source"],
        event_url=row["event_url"] or None,
        scraped_at=datetime.fromisoformat(row["scraped_at"]),
    )


def insert_new_rows(session, rows):
    if not rows:
        return 0, 0

    row_ids = [uuid.UUID(row["id"]) for row in rows]
    existing_ids = {
        existing_id
        for (existing_id,) in session.query(ResultMedal.id)
        .filter(ResultMedal.id.in_(row_ids))
        .all()
    }
    new_rows = [row for row in rows if uuid.UUID(row["id"]) not in existing_ids]
    if not new_rows:
        return 0, len(rows)

    session.add_all(result_medal_from_row(row) for row in new_rows)
    try:
        session.commit()
    except IntegrityError:
        # If another task inserted one of these rows concurrently, keep the
        # incremental job idempotent by rolling back and inserting one at a time.
        session.rollback()
        inserted = 0
        existing = len(rows) - len(new_rows)
        for row in new_rows:
            if session.get(ResultMedal, uuid.UUID(row["id"])) is not None:
                existing += 1
                continue
            session.add(result_medal_from_row(row))
            try:
                session.commit()
                inserted += 1
            except IntegrityError:
                session.rollback()
                existing += 1
        return inserted, existing

    return len(new_rows), len(rows) - len(new_rows)


def run_update(year, tournament=None, limit=None, batch_size=DEFAULT_BATCH_SIZE):
    print(f"Updating result_medals for {year} from IBJJF and CBJJ.", flush=True)
    scrape_session = get_medals.make_session()
    links = get_medals.build_result_links(
        source="all",
        year=str(year),
        tournament=tournament,
        limit=limit,
        session=scrape_session,
    )
    print(f"Result pages queued: {len(links)}", flush=True)

    stats = {}
    batch = []
    inserted_total = 0
    existing_total = 0
    batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))

    def flush_batch():
        nonlocal batch, inserted_total, existing_total
        inserted, existing = insert_new_rows(db.session, batch)
        inserted_total += inserted
        existing_total += existing
        print(
            f"  DB batch: {inserted} inserted, {existing} already present "
            f"(running: inserted={inserted_total}, existing={existing_total})",
            flush=True,
        )
        batch = []

    for row in get_medals.iter_result_medal_rows(
        links, session=scrape_session, stats=stats
    ):
        batch.append(row)
        if len(batch) >= batch_size:
            flush_batch()

    if batch:
        flush_batch()

    print()
    print("Summary:", flush=True)
    print(f"  Result pages scanned:   {stats.get('events', 0)}", flush=True)
    print(f"  Events with rows:       {stats.get('ok_events', 0)}", flush=True)
    print(f"  Empty events:           {stats.get('empty_events', 0)}", flush=True)
    print(f"  Failed events:          {stats.get('failed_events', 0)}", flush=True)
    print(f"  Result rows scraped:    {stats.get('total_rows', 0)}", flush=True)
    print(f"  New rows inserted:      {inserted_total}", flush=True)
    print(f"  Rows already present:   {existing_total}", flush=True)
    return {
        "links": len(links),
        "scraped": stats.get("total_rows", 0),
        "inserted": inserted_total,
        "existing": existing_total,
        "failed_events": stats.get("failed_events", 0),
    }


def main():
    args = parse_args()
    with app.app_context():
        run_update(
            year=args.year,
            tournament=args.tournament,
            limit=args.limit,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
