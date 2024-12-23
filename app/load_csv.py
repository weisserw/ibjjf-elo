#!/usr/bin/env python

import csv
import argparse
from elo import compute_ratings
from datetime import datetime
from app import db, app
from models import Event, Division, Athlete, Team, Match, MatchParticipant
from current import generate_current_ratings
from constants import translate_belt, translate_weight, check_gender, translate_age

def get_or_create(session, model, update=None, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        if update:
            for key, value in update.items():
                setattr(instance, key, value)
        return instance
    else:
        combined = dict(update or {}, **kwargs)

        instance = model(**combined)
        session.add(instance)
        session.flush()
        return instance

def process_file(csv_file_path):
    with app.app_context():
        with open(csv_file_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',')
            rows = sorted(reader, key=lambda row: row['Date'])

            if len(rows):
                event = db.session.query(Event).filter_by(ibjjf_id=rows[0]['Tournament ID']).first()
                if event is not None:
                    db.session.query(Match).filter(Match.event_id == event.id).delete()

            for row in rows:
                belt = translate_belt(row['Belt'])
                weight = translate_weight(row['Weight'])

                check_gender(row['Gender'])
                translate_age(row['Age'])

                event = get_or_create(db.session, Event, dict(name=row['Tournament Name']), ibjjf_id=row['Tournament ID'])
                division = get_or_create(db.session, Division, None, gi=row['Gi'] == 'true', gender=row['Gender'], age=row['Age'], belt=belt, weight=weight)
                red_athlete = get_or_create(db.session, Athlete, dict(name=row['Red Name']), ibjjf_id=row['Red ID'])
                blue_athlete = get_or_create(db.session, Athlete, dict(name=row['Blue Name']), ibjjf_id=row['Blue ID'])
                red_team = get_or_create(db.session, Team, None, name=row['Red Team'])
                blue_team = get_or_create(db.session, Team, None, name=row['Blue Team'])

                rated, red_start_rating, red_end_rating, blue_start_rating, blue_end_rating = compute_ratings(
                    db,
                    division,
                    red_athlete.id,
                    row['Red Winner'] == 'true',
                    row['Red Note'],
                    blue_athlete.id,
                    row['Blue Winner'] == 'true',
                    row['Blue Note']
                )

                match = Match(
                    happened_at=datetime.strptime(row['Date'], '%Y-%m-%dT%H:%M:%S'),
                    event_id=event.id,
                    division_id=division.id,
                    rated=rated
                )
                db.session.add(match)
                db.session.flush()

                red_participant = MatchParticipant(
                    match_id=match.id,
                    athlete_id=red_athlete.id,
                    team_id=red_team.id,
                    seed=row['Red Seed'],
                    red=True,
                    winner=row['Red Winner'] == 'true',
                    note=row['Red Note'],
                    start_rating=red_start_rating,
                    end_rating=red_end_rating
                )
                db.session.add(red_participant)
                blue_participant = MatchParticipant(
                    match_id=match.id,
                    athlete_id=blue_athlete.id,
                    team_id=blue_team.id,
                    seed=row['Blue Seed'],
                    red=False,
                    winner=row['Blue Winner'] == 'true',
                    note=row['Blue Note'],
                    start_rating=blue_start_rating,
                    end_rating=blue_end_rating
                )
                db.session.add(blue_participant)
            db.session.commit()

            generate_current_ratings(db)
            db.session.commit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load match data from CSV files')
    parser.add_argument('csv_files', metavar='csv_file', type=str, nargs='+', help='CSV file paths')
    args = parser.parse_args()

    for csv_file_path in args.csv_files:
        process_file(csv_file_path)