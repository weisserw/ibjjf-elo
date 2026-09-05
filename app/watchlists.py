"""Selection identity, registration-scoped search and current watchlist rows."""

import base64
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    Athlete,
    Division,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Watchlist,
    WatchlistSchedule,
)
from normalize import normalize
from constants import age_order_all, translate_age_keep_juvenile
from watchlist_refresh import database_now, trigger, utc

NAMESPACE = uuid.UUID("56e85f1e-d720-5d40-a186-bcc82e02d311")
SCHEMA_VERSION = 1


class WatchlistError(ValueError):
    def __init__(self, code, status=400, **details):
        super().__init__(code)
        self.code, self.status, self.details = code, status, details


def canonical_selection(event_ids, athlete_ids):
    if not isinstance(event_ids, list) or not isinstance(athlete_ids, list):
        raise WatchlistError("invalid_selection")
    if not event_ids or not athlete_ids:
        raise WatchlistError("selection_required")
    if len(event_ids) > current_app.config.get("WATCHLIST_MAX_TOURNAMENTS", 10) or len(
        athlete_ids
    ) > current_app.config.get("WATCHLIST_MAX_ATHLETES", 200):
        raise WatchlistError("selection_too_large")
    try:
        if any(
            not isinstance(e, str) or not re.fullmatch(r"[0-9]{1,12}", e)
            for e in event_ids
        ):
            raise ValueError()
        events = sorted({str(int(e)) for e in event_ids})
        athletes = sorted({str(uuid.UUID(a)) for a in athlete_ids})
    except (ValueError, TypeError, AttributeError):
        raise WatchlistError("invalid_selection")
    return {"event_ids": events, "athlete_ids": athletes}


def selection_id(selection):
    return uuid.uuid5(
        NAMESPACE,
        json.dumps(
            {"version": SCHEMA_VERSION, **selection},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def external(link):
    url = urlsplit(link.link)
    return url.scheme == "https" and url.hostname in {
        "www.ibjjfdb.com",
        "ibjjfdb.com",
        "www.ibjjf.com",
        "ibjjf.com",
    }


def public_registration_rows():
    return or_(
        *(
            RegistrationLink.link.startswith("https://" + host + "/")
            for host in ("www.ibjjfdb.com", "ibjjfdb.com", "www.ibjjf.com", "ibjjf.com")
        )
    )


def tournaments(event_ids=None, available=False):
    query = db.session.query(RegistrationLink).filter(
        RegistrationLink.event_id.isnot(None)
    )
    if event_ids is not None:
        query = query.filter(RegistrationLink.event_id.in_(event_ids))
    if available:
        query = query.filter(
            RegistrationLink.hidden.isnot(True),
            or_(
                RegistrationLink.event_end_date.is_(None),
                RegistrationLink.event_end_date
                >= datetime.combine(datetime.now().date(), datetime.min.time()),
            ),
        )
    links = [
        link
        for link in query.all()
        if external(link) and re.fullmatch(r"[0-9]+", link.event_id)
    ]
    imported = {
        row[0]
        for row in db.session.query(RegistrationLinkCompetitor.registration_link_id)
        .filter(
            RegistrationLinkCompetitor.registration_link_id.in_(
                [link.id for link in links]
            ),
        )
        .distinct()
        .all()
    }
    grouped = {}
    for link in links:
        item = grouped.setdefault(
            link.event_id,
            {
                "event_id": link.event_id,
                "name": link.name,
                "start": link.event_start_date,
                "end": link.event_end_date,
                "links": [],
                "registration_ready": True,
            },
        )
        if link.event_start_date:
            item["start"] = min(
                item["start"] or link.event_start_date, link.event_start_date
            )
        if link.event_end_date:
            item["end"] = max(item["end"] or link.event_end_date, link.event_end_date)
        item["links"].append({"id": str(link.id), "url": link.link})
        item["registration_ready"] &= (
            link.registrations_imported_at is not None or link.id in imported
        )
    return grouped


def event_summary(event):
    normalized_name = normalize(event["name"])
    return {
        "event_id": event["event_id"],
        "name": event["name"],
        "registration_link_ids": [link["id"] for link in event["links"]],
        "start_date": event["start"].date().isoformat() if event["start"] else None,
        "end_date": event["end"].date().isoformat() if event["end"] else None,
        "registration_ready": event["registration_ready"],
        "is_kids_tournament": any(
            marker in normalized_name for marker in ("kids", "criancas", "15 anos")
        ),
        "selectable": bool(event["start"] and event["end"]),
        "unavailable_reason": (
            None if event["start"] and event["end"] else "missing_event_dates"
        ),
    }


def athlete_summary(athlete):
    return {
        "id": str(athlete.id),
        "ibjjf_id": athlete.ibjjf_id,
        "name": athlete.personal_name or athlete.name,
        "full_name": None if athlete.hide_full_name else athlete.name,
        "profile_url": "/athlete/" + (athlete.slug or str(athlete.id)),
        "trackable": athlete.ibjjf_id is not None,
    }


def eligible(event_ids, q="", mode="name"):
    if mode == "all":
        return db.session.query(Athlete).filter(
            or_(
                Athlete.id.in_(
                    eligible(event_ids, q, "name").with_entities(Athlete.id)
                ),
                Athlete.id.in_(
                    eligible(event_ids, q, "team").with_entities(Athlete.id)
                ),
            )
        )
    registrations = (
        db.session.query(RegistrationLinkCompetitor.id)
        .join(RegistrationLink)
        .join(Division, Division.id == RegistrationLinkCompetitor.division_id)
        .filter(
            RegistrationLink.event_id.in_(event_ids),
            RegistrationLink.hidden.isnot(True),
            RegistrationLinkCompetitor.athlete_name == Athlete.name,
            public_registration_rows(),
            Division.age.in_(age_order_all),
        )
    )
    if mode == "team_exact":
        registrations = registrations.filter(RegistrationLinkCompetitor.team_name == q)
    if mode == "team":
        registrations = registrations.filter(
            RegistrationLinkCompetitor.team_name.ilike(
                "%"
                + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%",
                escape="\\",
            )
        )
    query = db.session.query(Athlete).filter(registrations.exists())
    if mode == "name" and q:
        # Preserve literal wildcard characters while normalizing name fragments.
        value = "".join(
            part if part in {"%", "_", "\\"} else normalize(part)
            for part in re.split(r"([%_\\])", q)
        )
        value = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(
            or_(
                Athlete.normalized_name.like("%" + value + "%", escape="\\"),
                Athlete.normalized_personal_name.like("%" + value + "%", escape="\\"),
            )
        )
    return query


def search(event_ids, q, mode, cursor=None, selected_ids=None):
    if mode not in {"name", "team", "all", "team_exact"} or len(q) > 200:
        raise WatchlistError("invalid_search")
    if not event_ids or len(event_ids) > current_app.config.get(
        "WATCHLIST_MAX_TOURNAMENTS", 10
    ):
        raise WatchlistError("tournaments_required")
    events = tournaments(event_ids, available=True)
    if set(event_ids) != set(events) or any(
        not e["start"] or not e["end"] for e in events.values()
    ):
        raise WatchlistError("invalid_tournaments")
    for event in events.values():
        if not event["registration_ready"]:
            trigger(event, registrations=True)
    query = eligible(event_ids, q, mode)
    if mode == "team_exact":
        query = query.filter(Athlete.ibjjf_id.isnot(None))
    display = func.coalesce(func.nullif(Athlete.personal_name, ""), Athlete.name)
    if cursor:
        try:
            name, identity = json.loads(base64.urlsafe_b64decode(cursor).decode())
            identity = uuid.UUID(identity)
            if not isinstance(name, str):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise WatchlistError("invalid_cursor")
        query = query.filter(
            or_(display > name, (display == name) & (Athlete.id > identity))
        )
    rows = query.order_by(display, Athlete.id).limit(31).all() if q.strip() else []
    next_cursor = None
    if len(rows) > 30:
        last = rows[29]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last.personal_name or last.name, str(last.id)]).encode()
        ).decode()
    rows = rows[:30]
    contexts = defaultdict(set)
    for name, team, event_id in (
        db.session.query(
            RegistrationLinkCompetitor.athlete_name,
            RegistrationLinkCompetitor.team_name,
            RegistrationLink.event_id,
        )
        .join(RegistrationLink)
        .filter(
            RegistrationLink.event_id.in_(event_ids),
            RegistrationLink.hidden.isnot(True),
            public_registration_rows(),
            RegistrationLinkCompetitor.athlete_name.in_([a.name for a in rows]),
            RegistrationLinkCompetitor.division_id.in_(
                db.session.query(Division.id).filter(Division.age.in_(age_order_all))
            ),
        )
        .all()
    ):
        contexts[name].add((team, event_id))
    result = [
        {
            **athlete_summary(a),
            "registrations": [
                {
                    "team": team,
                    "event_id": event_id,
                    "tournament": events[event_id]["name"],
                }
                for team, event_id in sorted(
                    contexts[a.name], key=lambda c: (c[1], c[0] or "")
                )
            ],
        }
        for a in rows
    ]
    valid_ids = None
    if selected_ids is not None:
        try:
            if len(selected_ids) > 200:
                raise ValueError()
            ids = [uuid.UUID(a) for a in selected_ids]
        except (ValueError, TypeError):
            raise WatchlistError("invalid_selection")
        valid_ids = [
            str(a.id)
            for a in eligible(event_ids)
            .filter(Athlete.id.in_(ids), Athlete.ibjjf_id.isnot(None))
            .all()
        ]
    teams = []
    if mode == "all" and q.strip():
        pattern = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        teams = [
            row[0]
            for row in db.session.query(RegistrationLinkCompetitor.team_name)
            .join(RegistrationLink)
            .filter(
                RegistrationLink.event_id.in_(event_ids),
                RegistrationLink.hidden.isnot(True),
                public_registration_rows(),
                RegistrationLinkCompetitor.team_name.ilike(pattern, escape="\\"),
                RegistrationLinkCompetitor.division_id.in_(
                    db.session.query(Division.id).filter(
                        Division.age.in_(age_order_all)
                    )
                ),
                RegistrationLinkCompetitor.athlete_name.in_(
                    db.session.query(Athlete.name)
                ),
            )
            .distinct()
            .order_by(RegistrationLinkCompetitor.team_name)
            .all()
        ]
    return {
        "athletes": result,
        "teams": teams,
        "next_cursor": next_cursor,
        "eligible_selected_ids": valid_ids,
        "registration_ready": all(e["registration_ready"] for e in events.values()),
        "tournaments": [event_summary(e) for e in events.values()],
    }


def expiry(events):
    return utc(max(e["end"] for e in events.values() if e["end"]) + timedelta(days=2))


def creation_capacity(identity):
    """Check the saved-watchlist count before creating a new selection."""
    row = db.session.get(Watchlist, identity)
    if row is None and db.session.query(Watchlist).count() >= current_app.config.get(
        "WATCHLIST_MAX_SAVED", 10000
    ):
        db.session.rollback()
        raise WatchlistError("watchlist_capacity_reached", 503)
    return row


def save(event_ids, athlete_ids):
    selection = canonical_selection(event_ids, athlete_ids)
    identity = selection_id(selection)
    row = creation_capacity(identity)
    events = tournaments(selection["event_ids"], available=True)
    if set(events) != set(selection["event_ids"]) or any(
        not e["start"] or not e["end"] for e in events.values()
    ):
        raise WatchlistError("invalid_tournaments")
    valid = {
        str(a.id)
        for a in eligible(selection["event_ids"])
        .filter(
            Athlete.id.in_([uuid.UUID(a) for a in selection["athlete_ids"]]),
            Athlete.ibjjf_id.isnot(None),
        )
        .all()
    }
    invalid = sorted(set(selection["athlete_ids"]) - valid)
    if invalid:
        raise WatchlistError("athletes_no_longer_eligible", athlete_ids=invalid)
    if row is None:
        try:
            with db.session.begin_nested():
                row = Watchlist(
                    id=identity,
                    schema_version=SCHEMA_VERSION,
                    canonical_selection=selection,
                    created_at=database_now(),
                    expires_at=expiry(events),
                )
                db.session.add(row)
                db.session.flush()
        except IntegrityError:
            row = db.session.get(Watchlist, identity)
    if row.canonical_selection != selection or row.schema_version != SCHEMA_VERSION:
        raise WatchlistError("selection_identity_conflict", 409)
    row.expires_at = expiry(events)
    db.session.commit()
    return {
        "id": str(identity),
        "url": "/watchlists/" + str(identity),
        "expires_at": utc(row.expires_at).isoformat(),
    }


def load(identity):
    try:
        identity = uuid.UUID(str(identity))
    except ValueError:
        raise WatchlistError("invalid_watchlist")
    row = db.session.get(Watchlist, identity)
    if row is None:
        raise WatchlistError("watchlist_unavailable", 404)
    events = tournaments(row.canonical_selection["event_ids"])
    if (
        events
        and all(e["end"] for e in events.values())
        and len(events) == len(row.canonical_selection["event_ids"])
    ):
        row.expires_at = expiry(events)
    if utc(row.expires_at) <= database_now():
        db.session.delete(row)
        db.session.commit()
        raise WatchlistError("watchlist_expired", 410)
    db.session.commit()
    return row, events


def summaries(row, events):
    ids = [uuid.UUID(a) for a in row.canonical_selection["athlete_ids"]]
    athletes = {
        str(a.id): athlete_summary(a)
        for a in db.session.query(Athlete).filter(Athlete.id.in_(ids)).all()
    }
    return {
        "id": str(row.id),
        "selection": row.canonical_selection,
        "expires_at": utc(row.expires_at).isoformat(),
        "tournaments": [event_summary(e) for e in events.values()],
        "athletes": [
            athletes.get(
                str(a),
                {
                    "id": str(a),
                    "name": "",
                    "trackable": False,
                    "ibjjf_id": None,
                    "profile_url": None,
                },
            )
            for a in ids
        ],
    }


def match_order(match):
    return (
        match["local_time"] is None,
        match["local_date"],
        match["local_time"] or "",
        match["event_id"],
        match["day_id"],
        match["mat"],
        match["fight_number"],
        match.get("source_order", 0),
    )


def supported_schedule_division(division):
    # Match the registration import's supported ages without requiring a rating
    # model or a recognized belt/weight (teens still need their schedule).
    for part in division.split(" / "):
        try:
            translate_age_keep_juvenile(part.strip())
            return True
        except ValueError:
            pass
    return False


def enrich(matches, events):
    from routes.brackets import (
        get_ratings,
        compute_match_ratings,
        parse_division,
        format_division,
        is_gi,
    )
    from elo import DEFAULT_RATINGS
    from constants import rated_ages

    groups = defaultdict(list)
    identities = {s["ibjjf_id"] for m in matches for s in m["sides"] if s["ibjjf_id"]}
    athletes = {
        a.ibjjf_id: athlete_summary(a)
        for a in db.session.query(Athlete)
        .filter(Athlete.ibjjf_id.in_(identities))
        .all()
    }
    for match in matches:
        match["bracket_category"] = None
        for side in match["sides"]:
            side.update(
                rating=None, match_count=0, win_probability=None, profile_url=None
            )
            if side["ibjjf_id"] in athletes:
                side.update(athletes[side["ibjjf_id"]])
        try:
            division = parse_division(match["division"])
        except ValueError:
            continue
        match["bracket_category"] = format_division(division)
        if division["age"] not in rated_ages or division[
            "age"
        ] not in DEFAULT_RATINGS.get(division["belt"], {}):
            continue
        groups[(match["event_id"], match["local_date"], *division.values())].append(
            (match, division)
        )
    for (event_id, date, *_), entries in groups.items():
        division = entries[0][1]
        if event_id not in events:
            continue
        gi = is_gi(events[event_id]["name"])
        inputs = {}
        for match, _ in entries:
            for side in match["sides"]:
                if side["ibjjf_id"]:
                    inputs[side["ibjjf_id"]] = {
                        **division,
                        "name": side["name"],
                        "team": side["team"],
                        "ibjjf_id": side["ibjjf_id"],
                        "id": None,
                        "rating": None,
                        "match_count": None,
                        "rank": None,
                        "percentile": None,
                        "percentile_age": None,
                        "last_weight": None,
                        "note": None,
                        "slug": None,
                        "instagram_profile": None,
                        "personal_name": None,
                        "profile_image_url": None,
                        "country": None,
                        "country_note": None,
                        "country_note_pt": None,
                    }
        results = list(inputs.values())
        get_ratings(results, event_id, gi, datetime.now(), True, None, strict_ids=True)
        for match, _ in entries:
            adapter = {}
            for color, side in zip(("red", "blue"), match["sides"]):
                adapter.update(
                    {
                        color + "_id": side["ibjjf_id"],
                        color + "_name": side["name"],
                        color + "_weight": division["weight"],
                        color + "_note": None,
                        color + "_loser": False,
                    }
                )
            compute_match_ratings(
                [adapter],
                results,
                division["belt"],
                division["weight"],
                division["age"],
            )
            for color, side in zip(("red", "blue"), match["sides"]):
                if side["ibjjf_id"]:
                    side.update(
                        rating=adapter[color + "_rating"],
                        match_count=adapter[color + "_match_count"],
                        win_probability=adapter[color + "_expected"],
                    )


def data(row, events, today=None):
    today = today or datetime.now().date()
    base = summaries(row, events)
    selection = base["selection"]
    now = database_now()
    states, matches, coverage_uncertainties = [], [], []
    for event_id in selection["event_ids"]:
        event = events.get(event_id)
        cache = db.session.get(WatchlistSchedule, event_id)
        if event and event["start"] and event["end"] and event["end"].date() >= today:
            trigger(event)
            db.session.expire_all()
            cache = db.session.get(WatchlistSchedule, event_id)
        snapshot = cache.snapshot if cache else None
        refreshing = bool(cache and cache.lease_until and utc(cache.lease_until) > now)
        stale = bool(
            cache
            and cache.fetched_at
            and utc(cache.fetched_at) <= now - timedelta(seconds=180)
        )
        # Reaching the TTL starts a refresh; it does not invalidate complete
        # coverage. Keep the last successful snapshot usable while the worker
        # owns a live lease. Failures and lost/expired leases still mark it stale.
        if (
            stale
            and refreshing
            and not cache.last_error_code
            and cache.coverage
            and all(c["state"] == "complete" for c in cache.coverage)
        ):
            stale = False
        coverage_uncertain = (
            snapshot is None or stale or bool(cache.last_error_code if cache else False)
        )
        unpublished = bool(
            cache and any(c["state"] == "unpublished" for c in cache.coverage or [])
        )
        coverage_uncertain |= unpublished
        state = (
            "unavailable"
            if not event
            else "populating" if snapshot is None else "stale" if stale else "ready"
        )
        if cache and cache.last_error_code:
            state = "stale" if snapshot is not None else "unavailable"
        elif unpublished:
            state = "not_posted"
        if (
            event
            and event["end"]
            and event["end"].date() < today
            and snapshot is not None
            and not cache.last_error_code
            and cache.coverage
            and all(c["state"] == "complete" for c in cache.coverage)
        ):
            # Completed calendar days do not require further upstream scans.
            coverage_uncertain = False
        coverage_uncertainties.append(coverage_uncertain)
        states.append(
            {
                "event_id": event_id,
                "name": event["name"] if event else event_id,
                "state": state,
                "refreshing": refreshing,
                "fetched_at": (
                    utc(cache.fetched_at).isoformat()
                    if cache and cache.fetched_at
                    else None
                ),
                "coverage": cache.coverage if cache else None,
            }
        )
        if snapshot is not None:
            matches.extend(
                json.loads(json.dumps(m))
                for m in snapshot
                if m["local_date"] >= today.isoformat()
            )
    supported_matches = [
        m for m in matches if supported_schedule_division(m["division"])
    ]
    supported_ids = {s["ibjjf_id"] for m in supported_matches for s in m["sides"]}
    hidden_ids = {
        s["ibjjf_id"]
        for m in matches
        if not supported_schedule_division(m["division"])
        for s in m["sides"]
    } - supported_ids
    base["athletes"] = [a for a in base["athletes"] if a["ibjjf_id"] not in hidden_ids]
    matches = supported_matches
    by_id = {}
    for match in sorted(matches, key=match_order):
        for side in match["sides"]:
            if side["ibjjf_id"]:
                by_id.setdefault(side["ibjjf_id"], match)
    chosen = {
        id(by_id[a["ibjjf_id"]]): by_id[a["ibjjf_id"]]
        for a in base["athletes"]
        if a["ibjjf_id"] in by_id
    }
    enrich(list(chosen.values()), events)
    rows = []
    coverage_uncertain = any(coverage_uncertainties)
    for athlete in base["athletes"]:
        match = by_id.get(athlete["ibjjf_id"])
        if match:
            side_index = next(
                i
                for i, s in enumerate(match["sides"])
                if s["ibjjf_id"] == athlete["ibjjf_id"]
            )
            rows.append(
                {
                    "athlete": athlete,
                    "state": "scheduled",
                    "match": match,
                    "competitor": match["sides"][side_index],
                    "opponent": match["sides"][1 - side_index],
                }
            )
        else:
            state = "not_on_schedule"
            if coverage_uncertain:
                state = (
                    "unavailable"
                    if any(s["state"] in {"unavailable", "stale"} for s in states)
                    else (
                        "populating"
                        if any(s["state"] == "populating" for s in states)
                        else "not_posted"
                    )
                )
            elif any(e["start"] and e["start"].date() > today for e in events.values()):
                state = "not_posted"
            rows.append(
                {
                    "athlete": athlete,
                    "state": state,
                    "match": None,
                }
            )
    rows.sort(
        key=lambda r: (
            (0, match_order(r["match"]), r["athlete"]["id"])
            if r["match"]
            else (
                2 if r["state"] == "not_on_schedule" else 1,
                (),
                r["athlete"]["name"],
                r["athlete"]["id"],
            )
        )
    )
    return {
        **base,
        "rows": rows,
        "tournaments": states,
        "poll_after_seconds": 180,
    }


def purge():
    now = database_now()
    removed = 0
    # Reconcile authoritative dates before deleting a formerly expired selection.
    for row in db.session.query(Watchlist).all():
        events = tournaments(row.canonical_selection["event_ids"])
        if len(events) == len(row.canonical_selection["event_ids"]) and all(
            e["end"] for e in events.values()
        ):
            row.expires_at = expiry(events)
        if utc(row.expires_at) <= now:
            db.session.delete(row)
            removed += 1
    db.session.flush()
    active = {
        e
        for row in db.session.query(Watchlist).all()
        for e in row.canonical_selection["event_ids"]
    }
    for cache in db.session.query(WatchlistSchedule).all():
        event_id = cache.event_id.removeprefix("registration:")
        if event_id not in active and not (
            cache.lease_until and utc(cache.lease_until) > now
        ):
            db.session.delete(cache)
    db.session.commit()
    return removed
