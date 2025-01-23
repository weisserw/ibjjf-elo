from flask import Blueprint, request, jsonify
from sqlalchemy.sql import exists
from extensions import db
from models import Event, Match, Division
from normalize import normalize

events_route = Blueprint("events_route", __name__)

MAX_RESULTS = 50


@events_route.route("/api/events")
def events():
    search = normalize(request.args.get("search", ""))
    gi = request.args.get("gi")

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter: gi"}), 400

    gi = gi.lower() == "true"

    subquery_gi = (
        db.session.query(Match.event_id)
        .join(Division)
        .filter(
            Division.gi == gi,
        )
        .subquery()
    )

    query = db.session.query(Event.name).filter(exists().where(Event.id == subquery_gi.c.event_id))
    for name_part in search.split():
        query = query.filter(Event.normalized_name.like(f"%{name_part}%"))
    query = query.order_by(Event.name).limit(MAX_RESULTS)
    results = query.all()

    response = [result.name for result in results]

    return jsonify(response)
