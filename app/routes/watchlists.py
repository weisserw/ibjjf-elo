from calendar import monthrange
from datetime import date
from flask import Blueprint, jsonify, request
import watchlists

watchlists_route = Blueprint("watchlists_route", __name__, url_prefix="/api/watchlists")


@watchlists_route.errorhandler(watchlists.WatchlistError)
def watchlist_error(error):
    return jsonify(error=error.code, **error.details), error.status


@watchlists_route.get("/tournaments")
def tournaments():
    events = watchlists.tournaments(available=True)
    today = date.today()
    year, month = (
        (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    )
    cutoff = date(year, month, min(today.day, monthrange(year, month)[1]))
    return jsonify(
        tournaments=sorted(
            [
                watchlists.event_summary(e)
                for e in events.values()
                if e["start"] and e["start"].date() <= cutoff
            ],
            key=lambda e: (e["start_date"] or "9999", e["event_id"]),
        )
    )


@watchlists_route.get("/athletes")
def athletes():
    return jsonify(
        watchlists.search(
            request.args.getlist("event_id"),
            request.args.get("q", ""),
            request.args.get("mode", "all"),
            request.args.get("cursor"),
            request.args.getlist("selected_id"),
            request.args.getlist("selected_name"),
        )
    )


@watchlists_route.post("")
def save():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise watchlists.WatchlistError("invalid_selection")
    return jsonify(
        watchlists.save(
            payload.get("event_ids"),
            payload.get("athlete_ids"),
            payload.get("athlete_names"),
        )
    )


@watchlists_route.get("/<identity>")
def selection(identity):
    return jsonify(watchlists.summaries(*watchlists.load(identity)))


@watchlists_route.get("/<identity>/data")
def data(identity):
    today = None
    if request.args.get("local_date"):
        try:
            today = date.fromisoformat(request.args["local_date"])
        except ValueError:
            raise watchlists.WatchlistError("invalid_date")
    return jsonify(watchlists.data(*watchlists.load(identity), today=today))
