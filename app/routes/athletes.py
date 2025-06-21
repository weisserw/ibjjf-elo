from flask import Blueprint, request, jsonify
from sqlalchemy.sql import exists
from extensions import db
from models import Athlete, MatchParticipant, Match, Division
from normalize import normalize
from elo import EloCompetitor, AGE_K_FACTOR_MODIFIERS, weight_handicaps
from constants import (
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
    TEEN_1,
    TEEN_2,
    TEEN_3,
)

athletes_route = Blueprint("athletes_route", __name__)

MAX_RESULTS = 50


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

    return jsonify(info)


@athletes_route.route("/api/athletes")
def athletes():
    search = normalize(request.args.get("search", ""))
    gi = request.args.get("gi")
    gender = request.args.get("gender")
    allowteen = request.args.get("allow_teen", "")

    query = db.session.query(Athlete.name).filter(
        Athlete.normalized_name.like(f"{search}%")
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

    query = query.order_by(Athlete.name).limit(MAX_RESULTS)
    results = query.all()

    unique_names = set(result.name for result in results)

    if len(results) < MAX_RESULTS:
        remaining_count = MAX_RESULTS - len(results)
        additional_query = db.session.query(Athlete.name)
        for name_part in search.split():
            additional_query = additional_query.filter(
                Athlete.normalized_name.like(f"%{name_part}%")
            )
        if gi:
            additional_query = additional_query.filter(
                exists().where(Athlete.id == subquery_gi.c.athlete_id)
            )
        if gender:
            additional_query = additional_query.filter(
                exists().where(Athlete.id == subquery_gender.c.athlete_id)
            )
        additional_query = additional_query.order_by(Athlete.name).limit(
            remaining_count
        )
        additional_results = additional_query.all()
        for result in additional_results:
            if result.name not in unique_names:
                results.append(result)
                unique_names.add(result.name)

    response = [result.name for result in results]

    return jsonify(response)
