import math
from flask import Blueprint, request, jsonify
from datetime import datetime
from sqlalchemy.sql import text
from extensions import db
from constants import (
    MALE, FEMALE,
    ADULT, MASTER_1, MASTER_2, MASTER_3, MASTER_4, MASTER_5, MASTER_6, MASTER_7, JUVENILE_1, JUVENILE_2,
    WHITE, BLUE, PURPLE, BROWN, BLACK,
    ROOSTER, LIGHT_FEATHER, FEATHER, LIGHT, MIDDLE, MEDIUM_HEAVY, HEAVY, SUPER_HEAVY, ULTRA_HEAVY, OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY
)
from models import Athlete, MatchParticipant, Division, Match, Event

matches_route = Blueprint('matches_route', __name__)

MATCH_PAGE_SIZE = 12

@matches_route.route('/api/matches')
def matches():
    gi = request.args.get('gi')
    athlete_name = request.args.get('athlete_name')
    event_name = request.args.get('event_name')
    gender_male = request.args.get('gender_male')
    gender_female = request.args.get('gender_female')
    age_adult = request.args.get('age_adult')
    age_master1 = request.args.get('age_master1')
    age_master2 = request.args.get('age_master2')
    age_master3 = request.args.get('age_master3')
    age_master4 = request.args.get('age_master4')
    age_master5 = request.args.get('age_master5')
    age_master6 = request.args.get('age_master6')
    age_master7 = request.args.get('age_master7')
    age_juvenile1 = request.args.get('age_juvenile1')
    age_juvenile2 = request.args.get('age_juvenile2')
    belt_white = request.args.get('belt_white')
    belt_blue = request.args.get('belt_blue')
    belt_purple = request.args.get('belt_purple')
    belt_brown = request.args.get('belt_brown')
    belt_black = request.args.get('belt_black')
    weight_rooster = request.args.get('weight_rooster')
    weight_light_feather = request.args.get('weight_light_feather')
    weight_feather = request.args.get('weight_feather')
    weight_light = request.args.get('weight_light')
    weight_middle = request.args.get('weight_middle')
    weight_medium_heavy = request.args.get('weight_medium_heavy')
    weight_heavy = request.args.get('weight_heavy')
    weight_super_heavy = request.args.get('weight_super_heavy')
    weight_ultra_heavy = request.args.get('weight_ultra_heavy')
    weight_open_class = request.args.get('weight_open_class')
    date_start = request.args.get('date_start')
    date_end = request.args.get('date_end')
    rating_start = request.args.get('rating_start')
    rating_end = request.args.get('rating_end')
    page = request.args.get('page') or 1

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter"}), 400
    
    if gi:
        gi = gi.lower() == 'true'
    if gender_male:
        gender_male = gender_male.lower() == 'true'
    if gender_female:
        gender_female = gender_female.lower() == 'true'
    if age_adult:
        age_adult = age_adult.lower() == 'true'
    if age_master1:
        age_master1 = age_master1.lower() == 'true'
    if age_master2:
        age_master2 = age_master2.lower() == 'true'
    if age_master3:
        age_master3 = age_master3.lower() == 'true'
    if age_master4:
        age_master4 = age_master4.lower() == 'true'
    if age_master5:
        age_master5 = age_master5.lower() == 'true'
    if age_master6:
        age_master6 = age_master6.lower() == 'true'
    if age_master7:
        age_master7 = age_master7.lower() == 'true'
    if age_juvenile1:
        age_juvenile1 = age_juvenile1.lower() == 'true'
    if age_juvenile2:
        age_juvenile2 = age_juvenile2.lower() == 'true'
    if belt_white:
        belt_white = belt_white.lower() == 'true'
    if belt_blue:
        belt_blue = belt_blue.lower() == 'true'
    if belt_purple:
        belt_purple = belt_purple.lower() == 'true'
    if belt_brown:
        belt_brown = belt_brown.lower() == 'true'
    if belt_black:
        belt_black = belt_black.lower() == 'true'
    if weight_rooster:
        weight_rooster = weight_rooster.lower() == 'true'
    if weight_light_feather:
        weight_light_feather = weight_light_feather.lower() == 'true'
    if weight_feather:
        weight_feather = weight_feather.lower() == 'true'
    if weight_light:
        weight_light = weight_light.lower() == 'true'
    if weight_middle:
        weight_middle = weight_middle.lower() == 'true'
    if weight_medium_heavy:
        weight_medium_heavy = weight_medium_heavy.lower() == 'true'
    if weight_heavy:
        weight_heavy = weight_heavy.lower() == 'true'
    if weight_super_heavy:
        weight_super_heavy = weight_super_heavy.lower() == 'true'
    if weight_ultra_heavy:
        weight_ultra_heavy = weight_ultra_heavy.lower() == 'true'
    if weight_open_class:
        weight_open_class = weight_open_class.lower() == 'true'

    params = {'gi': gi}

    filters = ''

    if athlete_name:
        filters += '''AND EXISTS (
            SELECT 1
            FROM athletes a
            JOIN match_participants mp ON a.id = mp.athlete_id
            WHERE mp.match_id = m.id AND LOWER(a.name) LIKE :athlete_name
        )
        '''
        params['athlete_name'] = f'%{athlete_name.lower()}%'
    if event_name:
        filters += 'AND LOWER(e.name) LIKE :event_name\n'
        params['event_name'] = f'%{event_name.lower()}%'

    genders = []
    if gender_male:
        genders.append(MALE)
    if gender_female:
        genders.append(FEMALE)
    if len(genders):
        filters += 'AND d.gender IN (' + ", ".join(f"'{g}'" for g in genders) + ')\n'

    ages = []
    if age_adult:
        ages.append(ADULT)
    if age_master1:
        ages.append(MASTER_1)
    if age_master2:
        ages.append(MASTER_2)
    if age_master3:
        ages.append(MASTER_3)
    if age_master4:
        ages.append(MASTER_4)
    if age_master5:
        ages.append(MASTER_5)
    if age_master6:
        ages.append(MASTER_6)
    if age_master7:
        ages.append(MASTER_7)
    if age_juvenile1:
        ages.append(JUVENILE_1)
    if age_juvenile2:
        ages.append(JUVENILE_2)
    if len(ages):
        filters += 'AND d.age IN (' + ", ".join(f"'{a}'" for a in ages) + ')\n'

    belts = []
    if belt_white:
        belts.append(WHITE)
    if belt_blue:
        belts.append(BLUE)
    if belt_purple:
        belts.append(PURPLE)
    if belt_brown:
        belts.append(BROWN)
    if belt_black:
        belts.append(BLACK)
    if len(belts):
        filters += 'AND d.belt IN (' + ", ".join(f"'{b}'" for b in belts) + ')\n'

    weights = []
    if weight_rooster:
        weights.append(ROOSTER)
    if weight_light_feather:
        weights.append(LIGHT_FEATHER)
    if weight_feather:
        weights.append(FEATHER)
    if weight_light:
        weights.append(LIGHT)
    if weight_middle:
        weights.append(MIDDLE)
    if weight_medium_heavy:
        weights.append(MEDIUM_HEAVY)
    if weight_heavy:
        weights.append(HEAVY)
    if weight_super_heavy:
        weights.append(SUPER_HEAVY)
    if weight_ultra_heavy:
        weights.append(ULTRA_HEAVY)
    if weight_open_class:
        weights.append(OPEN_CLASS)
        weights.append(OPEN_CLASS_LIGHT)
        weights.append(OPEN_CLASS_HEAVY)
    if len(weights):
        filters += 'AND d.weight IN (' + ", ".join(f"'{w}'" for w in weights) + ')\n'

    if date_start:
        filters += 'AND m.happened_at >= :date_start\n'
        params['date_start'] = datetime.fromisoformat(date_start)
    if date_end:
        filters += 'AND m.happened_at <= :date_end\n'
        params['date_end'] = datetime.fromisoformat(date_end)

    if rating_start is not None:
        rating_start_int = int(rating_start)
        filters += '''AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating >= :rating_start OR mp.end_rating >= :rating_start)
        )
        '''
        params['rating_start'] = rating_start_int
    if rating_end is not None:
        rating_end_int = int(rating_end)
        filters += '''AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating <= :rating_end OR mp.end_rating <= :rating_end)
        )
        '''
        params['rating_end'] = rating_end_int

    sql = f'''
        SELECT m.id, m.happened_at, d.gi, d.gender, d.age, d.belt, d.weight, e.name as event_name,
            mp.winner, mp.start_rating, mp.end_rating, a.name, mp.note
        FROM matches m
        JOIN divisions d ON m.division_id = d.id
        JOIN events e ON m.event_id = e.id
        JOIN match_participants mp ON m.id = mp.match_id
        JOIN athletes a ON mp.athlete_id = a.id
        WHERE d.gi = :gi
        {filters}
    '''

    totalCount = db.session.execute(text(f'''
        SELECT COUNT(*) FROM (
            {sql}
        )'''), params).scalar_one() // 2

    params['limit'] = MATCH_PAGE_SIZE * 2
    params['offset'] = (int(page) - 1) * MATCH_PAGE_SIZE * 2
    results = db.session.execute(text(f'''
        {sql}
        ORDER BY m.happened_at DESC, m.id DESC
        LIMIT :limit OFFSET :offset
        '''), params)

    response = []
    current_match = None
    for result in results:
        row = result._mapping

        if current_match is None or current_match.id != row['id']:
            division = Division(gi=row['gi'], gender=row['gender'], age=row['age'], belt=row['belt'], weight=row['weight'])
            event = Event(name=row['event_name'])

            # sqlite returns a string for datetime fields, but postgres returns a datetime object
            if isinstance(row['happened_at'], str):
                happened_at = datetime.fromisoformat(row['happened_at'])
            else:
                happened_at = row['happened_at']

            current_match = Match(id=row['id'], happened_at=happened_at, division=division, event=event)

        current_match.participants.append(MatchParticipant(
            winner=row['winner'],
            start_rating=row['start_rating'],
            end_rating=row['end_rating'],
            athlete=Athlete(name=row['name']),
            note=row['note']
        ))

        if len(current_match.participants) == 2:
            winner = None
            loser = None
            for participant in current_match.participants:
                if participant.winner:
                    winner = participant
                else:
                    loser = participant

            if winner is None or loser is None:
                winner = current_match.participants[0]
                loser = current_match.participants[1]

            response.append({
                "id": current_match.id,
                "winner": winner.athlete.name,
                "winnerStartRating": round(winner.start_rating),
                "winnerEndRating": round(winner.end_rating),
                "loser": loser.athlete.name,
                "loserStartRating": round(loser.start_rating),
                "loserEndRating": round(loser.end_rating),
                "event": current_match.event.name,
                "division": current_match.division.display_name(),
                "date": current_match.happened_at.isoformat(),
                "notes": loser.note or winner.note
            })

    return jsonify({
        "rows": response,
        "totalPages": math.ceil(totalCount / MATCH_PAGE_SIZE)
    })
