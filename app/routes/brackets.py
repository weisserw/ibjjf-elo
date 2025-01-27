from flask import Blueprint, jsonify, request
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from pull import parse_categories
import re
import json
from sqlalchemy.sql import func, or_
from sqlalchemy.orm import aliased
from extensions import db
from models import (
    AthleteRating,
    Athlete,
    MatchParticipant,
    Match,
    Division,
    BracketPage,
)
import logging
from normalize import normalize
from constants import (
    translate_age,
    translate_age_keep_juvenile,
    translate_belt,
    translate_weight,
    translate_gender,
    belt_order,
    age_order_all,
    weight_class_order_all,
    gender_order,
)

log = logging.getLogger("ibjjf")

brackets_route = Blueprint("brackets_route", __name__)

validlink = re.compile(r"^/tournaments/\d+/categories/\d+$")
validibjjfdblibk = re.compile(
    r"^(https://www.ibjjfdb.com/ChampionshipResults/\d+/PublicRegistrations)(\?lang=[a-zA-Z-]*)?$"
)
weightre = re.compile(r"\s+\(.*\)$")


def parse_division(name, throw=True):
    name = weightre.sub("", name)

    parts = name.split(" / ")

    age = None
    for part in parts:
        try:
            age = translate_age(part)
            break
        except ValueError:
            pass
    if age is None:
        if throw:
            raise ValueError(f"{name}: No age found")
        age = "Unknown"

    weight_class = None
    for part in parts:
        try:
            weight_class = translate_weight(part)
            break
        except ValueError:
            pass
    if weight_class is None:
        if throw:
            raise ValueError(f"{name}: No weight class found")
        weight_class = "Unknown"

    belt = None
    for part in parts:
        try:
            belt = translate_belt(part)
            break
        except ValueError:
            pass
    if belt is None:
        if throw:
            raise ValueError(f"{name}: No belt found")
        belt = "Unknown"

    gender = None
    for part in parts:
        try:
            gender = translate_gender(part)
            break
        except ValueError:
            pass
    if gender is None:
        if throw:
            raise ValueError(f"{name}: No gender found")
        gender = "Unknown"

    return {
        "age": age,
        "weight": weight_class,
        "belt": belt,
        "gender": gender,
    }


def get_bracket_page(link, newer_than=None):
    q = db.session.query(BracketPage).filter(BracketPage.link == link)

    if newer_than is not None:
        q = q.filter(BracketPage.saved_at > newer_than)

    page = q.first()

    if page:
        return page.html

    log.info(f"Retrieving {link}")
    session = requests.Session()
    response = session.get(link, timeout=10)
    log.info(f"Retrieved {link} with status {response.status_code}")

    if response.status_code != 200:
        raise Exception(
            f"Request returned error {response.status_code}: {response.text}"
        )

    db.session.query(BracketPage).filter(BracketPage.link == link).delete()

    page = BracketPage(link=link, html=response.text, saved_at=datetime.now())
    db.session.add(page)
    db.session.commit()

    return response.content


def get_ratings(results, age, belt, weight, gender, gi):
    athlete_results = (
        db.session.query(Athlete.id, Athlete.ibjjf_id, Athlete.normalized_name)
        .filter(
            or_(
                Athlete.ibjjf_id.in_(
                    [
                        result["ibjjf_id"]
                        for result in results
                        if result["ibjjf_id"] is not None
                    ]
                ),
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
        if result["ibjjf_id"] is not None and result["ibjjf_id"] in athletes_by_id:
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


def parse_registrations(soup):
    script_tag = soup.find_all("script")[-1]
    script_text = script_tag.get_text(strip=True)
    json_match = re.search(r"const\s+model\s*=\s*(\[[^;]+)", script_text)

    if not json_match:
        raise Exception("No data found.")

    json_text = json_match.group(1)
    json_data = json.loads(json_text)

    return json_data


@brackets_route.route("/api/brackets/registrations/categories")
def registration_categories():
    link = request.args.get("link")

    if not link:
        return jsonify({"error": "Missing parameter"}), 400

    m = validibjjfdblibk.search(link)
    if not m:
        return (
            jsonify(
                {
                    "error": "Link should be in the format 'https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations'"
                }
            ),
            400,
        )

    url = m.group(1) + m.group(2) if m.group(2) else m.group(1)

    try:
        soup = BeautifulSoup(
            get_bracket_page(url, newer_than=datetime.now() - timedelta(minutes=10)),
            "html.parser",
        )

        container = soup.find("div", class_="container")
        title_tag = container.find("h2", class_="title")
        tournament_name = title_tag.get_text(strip=True) if title_tag else "Unknown"

        json_data = parse_registrations(soup)
    except Exception as e:
        return jsonify({"error": str(e)})

    rows = []
    total_competitors = 0
    for entry in json_data:
        division_name = entry["FriendlyName"]

        total_competitors += len(entry["RegistrationCategories"])

        lowered = division_name.lower()
        if not ("master" in lowered or "adult" in lowered or "juven" in lowered):
            continue

        rows.append(weightre.sub("", division_name))

    return jsonify(
        {
            "categories": rows,
            "event_name": tournament_name,
            "total_competitors": total_competitors,
        }
    )


@brackets_route.route("/api/brackets/registrations/competitors")
def registration_competitors():
    link = request.args.get("link")
    division = request.args.get("division")
    gi = request.args.get("gi")

    if not link or not division or not gi:
        return jsonify({"error": "Missing parameter"}), 400

    gi = gi.lower() == "true"

    m = validibjjfdblibk.search(link)
    if not m:
        return (
            jsonify(
                {
                    "error": "Link should be in the format 'https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations'"
                }
            ),
            400,
        )

    url = m.group(1) + m.group(2) if m.group(2) else m.group(1)

    try:
        divdata = parse_division(division, throw=True)

        soup = BeautifulSoup(
            get_bracket_page(url, newer_than=datetime.now() - timedelta(minutes=10)),
            "html.parser",
        )

        json_data = parse_registrations(soup)
    except Exception as e:
        return jsonify({"error": str(e)})

    rows = []
    for entry in json_data:
        division_name = entry["FriendlyName"]
        lowered = division_name.lower()
        if not ("master" in lowered or "adult" in lowered or "juven" in lowered):
            continue
        division_name = weightre.sub("", division_name)

        if division_name == division:
            for competitor in entry["RegistrationCategories"]:
                team = competitor["AcademyTeamName"]
                name = competitor["AthleteName"]
                rows.append(
                    {
                        "name": name,
                        "team": team,
                        "id": None,
                        "ibjjf_id": None,
                        "seed": 0,
                        "rating": None,
                        "rank": None,
                    }
                )

    get_ratings(
        rows, divdata["age"], divdata["belt"], divdata["weight"], divdata["gender"], gi
    )

    return jsonify({"competitors": rows})


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

    try:
        soup = BeautifulSoup(
            get_bracket_page("https://www.bjjcompsystem.com" + link), "html.parser"
        )
    except Exception as e:
        return jsonify({"error": str(e)})

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

    get_ratings(results, age, belt, weight, gender, gi)

    return jsonify({"competitors": results})


@brackets_route.route("/api/brackets/categories/<tournament_id>")
def categories(tournament_id):
    results = []

    for url, gender in [
        (
            f"https://www.bjjcompsystem.com/tournaments/{tournament_id}/categories",
            "Male",
        ),
        (
            f"https://www.bjjcompsystem.com/tournaments/{tournament_id}/categories?gender_id=2",
            "Female",
        ),
    ]:
        try:
            soup = BeautifulSoup(get_bracket_page(url), "html.parser")
        except Exception as e:
            return jsonify({"error": str(e)})

        categories = parse_categories(soup)

        for category in categories:
            try:
                translate_age_keep_juvenile(category["age"])
                translate_belt(category["belt"])
                translate_weight(category["weight"])
            except ValueError:
                continue
            category["gender"] = gender
            results.append(category)

    results = sorted(
        results,
        key=lambda x: (
            belt_order.index(translate_belt(x["belt"])),
            age_order_all.index(translate_age_keep_juvenile(x["age"])),
            gender_order.index(x["gender"]),
            weight_class_order_all.index(translate_weight(x["weight"])),
        ),
    )

    return jsonify({"categories": results})


@brackets_route.route("/api/brackets/events")
def events():
    try:
        soup = BeautifulSoup(
            get_bracket_page(
                "https://bjjcompsystem.com/", datetime.now() - timedelta(minutes=5)
            ),
            "html.parser",
        )
    except Exception as e:
        return jsonify({"error": str(e)})

    tournaments_select = soup.find("select", {"id": "tournament_id"})
    if not tournaments_select:
        return jsonify({"error": "Could not find tournaments select element"})

    tournaments = []
    for option in tournaments_select.find_all("option"):
        if option.get("value"):
            tournaments.append({"id": option["value"], "name": option.text})

    return jsonify({"events": tournaments})
