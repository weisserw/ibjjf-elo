#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from app import db, app
from models import Event, Match, DefaultGold
from normalize import normalize

def delete_event(event):
    db.session.query(Match).filter(Match.event_id == event.id).delete()
    db.session.query(DefaultGold).filter(DefaultGold.event_id == event.id).delete()
    db.session.delete(event)
    db.session.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete an event and its related data")
    parser.add_argument("--id", type=str, help="Event ID")
    parser.add_argument("--name", type=str, help="Event name")
    args = parser.parse_args()

    if not args.id and not args.name:
        print("You must provide either an event ID or name.")
        sys.exit(1)

    with app.app_context():
        if args.id:
            event = db.session.query(Event).filter_by(ibjjf_id=args.id).first()
        else:
            normalized_name = normalize(args.name)
            event = db.session.query(Event).filter_by(normalized_name=normalized_name).first()

        if not event:
            print("Event not found.")
            sys.exit(1)

        confirm = input(f"Are you sure you want to delete the event '{event.name}'? (yes/no): ")
        if confirm.lower() == "yes":
            delete_event(event)
            print("Event and related data deleted.")
        else:
            print("Operation cancelled.")
