from flask import Blueprint, jsonify, request
import requests
from bs4 import BeautifulSoup
from pull import parse_categories
import re
from sqlalchemy.sql import or_
from extensions import db
from models import AthleteRating, Athlete
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
                        "id": competitor_id,
                        "seed": competitor_seed,
                        "found": False,
                        "name": competitor_name,
                        "team": competitor_team,
                        "rating": None,
                        "rank": None,
                    }
                )

    athlete_results = (
        db.session.query(Athlete.ibjjf_id, Athlete.normalized_name)
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

    athletes_by_id = set()
    athletes_by_name = set()

    for athlete in athlete_results:
        athletes_by_id.add(athlete.ibjjf_id)
        athletes_by_name.add(athlete.normalized_name)

    ratings_results = (
        db.session.query(
            AthleteRating.rating,
            AthleteRating.rank,
            Athlete.ibjjf_id,
            Athlete.normalized_name,
        )
        .select_from(AthleteRating)
        .join(Athlete)
        .filter(
            or_(
                Athlete.ibjjf_id.in_([result["id"] for result in results]),
                Athlete.normalized_name.in_(
                    [normalize(result["name"]) for result in results]
                ),
            ),
            AthleteRating.age == age,
            AthleteRating.belt == belt,
            AthleteRating.weight == weight,
            AthleteRating.gender == gender,
            AthleteRating.gi == gi,
        )
        .all()
    )

    ratings_by_id = {}
    ratings_by_name = {}
    for rating in ratings_results:
        ratings_by_id[rating.ibjjf_id] = rating
        ratings_by_name[rating.normalized_name] = rating

    for result in results:
        if (
            result["id"] in athletes_by_id
            or normalize(result["name"]) in athletes_by_name
        ):
            result["found"] = True

        rating = ratings_by_id.get(result["id"]) or ratings_by_name.get(
            normalize(result["name"])
        )
        if rating:
            result["rating"] = round(rating.rating)
            result["rank"] = rating.rank

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
