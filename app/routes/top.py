from flask import Blueprint, request, jsonify
from extensions import db
from sqlalchemy.sql import exists, not_
from models import AthleteRating, Athlete, MatchParticipant, Match, Division
from constants import OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY

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

    query = db.session.query(Athlete.name, AthleteRating.rating).select_from(AthleteRating).join(Athlete).filter(
        AthleteRating.gender == gender,
        AthleteRating.age == age,
        AthleteRating.belt == belt,
        AthleteRating.gi == gi
    )

    if name:
        query = query.filter(Athlete.name.ilike(f'%{name}%'))

    if weight:
        # to qualify for a weight class, the athlete must have either won a match in this division...
        subquery_winner = (
            db.session.query(MatchParticipant.athlete_id)
            .join(Match)
            .join(Division)
            .filter(
                Division.weight == weight,
                MatchParticipant.winner == True
            )
            .subquery()
        )

        # ...or have lost a match in this division and have no winning matches in any other division
        subquery_match = (
            db.session.query(MatchParticipant.athlete_id)
            .join(Match)
            .join(Division)
            .filter(
                Division.weight == weight,
                MatchParticipant.winner == False
            )
            .subquery()
        )
        subquery_other_weights = (
            db.session.query(MatchParticipant.athlete_id)
            .join(Match)
            .join(Division)
            .filter(
                not_(Division.weight.in_([weight, OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY])),
                MatchParticipant.winner == True
            )
            .subquery()
        )

        query = query.filter(
            exists().where(Athlete.id == subquery_winner.c.athlete_id) |
            (
                exists().where(Athlete.id == subquery_match.c.athlete_id) &
                not_(exists().where(Athlete.id == subquery_other_weights.c.athlete_id))
            )
        )

    query = query.order_by(AthleteRating.rating.desc(), AthleteRating.match_happened_at.desc()).limit(RATINGS_PAGE_SIZE)
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
            "name": result.name,
            "rating": rounded_rating
        })
        previous_rating = rounded_rating

    return jsonify(response)
