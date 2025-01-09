from flask import Blueprint, request, jsonify
from extensions import db
from models import Athlete
from normalize import normalize

athletes_route = Blueprint("athletes_route", __name__)

MAX_RESULTS = 50


@athletes_route.route("/api/athletes")
def athletes():
    search = normalize(request.args.get("search", ""))

    query = (
        db.session.query(Athlete.name)
        .filter(Athlete.normalized_name.like(f"{search}%"))
        .order_by(Athlete.name)
        .limit(MAX_RESULTS)
    )
    results = query.all()

    unique_names = set(result.name for result in results)

    if len(results) < MAX_RESULTS:
        remaining_count = MAX_RESULTS - len(results)
        additional_query = (
            db.session.query(Athlete.name)
            .filter(Athlete.normalized_name.like(f"%{search}%"))
            .order_by(Athlete.name)
            .limit(remaining_count)
        )
        additional_results = additional_query.all()
        for result in additional_results:
            if result.name not in unique_names:
                results.append(result)
                unique_names.add(result.name)

    response = [result.name for result in results]

    return jsonify(response)
