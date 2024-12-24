from flask import Blueprint, request, jsonify
from sqlalchemy.sql import exists
from extensions import db
from models import Event, Match, Division

events_route = Blueprint('events_route', __name__)

MAX_RESULTS = 50

@events_route.route('/api/events')
def events():
    search = request.args.get('search', '')
    gi = request.args.get('gi')

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter: gi"}), 400

    gi = gi.lower() == 'true'

    subquery_gi = (
        db.session.query(Match.event_id)
        .join(Division)
        .filter(
            Division.gi == gi,
        )
        .subquery()
    )

    query = db.session.query(Event.name).filter(
        Event.name.ilike(f'%{search}%'),
        exists().where(Event.id == subquery_gi.c.event_id)
    ).order_by(Event.name).limit(MAX_RESULTS)
    print(query.statement)
    results = query.all()

    response = [result.name for result in results]

    return jsonify(response)
