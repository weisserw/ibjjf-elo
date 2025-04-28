#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import csv
import argparse
import traceback
from progress_bar import Bar
from ratings import recompute_all_ratings
from datetime import datetime
from app import db, app
from models import Event, Division, Athlete, Team, Match, MatchParticipant, Medal
from constants import (
    translate_belt,
    translate_weight,
    translate_gender,
    translate_age,
)
from normalize import normalize
from elo import match_didnt_happen


def get_event(session, ibjjf_id, name):
    normalized_name = normalize(name)

    if not ibjjf_id:
        return session.query(Event).filter_by(normalized_name=normalized_name).first()

    instance = session.query(Event).filter_by(ibjjf_id=ibjjf_id).first()
    if instance:
        if name and (
            name != instance.name or normalized_name != instance.normalized_name
        ):
            instance.name = name
            instance.normalized_name = normalized_name
            session.flush()
        return instance
    instance = session.query(Event).filter_by(name=name).first()
    if instance:
        instance.ibjjf_id = ibjjf_id
        session.flush()
        return instance
    return None


def get_or_create_event_or_athlete(session, model, ibjjf_id, name, do_update=True):
    normalized_name = normalize(name)

    if not ibjjf_id:
        instance = (
            session.query(model).filter_by(normalized_name=normalized_name).first()
        )
        if instance:
            return instance
        else:
            instance = model(ibjjf_id=None, name=name, normalized_name=normalized_name)
            session.add(instance)
            session.flush()
            return instance
    else:
        instance = session.query(model).filter_by(ibjjf_id=ibjjf_id).first()
        if instance:
            if (
                do_update
                and name
                and (
                    name != instance.name or normalized_name != instance.normalized_name
                )
            ):
                instance.name = name
                instance.normalized_name = normalized_name
                session.flush()
            return instance
        else:
            instance = (
                session.query(model).filter_by(normalized_name=normalized_name).first()
            )
            if instance and instance.ibjjf_id is None:
                instance.ibjjf_id = ibjjf_id
                instance.name = name
                instance.normalized_name = normalized_name
                session.flush()
                return instance
            else:
                instance = model(ibjjf_id=ibjjf_id, name=name, normalized_name=normalized_name)
                session.add(instance)
                session.flush()
                return instance


def get_or_create_team(session, name):
    normalized_name = normalize(name)
    instance = session.query(Team).filter_by(normalized_name=normalized_name).first()
    if instance:
        return instance
    else:
        instance = Team(name=name, normalized_name=normalized_name)
        session.add(instance)
        session.flush()
        return instance


def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.flush()
        return instance


def create_or_update_medal(session, place, event, division, match, athlete, team):
    existing_medal = (
        session.query(Medal)
        .filter(
            Medal.event_id == event.id,
            Medal.division_id == division.id,
            Medal.athlete_id == athlete.id,
        )
        .first()
    )

    if existing_medal and existing_medal.happened_at < match.happened_at:
        existing_medal.happened_at = match.happened_at
    else:
        medal = Medal(
            happened_at=match.happened_at,
            event_id=event.id,
            division_id=division.id,
            athlete_id=athlete.id,
            team_id=team.id,
            place=place,
            default_gold=False,
        )
        session.add(medal)

    session.flush()


def process_file(csv_file_path: str, no_scores: bool):
    try:
        with app.app_context():
            with open(csv_file_path, newline="") as csvfile:
                reader = csv.DictReader(csvfile, delimiter=",")

                rows_by_tournament = {}
                count = 0
                for row in reader:
                    unique_id = f'{row["Tournament ID"]}:{row["Tournament Name"]}'
                    if unique_id not in rows_by_tournament:
                        rows_by_tournament[unique_id] = []
                    rows_by_tournament[unique_id].append(row)
                    count += 1

                earliest_date = None
                has_gi = False
                has_nogi = False

                with Bar(
                    f"Processing {csv_file_path}",
                    max=count,
                    check_tty=False,
                    no_tty=True,
                ) as bar:
                    for rows in rows_by_tournament.values():
                        rows = sorted(rows, key=lambda row: (row["Date"]))

                        tournament_id = rows[0]["Tournament ID"]
                        tournament_name = rows[0]["Tournament Name"]

                        partial_tournament = (
                            rows[0].get("Partial Tournament", "false").lower() == "true"
                        )

                        if not partial_tournament:
                            existing_event = get_event(
                                db.session, tournament_id, tournament_name
                            )
                            if existing_event is not None:
                                db.session.query(Match).filter(
                                    Match.event_id == existing_event.id
                                ).delete()
                                db.session.query(Medal).filter(
                                    Medal.event_id == existing_event.id
                                ).delete()

                        if rows[0]["Gi"].lower() == "true":
                            has_gi = True
                        else:
                            has_nogi = True

                        # default golds dont normally come with timestamps. we allow them to have one in the csv file
                        # but in the normal case that they don't, we just use the day of the first timestamp in the file
                        default_gold_date = None
                        for row in rows:
                            if row["Date"]:
                                default_gold_date = datetime.strptime(
                                    row["Date"][:10] + "T00:00:00", "%Y-%m-%dT%H:%M:%S"
                                )
                                break

                        for row in rows:
                            bar.next()

                            try:
                                age = translate_age(row["Age"])
                            except ValueError:
                                continue  # kids ages raise ValueError

                            belt = translate_belt(row["Belt"])
                            weight = translate_weight(row["Weight"])
                            gender = translate_gender(row["Gender"])

                            red_winner = row["Red Winner"].lower() == "true"
                            blue_winner = row["Blue Winner"].lower() == "true"
                            if red_winner and blue_winner:
                                continue  # match hasn't finished, don't import

                            red_medal = None
                            blue_medal = None

                            try:
                                if row.get("Red Medal", ""):
                                    red_medal = int(row["Red Medal"])
                            except ValueError:
                                print("Invalid red medal value:", row["Red Medal"])
                            try:
                                if row.get("Blue Medal", ""):
                                    blue_medal = int(row["Blue Medal"])
                            except ValueError:
                                print("Invalid blue medal value:", row["Blue Medal"])

                            event = get_or_create_event_or_athlete(
                                db.session,
                                Event,
                                row["Tournament ID"],
                                row["Tournament Name"],
                                do_update=not partial_tournament,
                            )
                            division = get_or_create(
                                db.session,
                                Division,
                                gi=row["Gi"].lower() == "true",
                                gender=gender,
                                age=age,
                                belt=belt,
                                weight=weight,
                            )
                            red_athlete = get_or_create_event_or_athlete(
                                db.session,
                                Athlete,
                                row["Red ID"],
                                row["Red Name"],
                            )
                            red_team = get_or_create_team(db.session, row["Red Team"])

                            if row["Blue ID"] == "DEFAULT_GOLD":
                                default_happened_at = default_gold_date
                                if row["Date"]:
                                    default_happened_at = datetime.strptime(
                                        row["Date"], "%Y-%m-%dT%H:%M:%S"
                                    )
                                if default_happened_at is None:
                                    continue
                                default_gold = Medal(
                                    happened_at=default_happened_at,
                                    event_id=event.id,
                                    division_id=division.id,
                                    athlete_id=red_athlete.id,
                                    team_id=red_team.id,
                                    place=1,
                                    default_gold=True,
                                )
                                db.session.add(default_gold)
                                db.session.flush()
                                continue

                            blue_team = get_or_create_team(db.session, row["Blue Team"])
                            blue_athlete = get_or_create_event_or_athlete(
                                db.session,
                                Athlete,
                                row["Blue ID"],
                                row["Blue Name"],
                            )

                            if earliest_date is None or row["Date"] < earliest_date:
                                earliest_date = row["Date"]

                            happened = (
                                not match_didnt_happen(
                                    row["Red Note"], row["Blue Note"]
                                ),
                            )

                            rated_winner_only = (
                                row.get("Rate Winner Only", "false").lower() == "true"
                            )

                            match = Match(
                                happened_at=datetime.strptime(
                                    row["Date"], "%Y-%m-%dT%H:%M:%S"
                                ),
                                event_id=event.id,
                                division_id=division.id,
                                rated=happened and not (red_winner and blue_winner),
                                rated_winner_only=rated_winner_only,
                            )
                            db.session.add(match)
                            db.session.flush()

                            if red_medal is not None:
                                create_or_update_medal(
                                    db.session,
                                    red_medal,
                                    event,
                                    division,
                                    match,
                                    red_athlete,
                                    red_team,
                                )
                            if blue_medal is not None:
                                create_or_update_medal(
                                    db.session,
                                    blue_medal,
                                    event,
                                    division,
                                    match,
                                    blue_athlete,
                                    blue_team,
                                )

                            red_participant = MatchParticipant(
                                match_id=match.id,
                                athlete_id=red_athlete.id,
                                team_id=red_team.id,
                                seed=row["Red Seed"],
                                red=True,
                                winner=red_winner,
                                note=row["Red Note"],
                                start_rating=0,
                                end_rating=0,
                                start_match_count=0,
                                end_match_count=0,
                            )
                            db.session.add(red_participant)
                            blue_participant = MatchParticipant(
                                match_id=match.id,
                                athlete_id=blue_athlete.id,
                                team_id=blue_team.id,
                                seed=row["Blue Seed"],
                                red=False,
                                winner=blue_winner,
                                note=row["Blue Note"],
                                start_rating=0,
                                end_rating=0,
                                start_match_count=0,
                                end_match_count=0,
                            )
                            db.session.add(blue_participant)

                if has_gi and not no_scores:
                    recompute_all_ratings(
                        db,
                        True,
                        start_date=datetime.strptime(
                            earliest_date, "%Y-%m-%dT%H:%M:%S"
                        ),
                        score=True,
                        rerank=not has_nogi,
                        rerankgi=True,
                        reranknogi=False,
                    )
                if has_nogi and not no_scores:
                    recompute_all_ratings(
                        db,
                        False,
                        start_date=datetime.strptime(
                            earliest_date, "%Y-%m-%dT%H:%M:%S"
                        ),
                        score=True,
                        rerank=True,
                        rerankgi=has_gi,
                        reranknogi=True,
                    )

                db.session.commit()
    except Exception as e:
        print(f"Error processing {csv_file_path}: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load match data from CSV files")
    parser.add_argument(
        "csv_files", metavar="csv_file", type=str, nargs="+", help="CSV file paths"
    )
    parser.add_argument(
        "--no-scores",
        action="store_true",
        help="Do not recompute scores after loading",
    )
    args = parser.parse_args()

    for csv_file_path in args.csv_files:
        process_file(csv_file_path, args.no_scores)
