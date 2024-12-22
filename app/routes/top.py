from flask import Blueprint, request, jsonify
from extensions import db
from sqlalchemy.sql import exists
from models import CurrentRating, Athlete, MatchParticipant, Match, Division

top_route = Blueprint('top_route', __name__)

RATINGS_PAGE_SIZE = 30

@top_route.route('/api/top')
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
        subquery = (
            db.session.query(Athlete.id)
            .join(MatchParticipant)
            .join(Match)
            .join(Division)
            .filter(
                Division.weight == weight,
                MatchParticipant.winner == True
            )
            .subquery()
        )

        query = query.filter(
            exists().where(Athlete.id == subquery.c.id)
        )

    query = query.order_by(CurrentRating.rating.desc(), CurrentRating.match_happened_at.desc()).limit(RATINGS_PAGE_SIZE)

    results = query.all()

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
