import os
from datetime import datetime
from flask import Blueprint, request, jsonify
from uuid import UUID
from sqlalchemy import and_, func, or_
from sqlalchemy.sql import exists
from sqlalchemy.orm import aliased
from extensions import db
from models import (
    Athlete,
    MatchParticipant,
    Match,
    Division,
    RegistrationLink,
    Team,
    AthleteRating,
    AthleteRatingAverage,
    ManualPromotions,
    RegistrationLinkCompetitor,
    Medal,
    Event,
)
from normalize import normalize
from elo import (
    EloCompetitor,
    AGE_K_FACTOR_MODIFIERS,
    weight_handicaps,
    RATING_VERY_IMMATURE_COUNT,
    belt_order,
    BLACK_PROMOTION_RATING_BUMP,
    COLOR_PROMOTION_RATING_BUMP,
)
from constants import (
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
    TEEN_1,
    TEEN_2,
    TEEN_3,
    BLACK,
)
from photos import get_s3_client, get_public_photo_url

athletes_route = Blueprint("athletes_route", __name__)

MAX_RESULTS = 50


@athletes_route.route("/api/athlete/<id>")
def get_athlete(id):
    try:
        id_uuid = UUID(id)
        athlete = Athlete.query.get(id_uuid)
        if not athlete:
            return jsonify({"error": "Athlete not found"}), 404
    except ValueError:
        athlete = Athlete.query.filter_by(slug=id).first()
        if not athlete:
            return jsonify({"error": "Athlete not found"}), 404
        id_uuid = athlete.id

    gi = request.args.get("gi")

    gi = gi.lower() == "true" if gi else True

    athlete = Athlete.query.get(id_uuid)
    if not athlete:
        return jsonify({"error": "Athlete not found"}), 404

    # load elo over time data
    elo_history = [
        {
            "date": mp.match.happened_at.strftime("%Y-%m-%d"),
            "team": mp.team.name,
            "belt": mp.match.division.belt,
            "age": mp.match.division.age,
            "Rating": round(mp.end_rating) if mp.end_rating is not None else None,
        }
        for mp in (
            db.session.query(MatchParticipant)
            .join(Match)
            .join(Division)
            .join(Team)
            .filter(Division.gi == gi)
            .filter(MatchParticipant.athlete_id == athlete.id)
            .order_by(Match.happened_at)
            .all()
        )
    ]

    team_name = None
    if len(elo_history):
        team_name = elo_history[-1]["team"]

    # remove duplicates keeping the latest rating for each date
    unique_elo_history = []
    last_date = None
    for entry in elo_history:
        if entry["date"] != last_date:
            unique_elo_history.append(entry)
            last_date = entry["date"]
        else:
            unique_elo_history[-1]["Rating"] = entry["Rating"]

    # remove any dates where elo didn't change
    filtered_elo_history = []
    last_rating = None
    for entry in unique_elo_history:
        if entry["Rating"] != last_rating:
            filtered_elo_history.append(entry)
            last_rating = entry["Rating"]

    # load all ranks
    ranks = [
        {
            "rank": r.rank,
            "rating": round(r.rating),
            "percentile": r.percentile,
            "age": r.age,
            "belt": r.belt,
            "weight": r.weight,
            "gender": r.gender,
            "avg_rating": round(r.avg_rating),
        }
        for r in (
            db.session.query(
                AthleteRating.rank,
                AthleteRating.rating,
                AthleteRating.percentile,
                AthleteRating.age,
                AthleteRating.belt,
                AthleteRating.weight,
                AthleteRating.gender,
                AthleteRatingAverage.avg_rating,
            )
            .join(
                AthleteRatingAverage,
                and_(
                    AthleteRatingAverage.gender == AthleteRating.gender,
                    AthleteRatingAverage.gi == AthleteRating.gi,
                    AthleteRatingAverage.age == AthleteRating.age,
                    AthleteRatingAverage.belt == AthleteRating.belt,
                    AthleteRatingAverage.weight == AthleteRating.weight,
                    AthleteRatingAverage.gender == AthleteRating.gender,
                ),
            )
            .filter(AthleteRating.athlete_id == id_uuid)
            .filter(AthleteRating.gi == gi)
            .filter(AthleteRating.match_count > RATING_VERY_IMMATURE_COUNT)
            .filter(AthleteRating.rank.isnot(None))
        )
    ]

    # load registrations and manual promotions
    registrations = (
        db.session.query(
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
        .select_from(RegistrationLinkCompetitor)
        .join(
            RegistrationLink,
            RegistrationLinkCompetitor.registration_link_id == RegistrationLink.id,
        )
        .join(Division, RegistrationLinkCompetitor.division_id == Division.id)
        .filter(
            RegistrationLinkCompetitor.athlete_name == athlete.name,
            RegistrationLink.event_end_date >= datetime.now(),
        )
        .order_by(
            RegistrationLink.event_end_date,
            RegistrationLink.name,
        )
        .all()
    )
    promotions = (
        db.session.query(ManualPromotions)
        .filter(ManualPromotions.athlete_id == id_uuid)
        .all()
    )

    # if they have ranks, use the belt and rating from there
    if len(ranks):
        rating = ranks[0]["rating"]
        highest_belt = ranks[0]["belt"]
    else:
        # determine highest belt from mathes, registrations, and promotions
        highest_belt = None
        if len(elo_history):
            highest_belt = elo_history[-1]["belt"]
        for reg in registrations:
            if highest_belt is None or belt_order.index(reg.belt) > belt_order.index(
                highest_belt
            ):
                highest_belt = reg.belt
        for promo in promotions:
            if highest_belt is None or belt_order.index(promo.belt) > belt_order.index(
                highest_belt
            ):
                highest_belt = promo.belt

        # if there are no matches, rating is null
        if len(elo_history) == 0:
            rating = None
        elif highest_belt:
            rating = elo_history[-1]["Rating"]

            if rating is not None and elo_history[-1]["belt"] != highest_belt:
                # adjust rating based on belt difference, can't do more than one belt here
                # since we don't know their age, so just leave it alone in that case
                belt_diff = belt_order.index(highest_belt) - belt_order.index(
                    elo_history[-1]["belt"]
                )
                if belt_diff == 1:
                    if highest_belt == BLACK:
                        rating += BLACK_PROMOTION_RATING_BUMP
                    else:
                        rating += COLOR_PROMOTION_RATING_BUMP

    MedalAlias = aliased(Medal)
    medal_query = (
        db.session.query(
            Medal.place,
            Medal.happened_at,
            Event.name,
            Event.medals_only,
            Division.belt,
            Division.age,
            Division.gender,
            Division.weight,
        )
        .select_from(Medal)
        .join(Event)
        .join(Division)
        .filter(Medal.athlete_id == id_uuid)
        .filter(Division.gi == gi)
        .filter(
            or_(
                Medal.place == 1,
                and_(
                    Medal.place != 1,
                    db.session.query(Match)
                    .join(MatchParticipant)
                    .filter(
                        Match.event_id == Medal.event_id,
                        Match.division_id == Medal.division_id,
                        MatchParticipant.match_id == Match.id,
                        MatchParticipant.athlete_id == Medal.athlete_id,
                        MatchParticipant.winner == True,
                    )
                    .exists(),
                ),
                and_(
                    Medal.place == 2,
                    db.session.query(MedalAlias)
                    .filter(
                        MedalAlias.event_id == Medal.event_id,
                        MedalAlias.division_id == Medal.division_id,
                        MedalAlias.place == 3,
                    )
                    .exists(),
                ),
            )
        )
    )

    medals = [
        {
            "place": r.place,
            "event_name": r.name,
            "event_medals_only": r.medals_only,
            "division": f"{r.belt} / {r.age} / {r.gender} / {r.weight}",
        }
        for r in (
            medal_query.distinct().order_by(Medal.place, Medal.happened_at.desc()).all()
        )
    ]

    athlete_json = {
        "id": str(athlete.id),
        "name": athlete.name,
        "instagram_profile": athlete.instagram_profile,
        "personal_name": athlete.personal_name,
        "instagram_profile_photo_url": None,
        "country": athlete.country,
        "country_note": athlete.country_note,
        "country_note_pt": athlete.country_note_pt,
        "team_name": team_name,
        "belt": highest_belt,
        "rating": rating,
    }

    if athlete.profile_image_saved_at is not None:
        s3_client = get_s3_client()
        photo_url = get_public_photo_url(s3_client, athlete)
        athlete_json["instagram_profile_photo_url"] = photo_url

    registrations_list = []
    for row in registrations:
        registrations_list.append(
            {
                "event_name": row.name,
                "division": f"{row.belt} / {row.age} / {row.gender} / {row.weight}",
                "event_start_date": row.event_start_date.strftime("%Y-%m-%d"),
                "event_end_date": row.event_end_date.strftime("%Y-%m-%d"),
                "link": row.link,
                "event_id": row.event_id,
            }
        )

    return (
        jsonify(
            {
                "athlete": athlete_json,
                "eloHistory": filtered_elo_history,
                "ranks": ranks,
                "registrations": registrations_list,
                "medals": medals,
            }
        ),
        200,
    )


@athletes_route.route("/api/athletes/predict")
def predict():
    rating1 = request.args.get("rating1")
    rating2 = request.args.get("rating2")
    weight1 = request.args.get("weight1")
    weight2 = request.args.get("weight2")
    belt = request.args.get("belt")
    age = request.args.get("age")

    if rating1 is None or rating2 is None or rating1 == "" or rating2 == "":
        return jsonify({"error": "Both ratings are required"}), 400
    if weight1 is None or weight2 is None:
        weight1 = weight2 = "Middle"
    if belt is None:
        belt = "BLACK"
    if age is None:
        age = "Adult"

    red_start_rating = float(rating1)
    blue_start_rating = float(rating2)
    red_k_factor = 32
    blue_k_factor = 32
    if age in AGE_K_FACTOR_MODIFIERS:
        red_k_factor *= AGE_K_FACTOR_MODIFIERS[age]
        blue_k_factor *= AGE_K_FACTOR_MODIFIERS[age]
    red_handicap = 0
    blue_handicap = 0
    if weight1 != weight2:
        red_handicap, blue_handicap = weight_handicaps(belt, weight1, weight2)

    red_elo_win = EloCompetitor(red_start_rating + red_handicap, red_k_factor)
    red_elo_loss = EloCompetitor(red_start_rating + red_handicap, red_k_factor)
    red_elo_tie = EloCompetitor(red_start_rating + red_handicap, red_k_factor)
    blue_elo_win = EloCompetitor(blue_start_rating + blue_handicap, blue_k_factor)
    blue_elo_loss = EloCompetitor(blue_start_rating + blue_handicap, blue_k_factor)
    blue_elo_tie = EloCompetitor(blue_start_rating + blue_handicap, blue_k_factor)

    red_expected = red_elo_win.expected_score(blue_elo_win)
    blue_expected = blue_elo_win.expected_score(red_elo_win)
    red_elo_win.beat(blue_elo_loss)
    blue_elo_win.beat(red_elo_loss)
    red_elo_tie.tied(blue_elo_tie)

    return jsonify(
        {
            "first_expected": red_expected,
            "second_expected": blue_expected,
            "first_win": red_elo_win.rating - red_start_rating - red_handicap,
            "second_win": blue_elo_win.rating - blue_start_rating - blue_handicap,
            "first_loss": red_elo_loss.rating - red_start_rating - red_handicap,
            "second_loss": blue_elo_loss.rating - blue_start_rating - blue_handicap,
            "first_tie": red_elo_tie.rating - red_start_rating - red_handicap,
            "second_tie": blue_elo_tie.rating - blue_start_rating - blue_handicap,
            "red_handicap": red_handicap,
            "blue_handicap": blue_handicap,
            "red_k_factor": red_k_factor,
            "blue_k_factor": blue_k_factor,
        }
    )


@athletes_route.route("/api/athletes/ratings")
def ratings():
    name = normalize(request.args.get("name", ""))
    gi = request.args.get("gi")

    if not name or not gi:
        return jsonify({"error": "Missing parameter"}), 400

    gi = gi.lower() == "true"

    query = (
        db.session.query(
            Athlete.slug,
            MatchParticipant.athlete_id,
            MatchParticipant.end_rating,
            Division.age,
            Division.belt,
        )
        .select_from(MatchParticipant)
        .join(Match)
        .join(Division)
        .join(Athlete)
        .filter(Athlete.normalized_name == name)
        .filter(Division.gi == gi)
        .filter(Division.age != TEEN_1)
        .filter(Division.age != TEEN_2)
        .filter(Division.age != TEEN_3)
    )

    weight_query = (
        db.session.query(
            Division.weight,
        )
        .select_from(MatchParticipant)
        .join(Match)
        .join(Division)
        .join(Athlete)
        .filter(Athlete.normalized_name == name)
        .filter(Division.gi == gi)
        .filter(Division.weight != OPEN_CLASS)
        .filter(Division.weight != OPEN_CLASS_HEAVY)
        .filter(Division.weight != OPEN_CLASS_LIGHT)
        .filter(Division.age != TEEN_1)
        .filter(Division.age != TEEN_2)
        .filter(Division.age != TEEN_3)
    )

    info = {
        "id": None,
        "slug": None,
        "rating": None,
        "age": None,
        "weight": None,
        "belt": None,
    }
    for rating in weight_query.order_by(Match.happened_at.desc()).limit(1).all():
        info["weight"] = rating.weight

    for rating in query.order_by(Match.happened_at.desc()).limit(1).all():
        info["rating"] = rating.end_rating
        info["age"] = rating.age
        info["belt"] = rating.belt
        info["id"] = rating.athlete_id
        info["slug"] = rating.slug

    return jsonify(info)


@athletes_route.route("/api/athletes")
def athletes():
    search = normalize(request.args.get("search", ""))
    gi = request.args.get("gi")
    gender = request.args.get("gender")
    allowteen = request.args.get("allow_teen", "")

    if os.getenv("DATABASE_URL"):
        # Use full-text search
        search_terms = [term + ":*" for term in search.split()]
        ts_query = func.to_tsquery("simple", " & ".join(search_terms))
        query = db.session.query(Athlete.name, Athlete.personal_name).filter(
            or_(
                Athlete.normalized_name_tsvector.op("@@")(ts_query),
                Athlete.normalized_personal_name_tsvector.op("@@")(ts_query),
            )
        )
    else:
        # Fallback to LIKE search
        query = db.session.query(Athlete.name, Athlete.personal_name)
        for name_part in search.split():
            query = query.filter(
                or_(
                    Athlete.normalized_name.like(f"%{name_part}%"),
                    Athlete.normalized_personal_name.like(f"%{name_part}%"),
                )
            )

    if gi:
        gi = gi.lower() == "true"
        subquery_gi = (
            db.session.query(MatchParticipant.athlete_id)
            .join(Match)
            .join(Division)
            .filter(
                Division.gi == gi,
            )
            .subquery()
        )

        query = query.filter(exists().where(Athlete.id == subquery_gi.c.athlete_id))

    if gender:
        subquery_gender = (
            db.session.query(MatchParticipant.athlete_id)
            .join(Match)
            .join(Division)
            .filter(
                Division.gender == gender,
            )
            .subquery()
        )

        query = query.filter(exists().where(Athlete.id == subquery_gender.c.athlete_id))

    if not (allowteen.lower() == "true"):
        # use subquery to remove athletes whose most recent match was in a teen division
        recent_match_subq = (
            db.session.query(Match.happened_at)
            .join(MatchParticipant, Match.id == MatchParticipant.match_id)
            .filter(MatchParticipant.athlete_id == Athlete.id)
            .order_by(Match.happened_at.desc())
            .limit(1)
            .correlate(Athlete)
            .scalar_subquery()
        )

        teen_recent_match_exists = (
            db.session.query(MatchParticipant.id)
            .join(Match)
            .join(Division)
            .filter(
                MatchParticipant.athlete_id == Athlete.id,
                Division.age.in_([TEEN_1, TEEN_2, TEEN_3]),
                Match.happened_at == recent_match_subq,
            )
            .exists()
        )

        query = query.filter(~teen_recent_match_exists)

    results = (
        query.order_by(Athlete.personal_name.isnot(None).desc(), Athlete.name)
        .limit(MAX_RESULTS)
        .all()
    )

    response = [
        {"name": result.name, "personal_name": result.personal_name}
        for result in results
    ]

    return jsonify(response)
