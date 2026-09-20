#!/usr/bin/env python3
"""Refresh result_medals from a validated result snapshot.

Each non-empty event is reconciled in its own transaction. Unique result slots
retain one database row across name/team changes; crowded slots are recorded
for review and are never guessed.
"""

import argparse
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402
from models import (  # noqa: E402
    Athlete,
    ResultMedal,
    ResultRenameObservation,
    ResultSnapshot,
)
from normalize import normalize  # noqa: E402
from result_identity import abbreviated_name_key  # noqa: E402

import get_medals  # noqa: E402
from result_snapshot_pipeline import (  # noqa: E402
    compare_event_rows,
    event_key,
    occurrence_key,
)


DEFAULT_BATCH_SIZE = 1000


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--year",
        default=str(datetime.utcnow().year),
        help="Four-digit result year to scrape. Default: current UTC year.",
    )
    parser.add_argument(
        "--source",
        choices=["all", "ibjjf", "cbjj"],
        default="all",
        help="Which result index(es) to scrape. Default: all.",
    )
    parser.add_argument(
        "--tournament",
        help="Only scrape event-years whose tournament name contains this substring.",
    )
    parser.add_argument(
        "--championship-id",
        help="Only scrape the IBJJF championship with this exact numeric ID.",
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
        active=True,
    )


def _model_row(row):
    return {
        "id": str(row.id),
        "event_name": row.event_name,
        "event_ibjjf_id": row.event_ibjjf_id or "",
        "division": row.division,
        "athlete_name": row.athlete_name,
        "team_name": row.team_name,
        "place": row.place,
        "source": row.source,
        "event_url": row.event_url or "",
        "scraped_at": row.scraped_at.isoformat(),
    }


def _uniquely_named_athlete(session, name):
    """Return the one canonical athlete matching name, never guess duplicates."""
    matches = (
        session.query(Athlete)
        .filter(Athlete.normalized_name == normalize(name))
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def reconcile_event(session, rows, snapshot):
    """Promote one successfully parsed, non-empty event atomically."""
    if not rows:
        raise ValueError("refusing to reconcile an empty result page")
    first = rows[0]
    query = session.query(ResultMedal).filter(ResultMedal.source == first["source"])
    if first.get("event_ibjjf_id"):
        query = query.filter(ResultMedal.event_ibjjf_id == first["event_ibjjf_id"])
    else:
        query = query.filter(ResultMedal.event_name == first["event_name"])
    existing = query.filter(ResultMedal.active.is_(True)).all()
    changes = compare_event_rows([_model_row(row) for row in existing], rows)
    slot_counts = Counter(change.slot_key for change in changes)
    counts = defaultdict(int)

    for change in changes:
        counts[change.change_type] += 1
        if change.change_type == "uncertain":
            before = "; ".join(r["athlete_name"] for r in change.old)
            after = "; ".join(r["athlete_name"] for r in change.new)
            session.add(
                ResultRenameObservation(
                    snapshot_id=snapshot.id,
                    slot_key=change.slot_key,
                    old_name=before,
                    new_name=after,
                    change_type="uncertain",
                    status="pending",
                    evidence="crowded_result_slot",
                )
            )
            continue
        if change.change_type == "added":
            medal = result_medal_from_row(change.new)
            prior = session.get(ResultMedal, medal.id)
            if prior is not None:
                prior.active = True
                prior.snapshot_id = snapshot.id
                prior.scraped_at = medal.scraped_at
                prior.team_name = medal.team_name
                prior.event_url = medal.event_url
                medal = prior
            else:
                session.add(medal)
            medal.snapshot_id = snapshot.id
            medal.occurrence_key = (
                occurrence_key(change.new)
                if slot_counts[change.slot_key] == 1
                else None
            )
            continue
        old_id = uuid.UUID(change.old["id"])
        medal = session.get(ResultMedal, old_id)
        if change.change_type == "removed":
            medal.active = False
            medal.snapshot_id = snapshot.id
            continue
        medal.occurrence_key = (
            occurrence_key(change.new) if slot_counts[change.slot_key] == 1 else None
        )
        medal.team_name = change.new["team_name"]
        medal.event_url = change.new.get("event_url") or None
        medal.scraped_at = datetime.fromisoformat(change.new["scraped_at"])
        medal.snapshot_id = snapshot.id
        if change.change_type == "renamed":
            old_name = medal.athlete_name
            medal.athlete_name = change.new["athlete_name"]
            if abbreviated_name_key(medal.athlete_name):
                # IBJJF now masks minor names as an initial plus surname. This
                # is a display/privacy change, not canonical rename evidence.
                continue
            athlete = _uniquely_named_athlete(session, old_name)
            session.add(
                ResultRenameObservation(
                    snapshot_id=snapshot.id,
                    result_medal_id=medal.id,
                    athlete_id=athlete.id if athlete else None,
                    slot_key=change.slot_key,
                    old_name=old_name,
                    new_name=medal.athlete_name,
                    old_team=change.old.get("team_name"),
                    new_team=medal.team_name,
                    change_type="renamed",
                    status="pending",
                    evidence="unique_result_slot",
                )
            )
    session.flush()
    return dict(counts)


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


def run_update(
    year,
    source="all",
    tournament=None,
    championship_id=None,
    limit=None,
    batch_size=DEFAULT_BATCH_SIZE,
):
    print(f"Updating result_medals for {year} from source={source}.", flush=True)
    scrape_session = get_medals.make_session()
    links = get_medals.build_result_links(
        source=source,
        year=str(year),
        tournament=tournament,
        championship_id=championship_id,
        limit=limit,
        session=scrape_session,
    )
    print(f"Result pages queued: {len(links)}", flush=True)

    stats = {}
    grouped = defaultdict(list)
    for row in get_medals.iter_result_medal_rows(
        links, session=scrape_session, stats=stats
    ):
        grouped[event_key(row)].append(row)

    snapshot = ResultSnapshot(status="candidate", stats={})
    db.session.add(snapshot)
    db.session.commit()
    promoted = 0
    change_counts = defaultdict(int)
    for key in sorted(grouped):
        rows = grouped[key]
        if not rows:
            continue
        try:
            counts = reconcile_event(db.session, rows, snapshot)
            db.session.commit()
            promoted += 1
            for kind, count in counts.items():
                change_counts[kind] += count
        except Exception:
            db.session.rollback()
            snapshot = db.session.get(ResultSnapshot, snapshot.id)
            snapshot.status = "partial"
            db.session.commit()
            raise

    snapshot = db.session.get(ResultSnapshot, snapshot.id)
    snapshot.completed_at = datetime.utcnow()
    snapshot.status = "partial" if stats.get("failed_events", 0) else "complete"
    snapshot.stats = {
        **stats,
        "promoted_events": promoted,
        "changes": dict(change_counts),
    }
    db.session.commit()

    print()
    print("Summary:", flush=True)
    print(f"  Result pages scanned:   {stats.get('events', 0)}", flush=True)
    print(f"  Events with rows:       {stats.get('ok_events', 0)}", flush=True)
    print(f"  Empty events:           {stats.get('empty_events', 0)}", flush=True)
    print(f"  Failed events:          {stats.get('failed_events', 0)}", flush=True)
    print(f"  Result rows scraped:    {stats.get('total_rows', 0)}", flush=True)
    print(f"  Events promoted:        {promoted}", flush=True)
    print(f"  Changes:                {dict(change_counts)}", flush=True)
    return {
        "links": len(links),
        "scraped": stats.get("total_rows", 0),
        "promoted_events": promoted,
        "changes": dict(change_counts),
        "failed_events": stats.get("failed_events", 0),
    }


def main():
    args = parse_args()
    with app.app_context():
        run_update(
            year=args.year,
            source=args.source,
            tournament=args.tournament,
            championship_id=args.championship_id,
            limit=args.limit,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
