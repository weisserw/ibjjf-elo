import os
from flask import Flask, send_from_directory, request, jsonify
from extensions import db, migrate
from models import CurrentRating, Athlete, MatchParticipant, Division, Match

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

    query = db.session.query(Match).join(Division).join(MatchParticipant).filter(
        Division.gi == gi
    )

    totalCount = query.count() // 2

    query = query.order_by(Match.happened_at.desc()).limit(MATCH_PAGE_SIZE * 2).offset((int(page) - 1) * MATCH_PAGE_SIZE * 2)

    response = []
    for result in query.all():
        winner = None
        loser = None
        for participant in result.participants:
            if participant.winner:
                winner = participant
            else:
                loser = participant
        if winner is None or loser is None:
            continue
        response.append({
            "id": result.id,
            "winner": winner.athlete.name,
            "winnerStartRating": round(winner.start_rating),
            "winnerEndRating": round(winner.end_rating),
            "loser": loser.athlete.name,
            "loserStartRating": round(loser.start_rating),
            "loserEndRating": round(loser.end_rating),
            "event": result.event.name,
            "division": result.division.display_name(),
            "date": result.happened_at.isoformat(),
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
