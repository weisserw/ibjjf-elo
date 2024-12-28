#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))

import csv
import argparse
import traceback
from progress.bar import Bar
from ratings import recompute_all_ratings
from datetime import datetime
from app import db, app
from models import Event, Division, Athlete, Team, Match, MatchParticipant, DefaultGold
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
    try:
        with app.app_context():
            with open(csv_file_path, newline='') as csvfile:
                reader = csv.DictReader(csvfile, delimiter=',')
                rows = sorted(reader, key=lambda row: row['Date'])
                earliest_date = None

                gi = None
                if len(rows):
                    event = db.session.query(Event).filter_by(ibjjf_id=rows[0]['Tournament ID']).first()
                    if event is not None:
                        db.session.query(Match).filter(Match.event_id == event.id).delete()
                        db.session.query(DefaultGold).filter(DefaultGold.event_id == event.id).delete()
                    gi = rows[0]['Gi'] == 'true'

                # default golds dont normally come with timestamps. we allow them to have one in the csv file
                # but in the normal case that they don't, we just use the day of the first timestamp in the file
                default_gold_date = None
                for row in rows:
                    if row['Date']:
                        default_gold_date = datetime.strptime(row['Date'][:10] + 'T00:00:00', '%Y-%m-%dT%H:%M:%S')
                        break

                with Bar(f'Processing {csv_file_path}', max=len(rows)) as bar:
                    for row in rows:
                        bar.next()

                        belt = translate_belt(row['Belt'])
                        weight = translate_weight(row['Weight'])

                        check_gender(row['Gender'])
                        age = translate_age(row['Age'])

                        event = get_or_create(db.session, Event, dict(name=row['Tournament Name']), ibjjf_id=row['Tournament ID'])
                        division = get_or_create(db.session, Division, None, gi=row['Gi'] == 'true', gender=row['Gender'], age=age, belt=belt, weight=weight)
                        red_athlete = get_or_create(db.session, Athlete, dict(name=row['Red Name']), ibjjf_id=row['Red ID'])
                        red_team = get_or_create(db.session, Team, None, name=row['Red Team'])

                        if row['Blue ID'] == 'DEFAULT_GOLD':
                            default_happened_at = default_gold_date
                            if row['Date']:
                                default_happened_at = datetime.strptime(row['Date'], '%Y-%m-%dT%H:%M:%S')
                            if default_happened_at is None:
                                continue
                            default_gold = DefaultGold(
                                happened_at=default_happened_at,
                                event_id=event.id,
                                division_id=division.id,
                                athlete_id=red_athlete.id,
                                team_id=red_team.id
                            )
                            db.session.add(default_gold)
                            db.session.flush()
                            continue

                        blue_team = get_or_create(db.session, Team, None, name=row['Blue Team'])
                        blue_athlete = get_or_create(db.session, Athlete, dict(name=row['Blue Name']), ibjjf_id=row['Blue ID'])

                        if earliest_date is None or row['Date'] < earliest_date:
                            earliest_date = row['Date']

                        match = Match(
                            happened_at=datetime.strptime(row['Date'], '%Y-%m-%dT%H:%M:%S'),
                            event_id=event.id,
                            division_id=division.id,
                            rated=False
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
                            start_rating=0,
                            end_rating=0
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
                            start_rating=0,
                            end_rating=0
                        )
                        db.session.add(blue_participant)

                if gi is not None:
                    recompute_all_ratings(db, gi, start_date=datetime.strptime(earliest_date, '%Y-%m-%dT%H:%M:%S'))

                db.session.commit()
    except Exception as e:
        print(f"Error processing {csv_file_path}: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load match data from CSV files')
    parser.add_argument('csv_files', metavar='csv_file', type=str, nargs='+', help='CSV file paths')
    args = parser.parse_args()

    for csv_file_path in args.csv_files:
        process_file(csv_file_path)