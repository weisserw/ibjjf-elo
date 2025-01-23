import math
from flask import Blueprint, request, jsonify
from extensions import db
from sqlalchemy import func, or_
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
    changed = request.args.get("changed")
    page = request.args.get("page") or 1

    if not all([gender, age, belt, gi]):
        return jsonify({"error": "Missing mandatory query parameters"}), 400

    gi = gi.lower() == "true"
    changed = changed and changed.lower() == "true"

    query = (
        db.session.query(
            Athlete.name,
            AthleteRating.rating,
            AthleteRating.rank,
            AthleteRating.previous_rating,
            AthleteRating.previous_rank,
        )
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
        for name_part in normalize(name).split():
            query = query.filter(Athlete.normalized_name.like(f"%{name_part}%"))

    if changed:
        query = query.filter(
            or_(
                func.round(AthleteRating.rating)
                != func.round(AthleteRating.previous_rating),
                AthleteRating.previous_rank.is_(None),
            )
        )

    totalCount = query.count()

    query = (
        query.order_by(AthleteRating.rank, AthleteRating.match_happened_at.desc())
        .limit(RATINGS_PAGE_SIZE)
        .offset((int(page) - 1) * RATINGS_PAGE_SIZE)
    )
    results = query.all()

    response = [
        {
            "rank": result.rank,
            "name": result.name,
            "rating": round(result.rating),
            "previous_rating": (
                None
                if result.previous_rating is None
                else round(result.previous_rating)
            ),
            "previous_rank": result.previous_rank,
        }
        for result in results
    ]

    print(totalCount)
    return jsonify(
        {"rows": response, "totalPages": math.ceil(totalCount / RATINGS_PAGE_SIZE)}
    )
