import math
from flask import Blueprint, request, jsonify
from extensions import db
from models import AthleteRating, Athlete
from normalize import normalize

top_route = Blueprint("top_route", __name__)

RATINGS_PAGE_SIZE = 30


@top_route.route("/api/top")
def top():
    gender = request.args.get("gender")
    age = request.args.get("age")
    belt = request.args.get("belt")
    gi = request.args.get("gi")
    weight = request.args.get("weight") or ""
    name = request.args.get("name")
    page = request.args.get("page") or 1

    if not all([gender, age, belt, gi]):
        return jsonify({"error": "Missing mandatory query parameters"}), 400

    gi = gi.lower() == "true"

    query = (
        db.session.query(Athlete.name, AthleteRating.rating, AthleteRating.rank)
        .select_from(AthleteRating)
        .join(Athlete)
        .filter(
            AthleteRating.gender == gender,
            AthleteRating.age == age,
            AthleteRating.belt == belt,
            AthleteRating.gi == gi,
            AthleteRating.weight == weight,
        )
    )

    if name:
        query = query.filter(Athlete.normalized_name.like(f"%{normalize(name)}%"))

    totalCount = query.count()

    query = (
        query.order_by(AthleteRating.rank, AthleteRating.match_happened_at.desc())
        .limit(RATINGS_PAGE_SIZE)
        .offset((int(page) - 1) * RATINGS_PAGE_SIZE)
    )
    results = query.all()

    response = [
        {"rank": result.rank, "name": result.name, "rating": round(result.rating)}
        for result in results
    ]

    print(totalCount)
    return jsonify(
        {"rows": response, "totalPages": math.ceil(totalCount / RATINGS_PAGE_SIZE)}
    )
