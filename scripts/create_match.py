#!/usr/bin/env python

import sys
import os
import uuid
import csv
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Match, MatchParticipant, Medal
from ratings import recompute_all_ratings
from photos import get_s3_client, bucket_name


def upload_created_matches_file(s3_client, file_path, file_name):
    try:
        s3_client.upload_file(file_path, bucket_name, file_name)
        print(f"{file_path}: File uploaded to S3.")
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Credentials error: {e}")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create a new match and update ratings"
    )
    parser.add_argument(
        "--athlete",
        type=str,
        required=True,
        action="append",
        help="Athlete ID (specify twice)",
    )
    parser.add_argument(
        "--team",
        type=str,
        required=True,
        action="append",
        help="Team ID (specify twice)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        action="append",
        help="Seed for each participant (specify twice)",
    )
    parser.add_argument(
        "--weight-for-open",
        type=str,
        required=False,
        action="append",
        help="Weight for open for each participant (specify twice, or leave blank)",
    )
    parser.add_argument(
        "--medal",
        type=str,
        required=False,
        action="append",
        help="Medal for each participant (none, 1, 2, or 3; specify zero, one, or two times)",
    )
    parser.add_argument("--event-id", type=str, required=True, help="Event ID")
    parser.add_argument(
        "--date", type=str, required=True, help="Date (YYYY-MM-DDTHH:MM)"
    )
    parser.add_argument(
        "--gi", type=str, required=True, help="true for Gi, false for No-Gi"
    )
    parser.add_argument("--gender", type=str, required=True, help="Gender")
    parser.add_argument("--age", type=str, required=True, help="Age")
    parser.add_argument("--belt", type=str, required=True, help="Belt")
    parser.add_argument("--weight", type=str, required=True, help="Weight")
    parser.add_argument(
        "--winner",
        type=str,
        required=True,
        help="Winner: 1, 2, or both (for double DQ)",
    )
    parser.add_argument("--match-number", type=int, required=True, help="Match number")
    parser.add_argument(
        "--match-location", type=str, default=None, help="Match location"
    )
    parser.add_argument("--fight-number", type=int, default=None, help="Fight number")
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="If set, do not upload created matches file to S3",
    )
    args = parser.parse_args()

    # Convert gi argument to boolean
    if args.gi.lower() == "true":
        gi_bool = True
    elif args.gi.lower() == "false":
        gi_bool = False
    else:
        print("--gi must be 'true' or 'false'")
        sys.exit(1)

    try:
        if len(args.athlete) != 2 or len(args.team) != 2 or len(args.seed) != 2:
            raise ValueError(
                "You must specify exactly two --athlete, two --team, and two --seed arguments."
            )
        if args.weight_for_open is not None and len(args.weight_for_open) not in [0, 2]:
            raise ValueError(
                "If specified, --weight-for-open must be given zero or two times."
            )
        athlete_uuids = [uuid.UUID(a) for a in args.athlete]
        team_uuids = [uuid.UUID(t) for t in args.team]
        # Find division by gi, gender, belt, age, weight
        with app.app_context():
            division = (
                db.session.query(type("Division", (db.Model,), {}))
                .filter_by(
                    gi=gi_bool,
                    gender=args.gender,
                    belt=args.belt,
                    age=args.age,
                    weight=args.weight,
                )
                .first()
            )
            if not division:
                print(
                    "No division found for the given gi, gender, belt, age, and weight."
                )
                sys.exit(1)
            division_uuid = division.id
        event_uuid = uuid.UUID(args.event_id)
        winner_arg = args.winner.strip().lower()
        if winner_arg not in ["1", "2", "both", "neither"]:
            raise ValueError("--winner must be '1', '2', 'both', or 'neither'")
        happened_at = datetime.strptime(args.date, "%Y-%m-%dT%H:%M")
        seeds = args.seed
        weights_for_open = (
            args.weight_for_open
            if args.weight_for_open is not None and len(args.weight_for_open) == 2
            else [None, None]
        )
    except Exception as e:
        print(f"Invalid argument: {e}")
        sys.exit(1)

    s3_client = get_s3_client()

    created_matches_file = "created_matches.csv"
    file_path = os.path.join(os.getcwd(), created_matches_file)

    with app.app_context():
        match = Match(
            happened_at=happened_at,
            event_id=event_uuid,
            division_id=division_uuid,
            rated=True,
            rated_winner_only=False,
            match_number=args.match_number,
            match_location=args.match_location,
            fight_number=args.fight_number,
        )
        db.session.add(match)
        db.session.flush()  # get match.id

        default_rating = 1500.0
        default_count = 0

        winner1 = winner_arg == "1" or winner_arg == "both"
        winner2 = winner_arg == "2" or winner_arg == "both"
        participant1 = MatchParticipant(
            match_id=match.id,
            athlete_id=athlete_uuids[0],
            team_id=team_uuids[0],
            seed=seeds[0],
            red=True,
            winner=winner1,
            note="",
            rating_note="",
            start_rating=default_rating,
            end_rating=default_rating,
            weight_for_open=weights_for_open[0],
            start_match_count=default_count,
            end_match_count=default_count,
        )
        participant2 = MatchParticipant(
            match_id=match.id,
            athlete_id=athlete_uuids[1],
            team_id=team_uuids[1],
            seed=seeds[1],
            red=False,
            winner=winner2,
            note="",
            rating_note="",
            start_rating=default_rating,
            end_rating=default_rating,
            weight_for_open=weights_for_open[1],
            start_match_count=default_count,
            end_match_count=default_count,
        )
        db.session.add(participant1)
        db.session.add(participant2)
        db.session.commit()

        # Handle medals
        medals = args.medal if args.medal is not None else []
        for idx, medal_val in enumerate(medals):
            if medal_val and medal_val.lower() != "none":
                try:
                    place = int(medal_val)
                    if place not in [1, 2, 3]:
                        raise ValueError()
                except Exception:
                    print(
                        f"Invalid medal value: {medal_val}. Must be 1, 2, 3, or 'none'."
                    )
                    sys.exit(1)
                athlete_id = athlete_uuids[idx]
                team_id = team_uuids[idx]
                medal = Medal(
                    happened_at=happened_at,
                    event_id=event_uuid,
                    division_id=division_uuid,
                    athlete_id=athlete_id,
                    team_id=team_id,
                    place=place,
                    default_gold=False,
                )
                db.session.add(medal)
        db.session.commit()

        for athlete_id in athlete_uuids:
            print("Recomputing ratings for", athlete_id)
            recompute_all_ratings(
                db,
                gi_bool,
                start_date=happened_at,
                rerank=False,
                athlete_id=str(athlete_id),
            )

        event_name = match.event.name
        athlete1_name = participant1.athlete.name
        athlete2_name = participant2.athlete.name
        with open(file_path, "a", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    event_name,
                    args.gender,
                    args.age,
                    args.belt,
                    args.weight,
                    athlete1_name,
                    athlete2_name,
                    happened_at.strftime("%Y-%m-%dT%H:%M"),
                    args.match_number,
                    args.match_location,
                    args.fight_number,
                ]
            )

        if not args.no_upload:
            upload_created_matches_file(s3_client, file_path, created_matches_file)

        db.session.commit()

        print(
            "Match and participants created. Don't forget to regenerate ranking board."
        )
