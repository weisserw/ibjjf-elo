import os
import math
from flask import Blueprint, request, jsonify
from datetime import datetime
from extensions import db
from sqlalchemy import func, or_
from models import (
    AthleteRating,
    Athlete,
    RegistrationLinkCompetitor,
    RegistrationLink,
    Division,
)
from photos import get_public_photo_url, get_s3_client
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
    upcoming = request.args.get("upcoming")
    page = request.args.get("page") or 1

    if not all([gender, age, belt, gi]):
        return jsonify({"error": "Missing mandatory query parameters"}), 400

    try:
        page = int(page)
        if page < 1:
            raise ValueError()
    except ValueError:
        return jsonify({"error": "Invalid page number"}), 400

    gi = gi.lower() == "true"
    changed = changed and changed.lower() == "true"
    upcoming = upcoming and upcoming.lower() == "true"

    s3_client = get_s3_client()

    query = (
        db.session.query(
            Athlete.id,
            Athlete.name,
            Athlete.slug,
            Athlete.instagram_profile,
            Athlete.personal_name,
            Athlete.profile_image_saved_at,
            Athlete.country,
            Athlete.country_note,
            Athlete.country_note_pt,
            AthleteRating.rating,
            AthleteRating.rank,
            AthleteRating.match_count,
            AthleteRating.previous_rating,
            AthleteRating.previous_rank,
            AthleteRating.previous_match_count,
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
        exact = name.strip().startswith('"') and name.strip().endswith('"')
        if exact:
            name = name.strip()[1:-1]
            query = query.filter(Athlete.normalized_name == normalize(name))
        else:
            if os.getenv("DATABASE_URL"):
                # Use full-text search
                search_terms = [term + ":*" for term in normalize(name).split()]
                ts_query = func.to_tsquery("simple", " & ".join(search_terms))
                query = query.filter(
                    or_(
                        Athlete.normalized_name_tsvector.op("@@")(ts_query),
                        Athlete.normalized_personal_name_tsvector.op("@@")(ts_query),
                    )
                )
            else:
                # Fallback to LIKE search
                for name_part in normalize(name).split():
                    query = query.filter(
                        or_(
                            Athlete.normalized_name.like(f"%{name_part}%"),
                            Athlete.normalized_personal_name.like(f"%{name_part}%"),
                        )
                    )

    if changed:
        query = query.filter(
            or_(
                func.round(AthleteRating.rating)
                != func.round(AthleteRating.previous_rating),
                AthleteRating.previous_rank.is_(None),
            )
        )
    if upcoming:
        subquery = (
            db.session.query(Athlete.id)
            .select_from(Athlete)
            .join(
                RegistrationLinkCompetitor,
                RegistrationLinkCompetitor.athlete_name == Athlete.name,
            )
            .join(
                RegistrationLink,
                RegistrationLinkCompetitor.registration_link_id == RegistrationLink.id,
            )
            .filter(RegistrationLink.event_start_date > datetime.now())
        )
        query = query.filter(Athlete.id.in_(subquery))

    totalCount = query.count()

    query = (
        query.order_by(AthleteRating.rank, AthleteRating.match_happened_at.desc())
        .limit(RATINGS_PAGE_SIZE)
        .offset((page - 1) * RATINGS_PAGE_SIZE)
    )
    results = query.all()

    athlete_names = [result.name for result in results]
    reg_link_rows = (
        db.session.query(
            RegistrationLinkCompetitor.athlete_name,
            RegistrationLink.name,
            RegistrationLink.event_start_date,
            RegistrationLink.event_end_date,
            RegistrationLink.link,
            RegistrationLink.event_id,
            Division.belt,
            Division.age,
            Division.gender,
            Division.weight,
        )
        .join(
            RegistrationLink,
            RegistrationLinkCompetitor.registration_link_id == RegistrationLink.id,
        )
        .join(Division, RegistrationLinkCompetitor.division_id == Division.id)
        .filter(
            RegistrationLinkCompetitor.athlete_name.in_(athlete_names),
            RegistrationLink.event_end_date >= datetime.now(),
        )
        .order_by(
            RegistrationLinkCompetitor.athlete_name,
            RegistrationLink.event_start_date,
            RegistrationLink.name,
        )
        .all()
    )

    # Map athlete_name to a list of their registration links
    reg_links_by_athlete = {}
    for row in reg_link_rows:
        entry = {
            "event_name": row.name,
            "division": f"{row.belt} / {row.age} / {row.gender} / {row.weight}",
            "event_start_date": row.event_start_date.strftime("%Y-%m-%d"),
            "event_end_date": row.event_end_date.strftime("%Y-%m-%d"),
            "link": row.link,
            "event_id": row.event_id,
        }
        reg_links_by_athlete.setdefault(row.athlete_name, []).append(entry)

    response = [
        {
            "rank": result.rank,
            "athlete_id": result.id,
            "name": result.name,
            "slug": result.slug,
            "instagram_profile": result.instagram_profile,
            "personal_name": result.personal_name,
            "profile_image_url": (
                get_public_photo_url(s3_client, result)
                if result.profile_image_saved_at
                else None
            ),
            "country": result.country,
            "country_note": result.country_note,
            "country_note_pt": result.country_note_pt,
            "rating": round(result.rating),
            "match_count": result.match_count,
            "previous_rating": (
                None
                if result.previous_rating is None
                else round(result.previous_rating)
            ),
            "previous_rank": result.previous_rank,
            "previous_match_count": result.previous_match_count,
            "registrations": reg_links_by_athlete.get(result.name, []),
        }
        for result in results
    ]

    return jsonify(
        {"rows": response, "totalPages": math.ceil(totalCount / RATINGS_PAGE_SIZE)}
    )
