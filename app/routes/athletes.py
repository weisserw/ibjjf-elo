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
    Suspension,
)
from normalize import normalize
from team_name_mapping import load_team_name_mappings, resolve_dupe_team_name
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
    ADULT,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    MASTER_PREFIX,
    TEEN_1,
    TEEN_2,
    TEEN_3,
    BLACK,
    WHITE,
    BLUE,
)
from photos import get_s3_client, get_public_photo_url

athletes_route = Blueprint("athletes_route", __name__)

MAX_RESULTS = 50
NAVBAR_MAX_RESULTS = 12
YOUTH_AGE_DIVISIONS = {
    TEEN_1,
    TEEN_2,
    TEEN_3,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
}


def _parse_gi_flag(raw_gi):
    if raw_gi is None:
        return True
    return raw_gi.lower() == "true"


def _resolve_athlete(identifier):
    try:
        id_uuid = UUID(identifier)
        athlete = Athlete.query.get(id_uuid)
        return athlete, id_uuid
    except ValueError:
        athlete = Athlete.query.filter_by(slug=identifier).first()
        return (athlete, athlete.id) if athlete else (None, None)


def _compute_highest_belt(base_belt, registration_belts, promotion_belts):
    highest_belt = base_belt
    for belt in registration_belts + promotion_belts:
        if highest_belt is None or belt_order.index(belt) > belt_order.index(
            highest_belt
        ):
            highest_belt = belt
    return highest_belt


def _clamp_legacy_team_history_date(happened_at):
    if happened_at is None:
        return None

    if happened_at < datetime(2025, 2, 1):
        return datetime(happened_at.year, 1, 1)

    return happened_at


def _get_athlete_team_history(athlete_id):
    team_events = []
    exact_mappings, glob_mappings = load_team_name_mappings()

    medal_rows = (
        db.session.query(
            Medal.happened_at.label("happened_at"),
            Team.name.label("team_name"),
        )
        .join(Team, Team.id == Medal.team_id)
        .filter(Medal.athlete_id == athlete_id, Team.name.isnot(None), Team.name != "")
        .all()
    )
    for row in medal_rows:
        team_name = (row.team_name or "").strip()
        if not team_name:
            continue
        team_name = resolve_dupe_team_name(team_name, exact_mappings, glob_mappings)
        team_events.append(
            {
                "date": _clamp_legacy_team_history_date(row.happened_at),
                "team_name": team_name,
            }
        )

    match_rows = (
        db.session.query(
            Match.happened_at.label("happened_at"),
            Team.name.label("team_name"),
        )
        .select_from(MatchParticipant)
        .join(Match, Match.id == MatchParticipant.match_id)
        .join(Team, Team.id == MatchParticipant.team_id)
        .filter(
            MatchParticipant.athlete_id == athlete_id,
            Team.name.isnot(None),
            Team.name != "",
        )
        .all()
    )
    for row in match_rows:
        team_name = (row.team_name or "").strip()
        if not team_name:
            continue
        team_name = resolve_dupe_team_name(team_name, exact_mappings, glob_mappings)
        team_events.append(
            {
                "date": _clamp_legacy_team_history_date(row.happened_at),
                "team_name": team_name,
            }
        )

    sorted_team_events = sorted(
        team_events,
        key=lambda row: row["date"],
    )

    # Group teams by clamped date, preserving first appearance order.
    teams_by_date = {}
    ordered_dates = []

    for row in sorted_team_events:
        event_date = row["date"]
        if event_date is None:
            continue
        date_key = event_date.strftime("%Y-%m-%d")
        if date_key not in teams_by_date:
            teams_by_date[date_key] = []
            ordered_dates.append(date_key)
        teams_by_date[date_key].append(row["team_name"])

    # Per date bucket, keep all unique teams in original order.
    unique_teams_by_date = {}
    for date_key in ordered_dates:
        seen = set()
        unique_teams = []
        for team_name in teams_by_date[date_key]:
            if team_name in seen:
                continue
            seen.add(team_name)
            unique_teams.append(team_name)
        unique_teams_by_date[date_key] = unique_teams

    team_set_by_date = {
        date_key: set(unique_teams_by_date[date_key]) for date_key in ordered_dates
    }

    def _team_priority(in_prev, in_next):
        if in_prev and not in_next:
            return 0
        if in_prev and in_next:
            return 0
        if not in_prev and not in_next:
            return 1
        return 2

    # Reorder each date bucket using neighboring date membership as signal.
    reordered_teams_by_date = {}
    for idx, date_key in enumerate(ordered_dates):
        prev_teams = team_set_by_date[ordered_dates[idx - 1]] if idx > 0 else set()
        next_teams = (
            team_set_by_date[ordered_dates[idx + 1]]
            if idx < len(ordered_dates) - 1
            else set()
        )
        unique_teams = unique_teams_by_date[date_key]
        indexed_teams = list(enumerate(unique_teams))
        ranked_teams = sorted(
            indexed_teams,
            key=lambda item: (
                _team_priority(
                    item[1] in prev_teams,
                    item[1] in next_teams,
                ),
                item[0],
            ),
        )
        reordered_teams_by_date[date_key] = [team_name for _, team_name in ranked_teams]

    flattened_history = []
    for date_key in ordered_dates:
        for team_name in reordered_teams_by_date[date_key]:
            flattened_history.append(
                {
                    "date": date_key,
                    "team_name": team_name,
                }
            )

    # Only remove adjacent duplicates across the flattened timeline.
    team_history = []
    last_team_name = None
    for row in flattened_history:
        current_team_name = row["team_name"]
        if current_team_name == last_team_name:
            continue
        team_history.append(row)
        last_team_name = current_team_name

    team_history.reverse()
    return team_history


def _apply_promotion_rating_bump(rating, from_belt, to_belt):
    print(
        f"Applying promotion rating bump: rating={rating}, from_belt={from_belt}, to_belt={to_belt}"
    )
    if rating is None or not from_belt or not to_belt or from_belt == to_belt:
        return rating

    if from_belt == WHITE and to_belt == BLUE:
        belt_diff = 1  # special case to skip kids belts
    else:
        belt_diff = belt_order.index(to_belt) - belt_order.index(from_belt)
    if belt_diff == 1:
        if to_belt == BLACK:
            return rating + BLACK_PROMOTION_RATING_BUMP
        return rating + COLOR_PROMOTION_RATING_BUMP

    return rating


def get_athlete_data(identifier, gi_param=None):
    athlete, id_uuid = _resolve_athlete(identifier)
    if not athlete:
        return None

    gi = _parse_gi_flag(gi_param)

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
            .filter(MatchParticipant.end_rating != 0)
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

    athlete_has_adult_or_master_history = (
        db.session.query(MatchParticipant.id)
        .join(Match)
        .join(Division)
        .filter(MatchParticipant.athlete_id == athlete.id)
        .filter(or_(Division.age == ADULT, Division.age.like(f"{MASTER_PREFIX}%")))
        .first()
        is not None
    )

    # load registrations and manual promotions
    registrations_query = (
        db.session.query(
            RegistrationLinkCompetitor.team_name,
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
    )
    if athlete_has_adult_or_master_history:
        registrations_query = registrations_query.filter(
            ~Division.age.in_(YOUTH_AGE_DIVISIONS)
        )
    registrations = registrations_query.order_by(
        RegistrationLink.event_start_date,
        RegistrationLink.name,
    ).all()
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
        # determine highest belt from matches, registrations, and promotions
        highest_belt = None

        # need to query both gi and no-gi since belt is independent of gi
        mp = (
            db.session.query(Division.belt)
            .select_from(MatchParticipant)
            .join(Match)
            .join(Division)
            .join(Team)
            .filter(MatchParticipant.athlete_id == athlete.id)
            .order_by(Match.happened_at.desc())
            .first()
        )
        if mp:
            highest_belt = mp.belt
        registration_belts = [reg.belt for reg in registrations]
        promotion_belts = [promo.belt for promo in promotions]
        highest_belt = _compute_highest_belt(
            highest_belt, registration_belts, promotion_belts
        )

        # if there are no matches, rating is null
        if len(elo_history) == 0:
            rating = None
        elif highest_belt:
            rating = elo_history[-1]["Rating"]
            rating = _apply_promotion_rating_bump(
                rating, elo_history[-1]["belt"], highest_belt
            )

    filtered_registrations = registrations
    if highest_belt and highest_belt in belt_order:
        current_belt_index = belt_order.index(highest_belt)
        filtered_registrations = [
            reg
            for reg in registrations
            if reg.belt in belt_order
            and belt_order.index(reg.belt) >= current_belt_index
        ]

    registration_team_name = next(
        (row.team_name for row in reversed(filtered_registrations) if row.team_name),
        None,
    )
    if registration_team_name:
        team_name = registration_team_name

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
        .filter(Medal.default_gold == False)
        .filter(Division.gi == gi)
        .filter(
            or_(  # OR conditions for valid medals
                and_(  # athletes won a match in the same event/division they got a medal in
                    db.session.query(Match)
                    .join(MatchParticipant)
                    .filter(
                        Match.event_id == Medal.event_id,
                        Match.division_id == Medal.division_id,
                        Match.rated == True,
                        MatchParticipant.match_id == Match.id,
                        MatchParticipant.athlete_id == Medal.athlete_id,
                        MatchParticipant.winner == True,
                    )
                    .exists(),
                ),
                and_(  # athletes got 2nd place and there is a 3rd place medal awarded in that event/division (for tournaments where we have medals but no matches)
                    Medal.place == 2,
                    db.session.query(MedalAlias)
                    .filter(
                        MedalAlias.event_id == Medal.event_id,
                        MedalAlias.division_id == Medal.division_id,
                        MedalAlias.place == 3,
                    )
                    .exists(),
                ),
                and_(  # athletes got 1st place and there is a 2nd OR 3rd place medal awarded in that event/division (for tournaments where we have medals but no matches)
                    Medal.place == 1,
                    db.session.query(MedalAlias)
                    .filter(
                        MedalAlias.event_id == Medal.event_id,
                        MedalAlias.division_id == Medal.division_id,
                        or_(
                            MedalAlias.place == 2,
                            MedalAlias.place == 3,
                        ),
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
            "happened_at": r.happened_at.strftime("%Y-%m-%d"),
        }
        for r in (medal_query.distinct().all())
    ]

    athlete_json = {
        "id": str(athlete.id),
        "name": athlete.name,
        "slug": athlete.slug,
        "instagram_profile": athlete.instagram_profile,
        "personal_name": athlete.personal_name,
        "nickname_translation": athlete.nickname_translation,
        "bjjheroes_link": athlete.bjjheroes_link,
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
    for row in filtered_registrations:
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

    suspensions = [
        {
            "start_date": s.start_date.strftime("%Y-%m-%d"),
            "end_date": s.end_date.strftime("%Y-%m-%d"),
            "reason": s.reason,
            "suspending_org": s.suspending_org,
        }
        for s in db.session.query(Suspension)
        .filter(Suspension.athlete_name == athlete.name)
        .all()
    ]
    team_history = _get_athlete_team_history(id_uuid)

    return {
        "athlete": athlete_json,
        "eloHistory": filtered_elo_history,
        "ranks": ranks,
        "registrations": registrations_list,
        "medals": medals,
        "teamHistory": team_history,
        "suspensions": suspensions,
    }


@athletes_route.route("/api/athlete/<id>")
def get_athlete(id):
    athlete_data = get_athlete_data(id, request.args.get("gi"))
    if athlete_data is None:
        return jsonify({"error": "Athlete not found"}), 404

    return jsonify(athlete_data), 200


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
        "team_history": [],
    }
    last_match_belt = None
    for rating in weight_query.order_by(Match.happened_at.desc()).limit(1).all():
        info["weight"] = rating.weight

    for rating in query.order_by(Match.happened_at.desc()).limit(1).all():
        info["rating"] = rating.end_rating
        info["age"] = rating.age
        info["belt"] = rating.belt
        info["id"] = rating.athlete_id
        info["slug"] = rating.slug
        last_match_belt = rating.belt

    if info["id"] and last_match_belt:
        athlete = db.session.get(Athlete, info["id"])
        if athlete:
            info["team_history"] = _get_athlete_team_history(info["id"])
            registrations = (
                db.session.query(Division.belt)
                .select_from(RegistrationLinkCompetitor)
                .join(
                    RegistrationLink,
                    RegistrationLinkCompetitor.registration_link_id
                    == RegistrationLink.id,
                )
                .join(Division, RegistrationLinkCompetitor.division_id == Division.id)
                .filter(
                    RegistrationLinkCompetitor.athlete_name == athlete.name,
                    RegistrationLink.event_end_date >= datetime.now(),
                )
                .all()
            )
            promotions = (
                db.session.query(ManualPromotions)
                .filter(ManualPromotions.athlete_id == info["id"])
                .all()
            )

            registration_belts = [reg.belt for reg in registrations]
            promotion_belts = [promo.belt for promo in promotions]
            highest_belt = _compute_highest_belt(
                last_match_belt, registration_belts, promotion_belts
            )
            info["rating"] = _apply_promotion_rating_bump(
                info["rating"], last_match_belt, highest_belt
            )

            if highest_belt:
                info["belt"] = highest_belt

    elif info["id"]:
        info["team_history"] = _get_athlete_team_history(info["id"])

    return jsonify(info)


@athletes_route.route("/api/athletes")
def athletes():
    search = normalize(request.args.get("search", ""))
    gi = request.args.get("gi")
    gender = request.args.get("gender")
    allowteen = request.args.get("allow_teen", "")

    query = _build_athlete_search_query(
        search=search,
        gi=gi,
        gender=gender,
        allow_teen=allowteen.lower() == "true",
    )

    results = (
        query.order_by(Athlete.personal_name.isnot(None).desc(), Athlete.name)
        .limit(MAX_RESULTS)
        .all()
    )

    response = [
        {
            "slug": result.slug,
            "name": result.name,
            "personal_name": result.personal_name,
        }
        for result in results
    ]

    return jsonify(response)


def _team_slug_from_name(name):
    normalized = normalize(name)
    return normalized.replace(" ", "-")


def _build_team_search_suggestions(search, limit=MAX_RESULTS):
    team_query = db.session.query(Team.name).filter(
        Team.name.isnot(None), Team.name != ""
    )
    for name_part in search.split():
        team_query = team_query.filter(Team.normalized_name.like(f"%{name_part}%"))

    exact_mappings, glob_mappings = load_team_name_mappings()
    canonical_teams = {}
    for (team_name,) in team_query.order_by(Team.name).limit(limit).all():
        canonical_name = resolve_dupe_team_name(
            team_name, exact_mappings, glob_mappings
        )
        team_slug = _team_slug_from_name(canonical_name)
        if not canonical_name or not team_slug:
            continue
        canonical_teams[canonical_name] = team_slug

    return [{"name": name, "slug": slug} for name, slug in canonical_teams.items()]


def _build_athlete_search_query(search, gi=None, gender=None, allow_teen=False):
    if os.getenv("DATABASE_URL"):
        # Use full-text search
        search_terms = [term + ":*" for term in search.split()]
        ts_query = func.to_tsquery("simple", " & ".join(search_terms))
        query = db.session.query(
            Athlete.slug, Athlete.name, Athlete.personal_name
        ).filter(
            or_(
                Athlete.normalized_name_tsvector.op("@@")(ts_query),
                Athlete.normalized_personal_name_tsvector.op("@@")(ts_query),
            )
        )
    else:
        # Fallback to LIKE search
        query = db.session.query(Athlete.slug, Athlete.name, Athlete.personal_name)
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

    if not allow_teen:
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

    return query


@athletes_route.route("/api/navbar-search")
def navbar_search():
    search = normalize(request.args.get("search", ""))
    if not search:
        return jsonify([])

    athlete_rows = (
        _build_athlete_search_query(search=search)
        .order_by(Athlete.personal_name.isnot(None).desc(), Athlete.name)
        .limit(MAX_RESULTS)
        .all()
    )
    athlete_suggestions = [
        {
            "type": "athlete",
            "slug": row.slug,
            "name": row.name,
            "personal_name": row.personal_name,
        }
        for row in athlete_rows
    ]

    team_suggestions = [
        {"type": "team", "name": row["name"], "slug": row["slug"]}
        for row in _build_team_search_suggestions(search=search)
    ]

    response = athlete_suggestions[:NAVBAR_MAX_RESULTS]
    remaining_slots = NAVBAR_MAX_RESULTS - len(response)
    if remaining_slots > 0:
        response.extend(team_suggestions[:remaining_slots])

    return jsonify(response)
