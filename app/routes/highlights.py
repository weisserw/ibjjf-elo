import hashlib
import io
import math
from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, jsonify, make_response, request
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from livestreams import (
    get_livestream_link,
    load_linked_archive_video_links,
    load_livestream_links,
)
from models import (
    Athlete,
    # AthleteRating, temporarily removed, see below
    Division,
    Event,
    Match,
    MatchParticipant,
    RegistrationLink,
    Team,
)
from normalize import normalize
from photos import bucket_name, convert_image_to_jpeg, get_s3_client, photo_key
from routes.athletes import _build_athlete_search_query, get_athlete_data
from routes.matches import _ending_method
from routes.top import top


highlights_route = Blueprint("highlights_route", __name__)

SCHEMA_VERSION = 1
MAX_SEARCH_LIMIT = 20
MAX_MATCH_PAGE_SIZE = 50
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_ASSET_PIXELS = 25_000_000
ASSET_CACHE_SECONDS = 24 * 60 * 60


def _as_of():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _envelope(**values):
    return {"schema_version": SCHEMA_VERSION, "as_of": _as_of(), **values}


def _error(code, message, status):
    return jsonify(_envelope(error={"code": code, "message": message})), status


def _reject_unknown_args(allowed):
    unknown = sorted(set(request.args) - set(allowed))
    if unknown:
        return _error(
            "invalid_query",
            "Unexpected query parameter(s): " + ", ".join(unknown),
            400,
        )
    return None


def _bounded_int(raw, *, name, default, minimum, maximum):
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if str(value) != str(raw).strip() or value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(raw, *, name, default=None):
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return normalized == "true"


def _uuid(raw, *, name):
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{name} must be a UUID")


def _display_name(athlete):
    if athlete.personal_name:
        return athlete.personal_name
    return athlete.name


def _photo_descriptor(athlete):
    available = athlete.profile_image_saved_at is not None
    return {
        "available": available,
        "asset": (
            {
                "asset_ref": f"athlete-photo.{athlete.id}",
                "kind": "athlete_photo",
                "media_type": "image/jpeg",
            }
            if available
            else None
        ),
    }


def _athlete_summary(athlete, current_team, same_name_count, result_count):
    return {
        "athlete_id": str(athlete.id),
        "slug": athlete.slug,
        "display_name": _display_name(athlete),
        "country": athlete.country or None,
        "current_team": current_team,
        "photo": _photo_descriptor(athlete),
        "ambiguity": {
            "multiple_results": result_count > 1,
            "same_display_name_count": same_name_count,
        },
    }


@highlights_route.route("/api/highlights/v1/athletes")
def search_athletes():
    invalid = _reject_unknown_args({"query", "limit"})
    if invalid:
        return invalid
    query_text = (request.args.get("query") or "").strip()
    if len(query_text) < 2 or len(query_text) > 100:
        return _error(
            "invalid_query", "query must contain between 2 and 100 characters", 400
        )
    try:
        limit = _bounded_int(
            request.args.get("limit"),
            name="limit",
            default=10,
            minimum=1,
            maximum=MAX_SEARCH_LIMIT,
        )
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)

    rows = (
        _build_athlete_search_query(normalize(query_text))
        .order_by(Athlete.personal_name.isnot(None).desc(), Athlete.name, Athlete.id)
        .limit(limit)
        .all()
    )
    athlete_ids = [row.id for row in rows]
    latest_teams = {}
    if athlete_ids:
        team_rows = (
            db.session.query(MatchParticipant.athlete_id, Team.name)
            .join(Match, Match.id == MatchParticipant.match_id)
            .join(Team, Team.id == MatchParticipant.team_id)
            .filter(MatchParticipant.athlete_id.in_(athlete_ids))
            .order_by(Match.happened_at.desc(), MatchParticipant.id.desc())
            .all()
        )
        for athlete_id, team_name in team_rows:
            latest_teams.setdefault(athlete_id, team_name)

    display_counts = {}
    for row in rows:
        key = normalize(_display_name(row))
        display_counts[key] = display_counts.get(key, 0) + 1
    return jsonify(
        _envelope(
            query=query_text,
            athletes=[
                _athlete_summary(
                    row,
                    latest_teams.get(row.id),
                    display_counts[normalize(_display_name(row))],
                    len(rows),
                )
                for row in rows
            ],
        )
    )


@highlights_route.route("/api/highlights/v1/athletes/<athlete_id>")
def athlete_profile(athlete_id):
    invalid = _reject_unknown_args({"gi"})
    if invalid:
        return invalid
    try:
        canonical_id = _uuid(athlete_id, name="athlete_id")
        gi = _boolean(request.args.get("gi"), name="gi", default=True)
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)

    athlete = db.session.get(Athlete, canonical_id)
    if athlete is None:
        return _error("not_found", "Athlete not found", 404)
    profile = get_athlete_data(
        str(canonical_id), str(gi).lower(), include_photo_url=False
    )
    ranks = [
        {
            "rank": row["rank"],
            "rating": row["rating"],
            "percentile": row["percentile"],
            "average_rating": row["avg_rating"],
            "gender": row["gender"],
            "age": row["age"],
            "belt": row["belt"],
            "weight": row["weight"],
            "gi": gi,
        }
        for row in profile["ranks"]
    ]

    medals = [
        {
            "place": row["place"],
            "date": row["happened_at"],
            "event_id": row["event_id"],
            "event_name": row["event_name"],
            "division": row["division"],
        }
        for row in profile["medals"]
    ]
    instagram = profile["athlete"].get("instagram_profile")
    return jsonify(
        _envelope(
            athlete={
                "athlete_id": str(athlete.id),
                "slug": athlete.slug,
                "display_name": _display_name(athlete),
                "country": athlete.country or None,
                "current_team": profile["athlete"].get("team_name"),
                "current_belt": profile["athlete"].get("belt"),
                "current_rating": profile["athlete"].get("rating"),
                "gi": gi,
                "profile_path": f"/athlete/{athlete.slug}",
                "links": {
                    "instagram": (
                        f"https://www.instagram.com/{instagram}/" if instagram else None
                    ),
                    "bjjheroes": profile["athlete"].get("bjjheroes_link") or None,
                },
                "photo": _photo_descriptor(athlete),
            },
            ranks=ranks,
            medals=medals,
            team_history=[
                {"date": row["date"], "team": row["team_name"]}
                for row in profile["teamHistory"]
            ],
            suspensions=[
                {
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "reason": row["reason"] or None,
                    "organization": row["suspending_org"] or None,
                }
                for row in profile["suspensions"]
            ],
        )
    )


def _match_query():
    return db.session.query(Match).options(
        joinedload(Match.event),
        joinedload(Match.division),
        selectinload(Match.participants).joinedload(MatchParticipant.athlete),
        selectinload(Match.participants).joinedload(MatchParticipant.team),
    )


def _public_video_context(matches):
    match_ids = [match.id for match in matches]
    archive_links = load_linked_archive_video_links(db.session, match_ids)
    event_ids = sorted(
        {match.event.ibjjf_id for match in matches if match.event.ibjjf_id}
    )
    livestreams = (
        load_livestream_links(db.session, event_ids)
        if event_ids
        else {"tournament_days": {}, "live_streams": {}, "flo_event_tags": {}}
    )
    return archive_links, livestreams


def _ordered_participants(match):
    return sorted(match.participants, key=lambda row: (not row.red, str(row.id)))


def _winner_loser(match):
    participants = _ordered_participants(match)
    winner = next((row for row in participants if row.winner), None)
    loser = next((row for row in participants if not row.winner), None)
    return winner, loser


def _video_reference(match, archive_links, livestreams):
    winner, loser = _winner_loser(match)
    archive_url = archive_links.get(match.id)
    if archive_url:
        url = archive_url
    else:
        url = get_livestream_link(
            livestreams,
            match.event.ibjjf_id,
            _display_name(winner.athlete) if winner else None,
            _display_name(loser.athlete) if loser else None,
            match.happened_at,
            match.match_location,
            match.division.belt,
            match.division.age,
            match.division_size,
            match.match_number,
            None,
            None,
            match.video_link,
            match.video_start_offset_seconds,
        )
    if not url or str(url).strip().lower() == "none":
        return None
    return {
        "source_url": url,
        "offset_seconds": match.video_start_offset_seconds,
    }


def _participant_payload(participant):
    return {
        "athlete_id": str(participant.athlete_id),
        "slug": participant.athlete.slug,
        "display_name": _display_name(participant.athlete),
        "team": participant.team.name,
        "winner": participant.winner,
        "scoreboard_position": participant.scoreboard_position,
    }


def _score_payload(match):
    return {
        "top": {
            "points": match.final_top_points,
            "advantages": match.final_top_advantages,
            "penalties": match.final_top_penalties,
        },
        "bottom": {
            "points": match.final_bottom_points,
            "advantages": match.final_bottom_advantages,
            "penalties": match.final_bottom_penalties,
        },
    }


def _serialize_match(match, archive_links, livestreams):
    ending = _ending_method(match, match.final_match_time_seconds)
    return {
        "match_id": str(match.id),
        "date": match.happened_at.date().isoformat(),
        "event": {
            "event_id": str(match.event.id),
            "slug": match.event.slug,
            "name": match.event.name,
        },
        "division": {
            "gi": match.division.gi,
            "gender": match.division.gender,
            "age": match.division.age,
            "belt": match.division.belt,
            "weight": match.division.weight,
        },
        "participants": [
            _participant_payload(row) for row in _ordered_participants(match)
        ],
        "result": {
            "method": ending["category"],
            "amount": ending["amount"],
            "match_time_seconds": match.final_match_time_seconds,
            "score": _score_payload(match),
        },
        "video": _video_reference(match, archive_links, livestreams),
    }


@highlights_route.route("/api/highlights/v1/athletes/<athlete_id>/matches")
def athlete_matches(athlete_id):
    invalid = _reject_unknown_args({"gi", "page", "page_size"})
    if invalid:
        return invalid
    try:
        canonical_id = _uuid(athlete_id, name="athlete_id")
        gi = _boolean(request.args.get("gi"), name="gi", default=True)
        page = _bounded_int(
            request.args.get("page"), name="page", default=1, minimum=1, maximum=10000
        )
        page_size = _bounded_int(
            request.args.get("page_size"),
            name="page_size",
            default=20,
            minimum=1,
            maximum=MAX_MATCH_PAGE_SIZE,
        )
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)
    if db.session.get(Athlete, canonical_id) is None:
        return _error("not_found", "Athlete not found", 404)

    query = (
        _match_query()
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .join(Division, Division.id == Match.division_id)
        .filter(MatchParticipant.athlete_id == canonical_id, Division.gi == gi)
    )
    total = query.count()
    matches = (
        query.order_by(Match.happened_at.desc(), Match.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    archive_links, livestreams = _public_video_context(matches)
    return jsonify(
        _envelope(
            athlete_id=str(canonical_id),
            gi=gi,
            pagination={
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": math.ceil(total / page_size),
            },
            matches=[
                _serialize_match(match, archive_links, livestreams) for match in matches
            ],
        )
    )


@highlights_route.route("/api/highlights/v1/matches/<match_id>")
def match_detail(match_id):
    invalid = _reject_unknown_args(set())
    if invalid:
        return invalid
    try:
        canonical_id = _uuid(match_id, name="match_id")
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)
    match = _match_query().filter(Match.id == canonical_id).one_or_none()
    if match is None:
        return _error("not_found", "Match not found", 404)
    archive_links, livestreams = _public_video_context([match])
    return jsonify(_envelope(match=_serialize_match(match, archive_links, livestreams)))


@highlights_route.route("/api/highlights/v1/rankings")
def rankings():
    allowed = {
        "gender",
        "age",
        "belt",
        "gi",
        "weight",
        "country",
        "name",
        "changed",
        "upcoming",
        "page",
    }
    invalid = _reject_unknown_args(allowed)
    if invalid:
        return invalid
    try:
        gi = _boolean(request.args.get("gi"), name="gi", default=None)
        changed = _boolean(request.args.get("changed"), name="changed", default=False)
        upcoming = _boolean(
            request.args.get("upcoming"), name="upcoming", default=False
        )
        page = _bounded_int(
            request.args.get("page"),
            name="page",
            default=1,
            minimum=1,
            maximum=10000,
        )
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)
    result = top(include_photo_urls=False)
    if isinstance(result, tuple):
        response, status = result
        message = (response.get_json() or {}).get("error", "Invalid ranking query")
        return _error("invalid_query", message, status)
    payload = result.get_json()
    photo_athlete_ids = [UUID(row["athlete_id"]) for row in payload["rows"]]
    photo_athlete_ids = {
        str(athlete_id)
        for athlete_id, in db.session.query(Athlete.id)
        .filter(
            Athlete.id.in_(photo_athlete_ids),
            Athlete.profile_image_saved_at.isnot(None),
        )
        .all()
    }
    rows = []
    for row in payload["rows"]:
        display_name = row.get("personal_name") or row["name"]
        rows.append(
            {
                "rank": row["rank"],
                "athlete_id": str(row["athlete_id"]),
                "slug": row["slug"],
                "display_name": display_name,
                "country": row["country"] or None,
                "rating": row["rating"],
                "match_count": row["match_count"],
                "previous_rating": row["previous_rating"],
                "previous_rank": row["previous_rank"],
                "previous_match_count": row["previous_match_count"],
                "photo": {
                    "available": row["athlete_id"] in photo_athlete_ids,
                    "asset": (
                        {
                            "asset_ref": f"athlete-photo.{row['athlete_id']}",
                            "kind": "athlete_photo",
                            "media_type": "image/jpeg",
                        }
                        if row["athlete_id"] in photo_athlete_ids
                        else None
                    ),
                },
            }
        )
    return jsonify(
        _envelope(
            context={
                "gender": request.args.get("gender"),
                "age": request.args.get("age"),
                "belt": request.args.get("belt"),
                "gi": gi,
                "weight": request.args.get("weight") or "",
                "country": request.args.get("country") or None,
                "name": request.args.get("name") or None,
                "changed": changed,
                "upcoming": upcoming,
            },
            pagination={
                "page": page,
                "page_size": 30,
                "total_pages": payload["totalPages"],
            },
            rows=rows,
        )
    )


def _event_payload(event, start, end, gi_values, registration=None):
    if start is None and registration is not None:
        start = registration.event_start_date
    if end is None and registration is not None:
        end = registration.event_end_date
    return {
        "event_id": str(event.id),
        "slug": event.slug,
        "name": event.name,
        "start_date": start.date().isoformat() if start else None,
        "end_date": end.date().isoformat() if end else None,
        "location": None,
        "gi": next(iter(gi_values)) if len(gi_values) == 1 else None,
        "tournament_url": registration.link if registration is not None else None,
        "assets": [],
    }


def _event_metadata(events):
    if not events:
        return {}, {}, {}
    event_ids = [event.id for event in events]
    date_rows = (
        db.session.query(
            Match.event_id,
            func.min(Match.happened_at),
            func.max(Match.happened_at),
        )
        .filter(Match.event_id.in_(event_ids))
        .group_by(Match.event_id)
        .all()
    )
    dates = {event_id: (start, end) for event_id, start, end in date_rows}
    gi_rows = (
        db.session.query(Match.event_id, Division.gi)
        .join(Division, Division.id == Match.division_id)
        .filter(Match.event_id.in_(event_ids))
        .distinct()
        .all()
    )
    gis = {}
    for event_id, gi in gi_rows:
        gis.setdefault(event_id, set()).add(gi)
    ibjjf_ids = {event.ibjjf_id for event in events if event.ibjjf_id}
    normalized_names = {event.normalized_name for event in events}
    registrations = (
        RegistrationLink.query.filter(
            RegistrationLink.hidden.isnot(True),
            or_(
                RegistrationLink.event_id.in_(ibjjf_ids),
                RegistrationLink.normalized_name.in_(normalized_names),
            ),
        )
        .order_by(RegistrationLink.updated_at.desc())
        .all()
    )
    registrations_by_event = {}
    for event in events:
        registrations_by_event[event.id] = next(
            (
                row
                for row in registrations
                if (event.ibjjf_id and row.event_id == event.ibjjf_id)
                or row.normalized_name == event.normalized_name
            ),
            None,
        )
    return dates, gis, registrations_by_event


@highlights_route.route("/api/highlights/v1/events")
def search_events():
    invalid = _reject_unknown_args({"query", "limit"})
    if invalid:
        return invalid
    query_text = (request.args.get("query") or "").strip()
    if len(query_text) < 2 or len(query_text) > 100:
        return _error(
            "invalid_query", "query must contain between 2 and 100 characters", 400
        )
    try:
        limit = _bounded_int(
            request.args.get("limit"),
            name="limit",
            default=10,
            minimum=1,
            maximum=MAX_SEARCH_LIMIT,
        )
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)
    query = Event.query.filter(Event.medals_only.isnot(True))
    for token in normalize(query_text).split():
        query = query.filter(Event.normalized_name.like(f"%{token}%"))
    events = query.order_by(Event.name, Event.id).limit(limit).all()
    dates, gis, registrations = _event_metadata(events)
    return jsonify(
        _envelope(
            query=query_text,
            events=[
                _event_payload(
                    event,
                    *dates.get(event.id, (None, None)),
                    gis.get(event.id, set()),
                    registrations.get(event.id),
                )
                for event in events
            ],
        )
    )


@highlights_route.route("/api/highlights/v1/events/<event_id>")
def event_detail(event_id):
    invalid = _reject_unknown_args(set())
    if invalid:
        return invalid
    try:
        canonical_id = _uuid(event_id, name="event_id")
    except ValueError as exc:
        return _error("invalid_query", str(exc), 400)
    event = db.session.get(Event, canonical_id)
    if event is None or event.medals_only is True:
        return _error("not_found", "Event not found", 404)
    dates, gis, registrations = _event_metadata([event])
    return jsonify(
        _envelope(
            event=_event_payload(
                event,
                *dates.get(event.id, (None, None)),
                gis.get(event.id, set()),
                registrations.get(event.id),
            )
        )
    )


@highlights_route.route("/api/highlights/v1/assets/<asset_ref>")
def asset(asset_ref):
    invalid = _reject_unknown_args(set())
    if invalid:
        return invalid
    prefix = "athlete-photo."
    if not asset_ref.startswith(prefix):
        return _error("not_found", "Asset not found", 404)
    try:
        athlete_id = _uuid(asset_ref[len(prefix) :], name="asset_ref")
    except ValueError:
        return _error("not_found", "Asset not found", 404)
    athlete = db.session.get(Athlete, athlete_id)
    if athlete is None or athlete.profile_image_saved_at is None:
        return _error("not_found", "Asset not found", 404)

    try:
        obj = get_s3_client().get_object(
            Bucket=bucket_name, Key=f"{photo_key}/{athlete.id}.jpg"
        )
        content_type = (obj.get("ContentType") or "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png"}:
            return _error("invalid_asset", "Asset has an unsupported media type", 502)
        body = obj["Body"].read(MAX_ASSET_BYTES + 1)
    except Exception as exc:
        error_response = getattr(exc, "response", None)
        error = (
            error_response.get("Error", {}) if isinstance(error_response, dict) else {}
        )
        if error.get("Code") in {"NoSuchKey", "NotFound", "404"}:
            return _error("not_found", "Asset not found", 404)
        return _error("asset_unavailable", "Asset could not be retrieved", 502)
    if not body or len(body) > MAX_ASSET_BYTES:
        return _error("invalid_asset", "Asset exceeds the byte limit", 502)
    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
            width, height = image.size
            actual_format = image.format
    except (UnidentifiedImageError, OSError, ValueError):
        return _error("invalid_asset", "Asset is not a valid image", 502)
    if width <= 0 or height <= 0 or width * height > MAX_ASSET_PIXELS:
        return _error("invalid_asset", "Asset exceeds the pixel limit", 502)
    expected_format = "JPEG" if content_type == "image/jpeg" else "PNG"
    if actual_format != expected_format:
        return _error("invalid_asset", "Asset media type does not match its bytes", 502)

    if actual_format == "PNG":
        try:
            body = convert_image_to_jpeg(body)
        except ValueError:
            return _error("invalid_asset", "Asset could not be normalized", 502)
        content_type = "image/jpeg"

    response = make_response(body)
    response.headers["Content-Type"] = content_type
    response.headers["Content-Length"] = str(len(body))
    response.headers["Cache-Control"] = f"public, max-age={ASSET_CACHE_SECONDS}"
    response.headers["ETag"] = f'"{hashlib.sha256(body).hexdigest()}"'
    response.headers["X-Image-Width"] = str(width)
    response.headers["X-Image-Height"] = str(height)
    return response
