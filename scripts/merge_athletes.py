#!/usr/bin/env python

import sys
import os
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Athlete, DefaultGold, MatchParticipant, AthleteRating

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge two athletes")
    parser.add_argument("--keep", type=str, help="Athlete ID to keep")
    parser.add_argument("--merge", type=str, help="Athlete ID to merge")
    args = parser.parse_args()

    if not args.keep and not args.merge:
        print("You must enter two athlete IDs.")
        sys.exit(1)

    try:
        keep_uuid = uuid.UUID(args.keep)
    except ValueError:
        print(f"Invalid athlete ID: {args.keep}")
        sys.exit(1)
    try:
        merge_uuid = uuid.UUID(args.merge)
    except ValueError:
        print(f"Invalid athlete ID: {args.merge}")
        sys.exit(1)

    with app.app_context():
        keep = db.session.query(Athlete).filter_by(id=keep_uuid).first()

        if not keep:
            print(f"Athlete with ID {args.keep} not found.")
            sys.exit(1)

        merge = db.session.query(Athlete).filter_by(id=merge_uuid).first()

        if not merge:
            print(f"Athlete with ID {args.merge} not found.")
            sys.exit(1)

        print(f"Merging {merge.name} into {keep.name}")
        for default_gold in (
            db.session.query(DefaultGold).filter_by(athlete_id=merge_uuid).all()
        ):
            default_gold.athlete_id = keep_uuid
        for match_participant in (
            db.session.query(MatchParticipant).filter_by(athlete_id=merge_uuid).all()
        ):
            match_participant.athlete_id = keep_uuid
        db.session.query(AthleteRating).filter_by(athlete_id=merge_uuid).delete()
        db.session.delete(merge)
        db.session.commit()

        print("Merge complete, make sure to recompute ratings.")
