#!/usr/bin/env python

import csv
import sys
from elo import EloCompetitor
from datetime import datetime
from app import db, app
from models import Event, Division, Athlete, Team, Match, MatchParticipant

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
    
BELT_DEFAULT_RATING = {
    'BLACK': 2000,
    'BROWN': 1600,
    'PURPLE': 1200,
    'BLUE': 800,
    'WHITE': 400
}

no_match_strings = [
    'Disqualified by no show',
    'Disqualified by overweight'
]

def match_didnt_happen(note1, note2):
    for no_match_string in no_match_strings:
        if no_match_string in note1 or no_match_string in note2:
            return True
    return False

def main(csv_file_path):
    with app.app_context():
        with open(csv_file_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',')
            rows = sorted(reader, key=lambda row: row['Date'])

            if len(rows):
                event = db.session.query(Event).filter_by(ibjjf_id=rows[0]['Tournament ID']).first()
                if event is not None:
                    db.session.query(Match).filter(Match.event_id == event.id).delete()

            for row in rows:
                event = get_or_create(db.session, Event, dict(name=row['Tournament Name']), ibjjf_id=row['Tournament ID'])
                division = get_or_create(db.session, Division, None, gi=row['Gi'] == 'true', gender=row['Gender'], age=row['Age'], belt=row['Belt'], weight=row['Weight'])
                red_athlete = get_or_create(db.session, Athlete, dict(name=row['Red Name']), ibjjf_id=row['Red ID'])
                blue_athlete = get_or_create(db.session, Athlete, dict(name=row['Blue Name']), ibjjf_id=row['Blue ID'])
                red_team = get_or_create(db.session, Team, None, name=row['Red Team'])
                blue_team = get_or_create(db.session, Team, None, name=row['Blue Team'])

                # get the last match played by each athlete in the same division by querying the matches table
                # in reverse date order
                red_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
                    Division.gi == division.gi,
                    Division.gender == division.gender,
                    Division.age == division.age,
                    Division.belt == division.belt,
                    MatchParticipant.athlete_id == red_athlete.id
                ).order_by(Match.happened_at.desc()).first()
                blue_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
                    Division.gi == division.gi,
                    Division.gender == division.gender,
                    Division.age == division.age,
                    Division.belt == division.belt,
                    MatchParticipant.athlete_id == blue_athlete.id
                ).order_by(Match.happened_at.desc()).first()

                # if the athlete has no previous matches, use the default rating for their belt
                if red_last_match is None:
                    red_start_rating = BELT_DEFAULT_RATING[row['Belt']]
                else:
                    red_start_rating = red_last_match.end_rating
                
                if blue_last_match is None:
                    blue_start_rating = BELT_DEFAULT_RATING[row['Belt']]
                else:
                    blue_start_rating = blue_last_match.end_rating

                # calculate the new ratings
                if match_didnt_happen(row['Red Note'], row['Blue Note']):
                    red_end_rating = red_start_rating
                    blue_end_rating = blue_start_rating
                else:
                    red_elo = EloCompetitor(red_start_rating, 64)
                    blue_elo = EloCompetitor(blue_start_rating, 64)

                    if row['Red Winner'] == row['Blue Winner']: # double DQ
                        red_elo.tied(blue_elo)
                    elif row['Red Winner'] == 'true':
                        red_elo.beat(blue_elo)
                    else:
                        blue_elo.beat(red_elo)

                    red_end_rating = red_elo.rating
                    blue_end_rating = blue_elo.rating

                # don't subtract points from winners
                if red_end_rating < red_start_rating and row['Red Winner'] == 'true':
                    red_end_rating = red_start_rating
                if blue_end_rating < blue_start_rating and row['Blue Winner'] == 'true':
                    blue_end_rating = blue_start_rating

                match = Match(
                    happened_at=datetime.strptime(row['Date'], '%Y-%m-%dT%H:%M:%S'),
                    event_id=event.id,
                    division_id=division.id,
                )
                db.session.add(match)
                db.session.flush()

                red_participant = MatchParticipant(
                    match_id=match.id,
                    athlete_id=red_athlete.id,
                    team_id=red_team.id,
                    seed=row['Red Seed'],
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
                    winner=row['Blue Winner'] == 'true',
                    note=row['Blue Note'],
                    start_rating=blue_start_rating,
                    end_rating=blue_end_rating
                )
                db.session.add(blue_participant)
            db.session.commit()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python load_csv.py <csv_file_path>")
        sys.exit(1)
    csv_file_path = sys.argv[1]
    main(csv_file_path)