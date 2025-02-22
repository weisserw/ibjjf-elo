#!/usr/bin/env python

import sys
import os
import uuid
import csv
import json
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Match, MatchParticipant
from ratings import recompute_all_ratings


def get_s3_client():
    aws_creds = json.loads(os.getenv("AWS_CREDS"))
    return boto3.client(
        "s3",
        aws_access_key_id=aws_creds["aws_access_key_id"],
        aws_secret_access_key=aws_creds["aws_secret_access_key"],
        region_name=aws_creds.get("region"),
    )


def download_deleted_matches_file(s3_client, bucket_name, file_name):
    file_path = os.path.join(os.getcwd(), file_name)
    try:
        s3_client.download_file(bucket_name, file_name, file_path)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print(f"{file_name} not found in bucket. A new file will be created.")
        else:
            print(f"An error occurred: {e}")
            raise
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Credentials error: {e}")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise
    return file_path


def upload_deleted_matches_file(s3_client, file_path, bucket_name, file_name):
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

    s3_client = get_s3_client()
    bucket_name = os.getenv("S3_BUCKET")
    if not bucket_name:
        raise ValueError("S3_BUCKET environment variable not set")

    deleted_matches_file = "deleted_matches.csv"
    file_path = download_deleted_matches_file(
        s3_client, bucket_name, deleted_matches_file
    )

    with app.app_context():
        match = db.session.query(Match).filter_by(id=match_uuid).first()

        if not match:
            print(f"Match with ID {args.match_id} not found.")
            sys.exit(1)

        division = match.division
        gi = division.gi
        gender = division.gender
        age = division.age
        weight = division.weight
        belt = division.belt
        happened_at = match.happened_at

        participants = (
            db.session.query(MatchParticipant).filter_by(match_id=match_uuid).all()
        )
        if not participants:
            print(f"No participants found for match ID {args.match_id}.")
            sys.exit(1)

        athlete_1_name = match.participants[0].athlete.name
        athlete_2_name = match.participants[1].athlete.name

        print(
            f"Deleting match that occurred on {match.happened_at.isoformat()} between "
            f"{athlete_1_name} and {athlete_2_name}, "
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

        with open(file_path, "a", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    match.event.ibjjf_id,
                    match.event.name,
                    athlete_1_name,
                    athlete_2_name,
                    "Gi" if gi else "No-Gi",
                    f"{age} / {gender} / {belt} / {weight}",
                    happened_at.isoformat(),
                ]
            )

        upload_deleted_matches_file(
            s3_client, file_path, bucket_name, deleted_matches_file
        )

        db.session.commit()

        print(
            "Match and participants deleted, ratings updated. Don't forget to regenerate ranking board."
        )
