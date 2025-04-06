#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Match, MatchParticipant, Event, Athlete
from normalize import normalize
from elo import WINNER_NOT_RECORDED

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find match ID by event / athlete")
    parser.add_argument("event", type=str, help="Event name")
    parser.add_argument("athlete", nargs="?", type=str, help="Athlete name (optional)")
    parser.add_argument(
        "athlete2", nargs="?", type=str, help="Second athlete name (optional)"
    )
    parser.add_argument(
        "--unrecorded", action="store_true", help="Only show unrecorded matches"
    )
    args = parser.parse_args()

    with app.app_context():
        event = (
            db.session.query(Event)
            .filter(Event.normalized_name.like(f"%{normalize(args.event)}%"))
            .first()
        )
        if not event:
            print(f"No events found matching {args.event}")
            sys.exit(1)

        found = False

        match_query = (
            db.session.query(Match)
            .join(Event)
            .filter(Event.normalized_name.like(f"%{normalize(args.event)}%"))
        )
        if args.athlete:
            athletes = (
                db.session.query(Athlete.id)
                .filter(Athlete.normalized_name.like(f"%{normalize(args.athlete)}%"))
                .subquery()
            )
            athletes_select = db.session.query(athletes.c.id)
            subquery = db.session.query(MatchParticipant.match_id).filter(
                MatchParticipant.athlete_id.in_(athletes_select)
            )
            match_query = match_query.filter(Match.id.in_(subquery))
        if args.athlete2:
            athletes2 = (
                db.session.query(Athlete.id)
                .filter(Athlete.normalized_name.like(f"%{normalize(args.athlete2)}%"))
                .subquery()
            )
            athletes2_select = db.session.query(athletes2.c.id)
            subquery2 = db.session.query(MatchParticipant.match_id).filter(
                MatchParticipant.athlete_id.in_(athletes2_select)
            )
            match_query = match_query.filter(Match.id.in_(subquery2))
        if args.unrecorded:
            subquery3 = db.session.query(MatchParticipant.match_id).filter(
                MatchParticipant.note.like(f"%{WINNER_NOT_RECORDED}%")
            )
            match_query = match_query.filter(Match.id.in_(subquery3))
        match_query = match_query.order_by(Match.happened_at)

        for match in match_query.all():
            p = match.participants
            age = match.division.age
            gender = match.division.gender
            belt = match.division.belt
            weight = match.division.weight
            print("=================================")
            print(f"{match.event.name}")
            print(f"{age} / {gender} / {belt} / {weight}")
            print(f"{match.happened_at}")
            print(f"{p[0].athlete.name}: {p[0].athlete_id}")
            print("vs")
            print(f"{p[1].athlete.name}: {p[1].athlete_id}")
            print(f"Match ID: {match.id}")
            if WINNER_NOT_RECORDED in [p.note for p in match.participants]:
                print("!!! Winner not recorded")
            found = True
        if not found:
            print("No matches found")
