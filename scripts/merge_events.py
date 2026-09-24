#!/usr/bin/env python
"""Safely merge one duplicate event into a canonical event."""

import argparse
import os
import sys
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db
from models import Event, Match, Medal


def _parse_uuid(value, label):
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Invalid {label} event ID: {value}") from None


def validate_merge(keep, merge):
    conflicts = []
    if keep.id == merge.id:
        conflicts.append("keep and merge IDs are identical")
    if keep.ibjjf_id and merge.ibjjf_id and keep.ibjjf_id != merge.ibjjf_id:
        conflicts.append("events have different non-empty IBJJF IDs")
    return conflicts


def merge_events(keep, merge):
    conflicts = validate_merge(keep, merge)
    if conflicts:
        raise ValueError("; ".join(conflicts))

    if not keep.ibjjf_id:
        keep.ibjjf_id = merge.ibjjf_id
        # Avoid a transient unique-key collision if the source owns the ID.
        merge.ibjjf_id = None

    # False means the event has match data. Preserve that stronger state no
    # matter which side of a medals-only/archive pair was selected as `keep`.
    # Legacy archive events can have NULL here, so the matches are authoritative.
    has_match_data = (
        db.session.query(Match.id)
        .filter(Match.event_id.in_((keep.id, merge.id)))
        .first()
        is not None
    )
    if has_match_data or keep.medals_only is False or merge.medals_only is False:
        keep.medals_only = False
    elif keep.medals_only is None:
        keep.medals_only = merge.medals_only

    keep_medals = {
        (row.division_id, row.athlete_id): row
        for row in db.session.query(Medal).filter_by(event_id=keep.id).all()
    }
    for medal in db.session.query(Medal).filter_by(event_id=merge.id).all():
        existing = keep_medals.get((medal.division_id, medal.athlete_id))
        if existing is None:
            medal.event_id = keep.id
            keep_medals[(medal.division_id, medal.athlete_id)] = medal
            continue

        if medal.place < existing.place:
            existing.place = medal.place
            existing.happened_at = medal.happened_at
            existing.team_id = medal.team_id
            existing.default_gold = medal.default_gold
            existing.imported_via = medal.imported_via
            existing.imported_at = medal.imported_at
        db.session.delete(medal)

    db.session.query(Match).filter_by(event_id=merge.id).update(
        {Match.event_id: keep.id}, synchronize_session=False
    )
    db.session.delete(merge)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, help="Canonical event UUID")
    parser.add_argument("--merge", required=True, help="Duplicate event UUID")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and apply, then roll back"
    )
    args = parser.parse_args()
    try:
        keep_uuid = _parse_uuid(args.keep, "keep")
        merge_uuid = _parse_uuid(args.merge, "merge")
    except ValueError as exc:
        parser.error(str(exc))

    with app.app_context():
        keep = db.session.get(Event, keep_uuid)
        merge = db.session.get(Event, merge_uuid)
        if not keep or not merge:
            parser.error(
                f"Event with ID {args.keep if not keep else args.merge} not found"
            )
        print(f"Merging {merge.name} ({merge.id}) into {keep.name} ({keep.id})")
        try:
            merge_events(keep, merge)
            if args.dry_run:
                db.session.rollback()
                print("Preflight passed; transaction rolled back.")
            else:
                db.session.commit()
                print("Merge complete.")
        except ValueError as exc:
            db.session.rollback()
            parser.error(str(exc))


if __name__ == "__main__":
    main()
