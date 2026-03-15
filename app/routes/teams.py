from flask import Blueprint, jsonify, request
from sqlalchemy import case, func
from datetime import datetime
from extensions import db
from constants import NON_ELITE_BELTS, belt_order
from team_name_mapping import load_team_name_mappings, resolve_dupe_team_name
from normalize import normalize
from models import (
    Athlete,
    AthleteRating,
    MatchParticipant,
    Match,
    Medal,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Team,
)

teams_route = Blueprint("teams_route", __name__)


def _team_slug_to_normalized_name(team_slug):
    return team_slug.replace("-", " ").strip()


def _glob_to_sql_like(name_match):
    # Escape LIKE wildcard characters first, then map glob wildcard chars.
    escaped = name_match.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")


def _team_slug_from_name(name):
    normalized = normalize(name)
    return normalized.replace(" ", "-")


def _build_team_search_suggestions(search, limit=50):
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


@teams_route.route("/api/teams/search")
def team_search():
    search = normalize(request.args.get("search", ""))
    if not search:
        return jsonify([])

    return jsonify(_build_team_search_suggestions(search=search))


@teams_route.route("/api/teams/<team_slug>")
def get_team(team_slug):
    normalized_name = _team_slug_to_normalized_name(team_slug)

    team = Team.query.filter(Team.normalized_name == normalized_name).first()
    if team is None:
        return jsonify({"error": "Team not found"}), 404

    team_ids = {team.id}

    exact_mappings, glob_mappings = load_team_name_mappings()
    for name_match, mapped_name in exact_mappings.items():
        if mapped_name != team.name:
            continue
        like_pattern = _glob_to_sql_like(name_match)
        mapped_team_ids = (
            db.session.query(Team.id)
            .filter(Team.name.like(like_pattern, escape="\\"))
            .all()
        )
        for (mapped_team_id,) in mapped_team_ids:
            team_ids.add(mapped_team_id)
    for pattern, mapped_name in glob_mappings:
        if mapped_name != team.name:
            continue
        like_pattern = _glob_to_sql_like(pattern)
        mapped_team_ids = (
            db.session.query(Team.id)
            .filter(Team.name.like(like_pattern, escape="\\"))
            .all()
        )
        for (mapped_team_id,) in mapped_team_ids:
            team_ids.add(mapped_team_id)

    associated_athlete_ids = (
        db.session.query(Medal.athlete_id.label("athlete_id"))
        .filter(Medal.team_id.in_(team_ids))
        .union(
            db.session.query(MatchParticipant.athlete_id.label("athlete_id")).filter(
                MatchParticipant.team_id.in_(team_ids)
            )
        )
        .subquery()
    )

    best_adult_rating = (
        db.session.query(
            AthleteRating.athlete_id.label("athlete_id"),
            AthleteRating.percentile.label("percentile"),
            AthleteRating.rating.label("rating"),
            AthleteRating.belt.label("belt"),
            func.row_number()
            .over(
                partition_by=AthleteRating.athlete_id,
                order_by=(
                    AthleteRating.percentile.asc(),
                    AthleteRating.rating.desc(),
                ),
            )
            .label("row_num"),
        )
        .filter(
            AthleteRating.age == "Adult",
            AthleteRating.percentile.isnot(None),
        )
        .subquery()
    )

    elite_competitors = (
        db.session.query(
            Athlete.id.label("athlete_id"),
            Athlete.name.label("athlete_name"),
            Athlete.personal_name.label("personal_name"),
            Athlete.slug.label("athlete_slug"),
            best_adult_rating.c.percentile.label("percentile"),
            best_adult_rating.c.rating.label("rating"),
            best_adult_rating.c.belt.label("belt"),
        )
        .join(associated_athlete_ids, associated_athlete_ids.c.athlete_id == Athlete.id)
        .join(best_adult_rating, best_adult_rating.c.athlete_id == Athlete.id)
        .filter(
            best_adult_rating.c.row_num == 1,
            best_adult_rating.c.percentile <= 0.11,
            best_adult_rating.c.belt.notin_(NON_ELITE_BELTS),
        )
        .order_by(
            case(
                {belt: idx for idx, belt in enumerate(belt_order)},
                value=best_adult_rating.c.belt,
                else_=-1,
            ).desc(),
            best_adult_rating.c.percentile.asc(),
            Athlete.name.asc(),
        )
        .all()
    )

    elite_competitors = [
        e for e in elite_competitors if round(e.percentile * 100) <= 10
    ]

    athlete_ids = [competitor.athlete_id for competitor in elite_competitors]
    athlete_names = [competitor.athlete_name for competitor in elite_competitors]

    upcoming_registration_rows = (
        db.session.query(
            RegistrationLinkCompetitor.athlete_name,
            RegistrationLinkCompetitor.team_name,
            RegistrationLink.event_end_date,
        )
        .select_from(RegistrationLinkCompetitor)
        .join(
            RegistrationLink,
            RegistrationLinkCompetitor.registration_link_id == RegistrationLink.id,
        )
        .filter(
            RegistrationLinkCompetitor.athlete_name.in_(athlete_names),
            RegistrationLink.event_end_date >= datetime.now(),
            RegistrationLinkCompetitor.team_name.isnot(None),
            RegistrationLinkCompetitor.team_name != "",
        )
        .order_by(
            RegistrationLinkCompetitor.athlete_name.asc(),
            RegistrationLink.event_end_date.desc(),
        )
        .all()
    )
    registration_team_by_name = {}
    for row in upcoming_registration_rows:
        if row.athlete_name not in registration_team_by_name:
            registration_team_by_name[row.athlete_name] = resolve_dupe_team_name(
                row.team_name, exact_mappings, glob_mappings
            )

    latest_match_team_rows = (
        db.session.query(
            MatchParticipant.athlete_id.label("athlete_id"),
            Team.name.label("team_name"),
            func.row_number()
            .over(
                partition_by=MatchParticipant.athlete_id,
                order_by=Match.happened_at.desc(),
            )
            .label("row_num"),
        )
        .select_from(MatchParticipant)
        .join(Match, Match.id == MatchParticipant.match_id)
        .join(Team, Team.id == MatchParticipant.team_id)
        .filter(
            MatchParticipant.athlete_id.in_(athlete_ids),
            Team.name.isnot(None),
            Team.name != "",
        )
        .subquery()
    )
    latest_match_team_by_id = {
        row.athlete_id: resolve_dupe_team_name(
            row.team_name, exact_mappings, glob_mappings
        )
        for row in db.session.query(
            latest_match_team_rows.c.athlete_id,
            latest_match_team_rows.c.team_name,
        )
        .filter(latest_match_team_rows.c.row_num == 1)
        .all()
    }

    return jsonify(
        {
            "team_name": team.name,
            "elite_competitors": [
                {
                    "athlete_name": competitor.athlete_name,
                    "personal_name": competitor.personal_name,
                    "athlete_slug": competitor.athlete_slug,
                    "percentile": competitor.percentile,
                    "rating": competitor.rating,
                    "belt": competitor.belt,
                    "current_team": registration_team_by_name.get(
                        competitor.athlete_name
                    )
                    or latest_match_team_by_id.get(competitor.athlete_id),
                }
                for competitor in elite_competitors
            ],
        }
    )
