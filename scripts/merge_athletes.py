#!/usr/bin/env python
"""Safely merge one duplicate athlete into a canonical athlete."""

import argparse
import os
import sys
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db
from models import (
    Athlete,
    AthleteMediaCoverage,
    AthleteRating,
    LiveRating,
    ManualPromotions,
    MatchParticipant,
    Medal,
)

PROFILE_FIELDS = (
    "instagram_profile",
    "country",
    "country_note",
    "country_note_pt",
    "personal_name",
    "normalized_personal_name",
    "nickname_translation",
    "bjjheroes_link",
)


def _parse_uuid(value, label):
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Invalid {label} athlete ID: {value}") from None


def validate_merge(keep, merge):
    """Return blocking conflicts. This is deliberately stricter than deletion."""
    conflicts = []
    if keep.id == merge.id:
        conflicts.append("keep and merge IDs are identical")
    if keep.ibjjf_id and merge.ibjjf_id and keep.ibjjf_id != merge.ibjjf_id:
        conflicts.append("athletes have different non-empty IBJJF IDs")
    if merge.profile_image_saved_at and not keep.profile_image_saved_at:
        conflicts.append(
            "merge athlete owns the only profile photo; reverse the pair or move the S3 object"
        )

    keep_matches = {
        row[0]
        for row in db.session.query(MatchParticipant.match_id)
        .filter_by(athlete_id=keep.id)
        .all()
    }
    if keep_matches:
        shared = (
            db.session.query(MatchParticipant.match_id)
            .filter(
                MatchParticipant.athlete_id == merge.id,
                MatchParticipant.match_id.in_(keep_matches),
            )
            .first()
        )
        if shared:
            conflicts.append(f"athletes share match participant rows: {shared[0]}")

    keep_medals = {
        (row.event_id, row.division_id): row
        for row in db.session.query(Medal).filter_by(athlete_id=keep.id).all()
    }
    for row in db.session.query(Medal).filter_by(athlete_id=merge.id).all():
        existing = keep_medals.get((row.event_id, row.division_id))
        if existing is not None and existing.place != row.place:
            conflicts.append(
                "conflicting medal places for event/division "
                f"{row.event_id}/{row.division_id}: {existing.place} vs {row.place}"
            )
    return conflicts


def merge_athletes(keep, merge):
    conflicts = validate_merge(keep, merge)
    if conflicts:
        raise ValueError("; ".join(conflicts))

    if not keep.ibjjf_id:
        keep.ibjjf_id = merge.ibjjf_id
    for field in PROFILE_FIELDS:
        if not getattr(keep, field) and getattr(merge, field):
            setattr(keep, field, getattr(merge, field))
    if not keep.hide_full_name and merge.hide_full_name and keep.personal_name:
        keep.hide_full_name = True

    keep_medals = {
        (row.event_id, row.division_id): row
        for row in db.session.query(Medal).filter_by(athlete_id=keep.id).all()
    }
    for row in db.session.query(Medal).filter_by(athlete_id=merge.id).all():
        if (row.event_id, row.division_id) in keep_medals:
            # validate_merge proved the place agrees, so this is a true duplicate.
            db.session.delete(row)
        else:
            row.athlete_id = keep.id

    for model in (MatchParticipant, ManualPromotions):
        db.session.query(model).filter_by(athlete_id=merge.id).update(
            {model.athlete_id: keep.id}, synchronize_session=False
        )

    existing_urls = {
        row[0]
        for row in db.session.query(AthleteMediaCoverage.url)
        .filter_by(athlete_id=keep.id)
        .all()
    }
    for row in (
        db.session.query(AthleteMediaCoverage).filter_by(athlete_id=merge.id).all()
    ):
        if row.url in existing_urls:
            db.session.delete(row)
        else:
            row.athlete_id = keep.id
            existing_urls.add(row.url)

    # Both rating tables are derived and must be recomputed after a merge.
    for model in (AthleteRating, LiveRating):
        db.session.query(model).filter(
            model.athlete_id.in_((keep.id, merge.id))
        ).delete(synchronize_session=False)
    db.session.delete(merge)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, help="Canonical athlete UUID")
    parser.add_argument("--merge", required=True, help="Duplicate athlete UUID")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate then roll back"
    )
    args = parser.parse_args()
    try:
        keep_uuid = _parse_uuid(args.keep, "keep")
        merge_uuid = _parse_uuid(args.merge, "merge")
    except ValueError as exc:
        parser.error(str(exc))

    with app.app_context():
        keep = db.session.get(Athlete, keep_uuid)
        merge = db.session.get(Athlete, merge_uuid)
        if not keep or not merge:
            parser.error(
                f"Athlete with ID {args.keep if not keep else args.merge} not found"
            )
        print(f"Merging {merge.name} ({merge.id}) into {keep.name} ({keep.id})")
        try:
            merge_athletes(keep, merge)
            if args.dry_run:
                db.session.rollback()
                print("Preflight passed; transaction rolled back.")
            else:
                db.session.commit()
                print("Merge complete, make sure to recompute ratings.")
        except ValueError as exc:
            db.session.rollback()
            parser.error(str(exc))


if __name__ == "__main__":
    main()
