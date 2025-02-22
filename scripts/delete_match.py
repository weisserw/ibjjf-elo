#!/usr/bin/env python

import sys
import os
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Match, MatchParticipant
from ratings import recompute_all_ratings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete a match and update ratings")
    parser.add_argument("--match-id", type=str, help="Match ID to delete")
    args = parser.parse_args()

    if not args.match_id:
        print("You must enter a match ID.")
        sys.exit(1)

    try:
        match_uuid = uuid.UUID(args.match_id)
    except ValueError:
        print(f"Invalid match ID: {args.match_id}")
        sys.exit(1)

    with app.app_context():
        match = db.session.query(Match).filter_by(id=match_uuid).first()

        if not match:
            print(f"Match with ID {args.match_id} not found.")
            sys.exit(1)

        division = match.division
        gi = division.gi
        gender = division.gender
        happened_at = match.happened_at

        participants = (
            db.session.query(MatchParticipant).filter_by(match_id=match_uuid).all()
        )
        if not participants:
            print(f"No participants found for match ID {args.match_id}.")
            sys.exit(1)

        print(
            f"Deleting match that occurred on {match.happened_at.isoformat()} between "
            f"{match.participants[0].athlete.name} and {match.participants[1].athlete.name}, "
            f"gi = {division.gi}, gender = {division.gender}."
        )

        ids = set([participant.athlete_id for participant in participants])
        db.session.query(MatchParticipant).filter_by(match_id=match_uuid).delete()
        db.session.delete(match)

        for athlete_id in ids:
            print("Recomputing ratings for", athlete_id)
            recompute_all_ratings(
                db,
                gi,
                gender,
                happened_at,
                score=True,
                rerank=False,
                athlete_id=athlete_id,
            )

        db.session.commit()

        print(
            "Match and participants deleted, ratings updated. Don't forget to regenerate ranking board."
        )
