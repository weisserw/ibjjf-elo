import os
from datetime import datetime
from sqlalchemy.sql import text
from flask import Flask, send_from_directory, request, jsonify
from extensions import db, migrate
from models import CurrentRating, Athlete, MatchParticipant, Division, Match, Event

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/')
if os.getenv('RENDER'):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

db.init_app(app)
migrate.init_app(app, db)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

RATINGS_PAGE_SIZE = 30
MATCH_PAGE_SIZE = 12

@app.route('/api/matches')
def matches():
    gi = request.args.get('gi')
    page = request.args.get('page') or 1

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter"}), 400
    
    gi = gi.lower() == 'true'

    sql = '''
        SELECT m.id, m.happened_at, d.gi, d.gender, d.age, d.belt, d.weight, e.name as event_name,
            mp.winner, mp.start_rating, mp.end_rating, a.name, mp.note
        FROM matches m
        JOIN divisions d ON m.division_id = d.id
        JOIN events e ON m.event_id = e.id
        JOIN match_participants mp ON m.id = mp.match_id
        JOIN athletes a ON mp.athlete_id = a.id
        WHERE d.gi = :gi
        AND (
            (SELECT COUNT(*)
            FROM match_participants
            WHERE match_id = m.id AND winner = true) = 1
            AND
            (SELECT COUNT(*)
            FROM match_participants
            WHERE match_id = m.id AND winner = false) = 1
        )
    '''

    totalCount = db.session.execute(text(f'''
        SELECT COUNT(*) FROM (
            {sql}
        )'''), {'gi': gi}).scalar_one() // 2

    results = db.session.execute(text(f'''
        {sql}
        ORDER BY m.happened_at DESC, m.id DESC
        LIMIT :limit OFFSET :offset
        '''), {'gi': gi, 'limit': MATCH_PAGE_SIZE * 2, 'offset': (int(page) - 1) * MATCH_PAGE_SIZE * 2})

    response = []
    current_match = None
    for result in results:
        row = result._mapping

        if current_match is None or current_match.id != row['id']:
            division = Division(gi=row['gi'], gender=row['gender'], age=row['age'], belt=row['belt'], weight=row['weight'])
            event = Event(name=row['event_name'])

            happened_at = datetime.fromisoformat(row['happened_at'])

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
        "totalPages": totalCount // MATCH_PAGE_SIZE + 1
    })

@app.route('/api/top')
def top():
    gender = request.args.get('gender')
    age = request.args.get('age')
    belt = request.args.get('belt')
    gi = request.args.get('gi')
    weight = request.args.get('weight')
    name = request.args.get('name')

    if not all([gender, age, belt, gi]):
        return jsonify({"error": "Missing mandatory query parameters"}), 400
    
    gi = gi.lower() == 'true'

    query = db.session.query(CurrentRating).join(Athlete).filter(
        CurrentRating.gender == gender,
        CurrentRating.age == age,
        CurrentRating.belt == belt,
        CurrentRating.gi == gi
    )

    if name:
        query = query.filter(Athlete.name.ilike(f'%{name}%'))

    if weight:
        query = query.join(MatchParticipant).join(Match).join(Division).filter(
            Division.weight == weight,
            MatchParticipant.winner == True
        )

    results = query.order_by(CurrentRating.rating.desc(), CurrentRating.match_happened_at.desc()).limit(RATINGS_PAGE_SIZE).all()

    response = []
    previous_rating = None
    rank = 0
    for index, result in enumerate(results):
        rounded_rating = round(result.rating)
        if rounded_rating != previous_rating:
            rank = index + 1
        response.append({
            "rank": rank,
            "name": result.athlete.name,
            "rating": rounded_rating
        })
        previous_rating = rounded_rating

    return jsonify(response)

if __name__ == '__main__':
    app.run()
