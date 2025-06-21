from flask import Blueprint, request, jsonify
from sqlalchemy.sql import exists, or_
from extensions import db
from models import Event, Match, Division
from normalize import normalize

events_route = Blueprint("events_route", __name__)

MAX_RESULTS = 50


@events_route.route("/api/events")
def events():
    search = normalize(request.args.get("search", ""))
    gi = request.args.get("gi")
    historical = request.args.get("historical", "true").lower() == "true"

    if gi is not None:
        gi = gi.lower() == "true"

    query = db.session.query(Event.name)

    if gi is not None:
        subquery_gi = (
            db.session.query(Match.event_id)
            .join(Division)
            .filter(
                Division.gi == gi,
            )
            .subquery()
        )
        query = query.filter(exists().where(Event.id == subquery_gi.c.event_id))
    for name_part in search.split():
        query = query.filter(Event.normalized_name.like(f"%{name_part}%"))
    if not historical:
        query = query.filter(
            or_(Event.name.not_like("%(%"), Event.name.like("%idade 04 a 15 anos%"))
        )
    query = query.order_by(Event.name).limit(MAX_RESULTS)
    results = query.all()

    response = [result.name for result in results]

    return jsonify(response)
