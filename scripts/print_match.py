#!/usr/bin/env python

import sys
import os
import uuid

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Match, MatchParticipant

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print all info for a match by ID")
    parser.add_argument("matchid", type=str, help="Match ID")
    args = parser.parse_args()

    try:
        match_uuid = uuid.UUID(args.matchid)
    except Exception as e:
        print(f"Invalid match ID: {e}")
        sys.exit(1)

    with app.app_context():
        match = db.session.query(Match).filter_by(id=match_uuid).first()
        if not match:
            print(f"Match with ID {args.match_id} not found.")
            sys.exit(1)

        participants = (
            db.session.query(MatchParticipant)
            .filter_by(match_id=match.id)
            .order_by(MatchParticipant.seed)
            .all()
        )
        if len(participants) != 2:
            print(f"Match {args.match_id} does not have exactly two participants.")
            sys.exit(1)

        athlete1 = participants[0]
        athlete2 = participants[1]

        # Print athlete names for clarity
        print(f"athlete1: {athlete1.athlete.name}")
        print(f"athlete2: {athlete2.athlete.name}")

        print(f"--athlete {athlete1.athlete_id}")
        print(f"--athlete {athlete2.athlete_id}")
        print(f"--team {athlete1.team_id}")
        print(f"--team {athlete2.team_id}")
        print(f"--seed {athlete1.seed}")
        print(f"--seed {athlete2.seed}")
        if hasattr(athlete1, "weight_for_open"):
            print(f"--weight-for-open '{athlete1.weight_for_open}'")
        if hasattr(athlete2, "weight_for_open"):
            print(f"--weight-for-open '{athlete2.weight_for_open}'")
        print(f"--division-id {match.division_id}")
        print(f"--event-id {match.event_id}")
        print(f"--date {match.happened_at.strftime('%Y-%m-%dT%H:%M')}")
        # Winner output
        if athlete1.winner and athlete2.winner:
            winner_str = "both"
        elif athlete1.winner:
            winner_str = "1"
        elif athlete2.winner:
            winner_str = "2"
        else:
            winner_str = "neither"
        gi = getattr(match.division, "gi", None)
        gender = getattr(match.division, "gender", None)
        age = getattr(match.division, "age", None)
        belt = getattr(match.division, "belt", None)
        weight = getattr(match.division, "weight", None)
        print(f"--gi {'true' if gi else 'false'}")
        print(f"--gender {gender}")
        print(f"--age '{age}'")
        print(f"--belt {belt}")
        print(f"--weight '{weight}'")
        print(f"--winner {winner_str}")
        if match.match_number is not None:
            print(f"--match-number {match.match_number}")
        if match.match_location is not None:
            print(f"--match-location '{match.match_location}'")
        if match.fight_number is not None:
            print(f"--fight-number {match.fight_number}")
