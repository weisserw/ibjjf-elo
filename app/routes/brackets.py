from flask import Blueprint, jsonify, request
import requests
from bs4 import BeautifulSoup
from pull import parse_categories
import re
from sqlalchemy.sql import func, or_
from sqlalchemy.orm import aliased
from extensions import db
from models import AthleteRating, Athlete, MatchParticipant, Match, Division
from normalize import normalize
from constants import translate_age, translate_belt, translate_weight

brackets_route = Blueprint("brackets_route", __name__)

validlink = re.compile(r"^/tournaments/\d+/categories/\d+$")


@brackets_route.route("/api/brackets/competitors")
def competitors():
    link = request.args.get("link")
    age = request.args.get("age")
    gender = request.args.get("gender")
    gi = request.args.get("gi")
    belt = request.args.get("belt")
    weight = request.args.get("weight")

    if not link or not age or not gender or not gi or not belt or not weight:
        return jsonify({"error": "Missing parameter"}), 400

    age = translate_age(age)
    belt = translate_belt(belt)
    weight = translate_weight(weight)

    gi = gi.lower() == "true"

    if not validlink.search(link):
        return jsonify({"error": "Invalid link"}), 400

    session = requests.Session()

    response = session.get("https://www.bjjcompsystem.com" + link, timeout=10)
    if response.status_code != 200:
        return jsonify(
            {"error": f"Request returned error {response.status_code}: {response.text}"}
        )

    soup = BeautifulSoup(response.content, "html.parser")

    results = []

    found = set()

    matches = soup.find_all("div", class_="tournament-category__match")

    for match in matches:
        for competitor in match.find_all("div", class_="match-card__competitor"):

            competitor_description = competitor.find(
                "span", class_="match-card__competitor-description"
            )

            if competitor_description and not competitor_description.find(
                "div", class_="match-card__bye"
            ):
                competitor_id = competitor["id"].split("-")[-1]

                if competitor_id in found:
                    continue

                found.add(competitor_id)

                competitor_seed = competitor.find(
                    "span", class_="match-card__competitor-n"
                ).get_text(strip=True)
                competitor_name = competitor.find(
                    "div", class_="match-card__competitor-name"
                ).get_text(strip=True)
                competitor_team = competitor.find(
                    "div", class_="match-card__club-name"
                ).get_text(strip=True)

                try:
                    competitor_seed = int(competitor_seed)
                except ValueError:
                    competitor_seed = 0

                results.append(
                    {
                        "id": None,
                        "ibjjf_id": competitor_id,
                        "seed": competitor_seed,
                        "name": competitor_name,
                        "team": competitor_team,
                        "rating": None,
                        "rank": None,
                    }
                )

    athlete_results = (
        db.session.query(Athlete.id, Athlete.ibjjf_id, Athlete.normalized_name)
        .filter(
            or_(
                Athlete.ibjjf_id.in_([result["id"] for result in results]),
                Athlete.normalized_name.in_(
                    [normalize(result["name"]) for result in results]
                ),
            )
        )
        .all()
    )

    athletes_by_id = {}
    athletes_by_name = {}

    for athlete in athlete_results:
        athletes_by_id[athlete.ibjjf_id] = athlete.id
        athletes_by_name[athlete.normalized_name] = athlete.id

    for result in results:
        if result["ibjjf_id"] in athletes_by_id:
            result["id"] = athletes_by_id[result["ibjjf_id"]]
        elif normalize(result["name"]) in athletes_by_name:
            result["id"] = athletes_by_name[normalize(result["name"])]

    ratings_results = (
        db.session.query(
            AthleteRating.athlete_id,
            AthleteRating.rating,
            AthleteRating.rank,
        )
        .filter(
            AthleteRating.athlete_id.in_([result["id"] for result in results]),
            AthleteRating.age == age,
            AthleteRating.belt == belt,
            AthleteRating.weight == weight,
            AthleteRating.gender == gender,
            AthleteRating.gi == gi,
        )
        .all()
    )

    ratings_by_id = {}
    for rating in ratings_results:
        ratings_by_id[rating.athlete_id] = rating

    no_ratings_found = []
    for result in results:
        rating = ratings_by_id.get(result["id"])
        if rating:
            result["rating"] = round(rating.rating)
            result["rank"] = rating.rank
        else:
            no_ratings_found.append(result)

    # If we can't find a rating for an athlete on the leader board,
    # they may still be rated but have been removed from the leader board
    # for inactivity. We can still find their rating by looking at their
    # most recent match.
    if len(no_ratings_found) > 0:
        recent_matches_cte = (
            db.session.query(
                MatchParticipant.athlete_id,
                MatchParticipant.end_rating,
                func.row_number()
                .over(
                    partition_by=MatchParticipant.athlete_id,
                    order_by=Match.happened_at.desc(),
                )
                .label("row_num"),
            )
            .select_from(MatchParticipant)
            .join(Match)
            .join(Division)
            .filter(
                MatchParticipant.athlete_id.in_(
                    [result["id"] for result in no_ratings_found]
                ),
                Division.gi == gi,
                Division.gender == gender,
            )
            .cte("recent_matches_cte")
        )
        recent_matches = aliased(recent_matches_cte)
        match_results = (
            db.session.query(recent_matches.c.athlete_id, recent_matches.c.end_rating)
            .select_from(recent_matches)
            .filter(recent_matches.c.row_num == 1)
            .all()
        )

        ratings_by_id = {}
        for rating in match_results:
            ratings_by_id[rating.athlete_id] = rating.end_rating

        for result in no_ratings_found:
            if result["id"] in ratings_by_id:
                result["rating"] = round(ratings_by_id[result["id"]])

    results.sort(key=lambda x: x["rating"] or -1, reverse=True)

    ordinal = 0
    ties = 0
    last_rating = None
    for result in results:
        if last_rating is None or result["rating"] != last_rating:
            ordinal += 1 + ties
            ties = 0
        else:
            ties += 1
        result["ordinal"] = ordinal
        last_rating = result["rating"]

    return jsonify({"competitors": results})


@brackets_route.route("/api/brackets/categories/<tournament_id>/<gender>")
def categories(tournament_id, gender):
    session = requests.Session()

    url = f"https://www.bjjcompsystem.com/tournaments/{tournament_id}/categories"
    if gender.lower() == "female":
        url += "?gender_id=2"

    response = session.get(url, timeout=10)
    if response.status_code != 200:
        return jsonify(
            {"error": f"Request returned error {response.status_code}: {response.text}"}
        )

    soup = BeautifulSoup(response.content, "html.parser")

    categories = parse_categories(soup)

    results = []
    for category in categories:
        try:
            translate_age(category["age"])
            translate_belt(category["belt"])
            translate_weight(category["weight"])
        except ValueError:
            continue
        results.append(category)

    return jsonify({"categories": results})


@brackets_route.route("/api/brackets/events")
def events():
    session = requests.Session()

    response = session.get("https://bjjcompsystem.com/", timeout=10)
    if response.status_code != 200:
        return jsonify(
            {"error": f"Request returned error {response.status_code}: {response.text}"}
        )

    soup = BeautifulSoup(response.content, "html.parser")

    tournaments_select = soup.find("select", {"id": "tournament_id"})
    if not tournaments_select:
        return jsonify({"error": "Could not find tournaments select element"})

    tournaments = []
    for option in tournaments_select.find_all("option"):
        if option.get("value"):
            tournaments.append({"id": option["value"], "name": option.text})

    return jsonify({"events": tournaments})
