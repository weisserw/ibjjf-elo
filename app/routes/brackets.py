from flask import Blueprint, jsonify, request
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from pull import (
    parse_categories,
    parse_match_when,
    parse_match_where,
    parse_competitor,
    parse_medals,
)
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
    age_order,
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
)
from elo import (
    compute_start_rating,
    EloCompetitor,
    weight_handicaps,
    match_didnt_happen,
    DEFAULT_RATINGS,
    compute_k_factor,
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


def get_bracket_page(link, newer_than):
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


def get_ratings(results, age, belt, weight, gender, gi, rating_date, get_rank):
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

    if get_rank:
        ratings_results = (
            db.session.query(
                AthleteRating.athlete_id,
                AthleteRating.rating,
                AthleteRating.rank,
                AthleteRating.match_count,
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
                result["rating"] = rating.rating
                result["rank"] = rating.rank
                result["match_count"] = rating.match_count
            else:
                no_ratings_found.append(result)
    else:
        no_ratings_found = results
        for result in results:
            result["rating"] = None
            result["rank"] = None
            result["match_count"] = None

    # If we can't find a rating for an athlete on the leader board,
    # they may still be rated but have been removed from the leader board
    # for inactivity. We can still find their rating by looking at their
    # most recent match.
    if len(no_ratings_found) > 0:
        recent_matches_cte = (
            db.session.query(
                MatchParticipant.id,
                MatchParticipant.athlete_id,
                MatchParticipant.end_rating,
                MatchParticipant.end_match_count,
                Division.belt,
                Division.age,
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
                Match.happened_at < rating_date,
            )
            .cte("recent_matches_cte")
        )
        recent_matches = aliased(recent_matches_cte)
        match_results = (
            db.session.query(
                recent_matches.c.id,
                recent_matches.c.athlete_id,
                recent_matches.c.end_rating,
                recent_matches.c.end_match_count,
                recent_matches.c.belt,
                recent_matches.c.age,
            )
            .select_from(recent_matches)
            .filter(recent_matches.c.row_num == 1)
            .all()
        )

        same_or_higher_ages = age_order[age_order.index(age) :]
        division = Division(age=age, belt=belt, gi=gi, gender=gender, weight=weight)

        ratings_by_id = {}
        notes_by_id = {}
        for rating in match_results:
            # if last match was a different belt or age, see if we need to adjust it to the current division
            if rating.belt != belt or rating.age != age:
                last_match = (
                    db.session.query(MatchParticipant)
                    .join(Match)
                    .filter(
                        MatchParticipant.id == rating.id,
                        Match.happened_at < rating_date,
                    )
                    .first()
                )
                same_or_higher_age_match = (
                    db.session.query(MatchParticipant)
                    .join(Match)
                    .join(Division)
                    .filter(
                        Division.gi == gi,
                        Division.gender == gender,
                        Division.age.in_(same_or_higher_ages),
                        MatchParticipant.athlete_id == rating.athlete_id,
                        (Match.happened_at < last_match.match.happened_at)
                        | (
                            (Match.happened_at == last_match.match.happened_at)
                            & (Match.id < last_match.match.id)
                        ),
                    )
                    .limit(1)
                    .first()
                )

                adjusted_start_rating, note = compute_start_rating(
                    division, last_match, same_or_higher_age_match is not None
                )

                ratings_by_id[rating.athlete_id] = (
                    adjusted_start_rating,
                    rating.end_match_count,
                )
                notes_by_id[rating.athlete_id] = note
            else:
                ratings_by_id[rating.athlete_id] = (
                    rating.end_rating,
                    rating.end_match_count,
                )

        for result in no_ratings_found:
            if result["id"] in ratings_by_id:
                result["rating"] = ratings_by_id[result["id"]][0]
                result["match_count"] = ratings_by_id[result["id"]][1]
            if result["id"] in notes_by_id:
                result["note"] = notes_by_id[result["id"]]

    for result in results:
        if result["match_count"] is None:
            result["match_count"] = 0
        if result["rating"] is None:
            result["rating"] = DEFAULT_RATINGS[belt][age]

    # Get the last weight for competitors in open class
    if OPEN_CLASS in weight:
        weight_cte = (
            db.session.query(
                MatchParticipant.athlete_id,
                Division.weight,
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
                MatchParticipant.athlete_id.in_([result["id"] for result in results]),
                Division.gi == gi,
                Division.weight != OPEN_CLASS,
                Division.weight != OPEN_CLASS_HEAVY,
                Division.weight != OPEN_CLASS_LIGHT,
                Match.happened_at < rating_date,
            )
            .cte("weight_cte")
        )

        weight_query = db.session.query(
            weight_cte.c.athlete_id,
            weight_cte.c.weight,
        ).filter(weight_cte.c.row_num == 1)

        last_weight_by_id = {}
        for last_weight in weight_query.all():
            last_weight_by_id[last_weight.athlete_id] = last_weight.weight

        for result in results:
            if result["id"] in last_weight_by_id:
                result["last_weight"] = last_weight_by_id[result["id"]]

    results.sort(key=lambda x: x["rating"] or -1, reverse=True)

    ordinal = 0
    ties = 0
    last_rating = None
    for result in results:
        if (
            last_rating is None
            or result["rating"] is None
            or round(result["rating"]) != last_rating
        ):
            ordinal += 1 + ties
            ties = 0
        else:
            ties += 1
        result["ordinal"] = ordinal
        last_rating = None if result["rating"] is None else round(result["rating"])


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
                        "match_count": None,
                        "rank": None,
                        "note": None,
                        "last_weight": None,
                    }
                )

    get_ratings(
        rows,
        divdata["age"],
        divdata["belt"],
        divdata["weight"],
        divdata["gender"],
        gi,
        datetime.now() + timedelta(days=1),
        True,
    )

    return jsonify({"competitors": rows})


def compute_match_ratings(matches, results, belt, weight, age):
    for i in range(len(matches)):
        match = matches[i]

        red_id = match["red_id"]
        red_weight = match["red_weight"]
        red_ordinal = None
        red_rating = None
        red_expected = None
        red_handicap = 0
        red_end_rating = None
        red_match_count = 0
        blue_id = match["blue_id"]
        blue_weight = match["blue_weight"]
        blue_ordinal = None
        blue_rating = None
        blue_expected = None
        blue_handicap = 0
        blue_end_rating = None
        blue_match_count = 0

        for result in results:
            if result["ibjjf_id"] == red_id:
                red_ordinal = result["ordinal"]
                red_rating = result["rating"]
                red_end_rating = red_rating
                red_match_count = result["match_count"]
                if OPEN_CLASS in weight and result["last_weight"] is not None:
                    red_weight = result["last_weight"]
            elif result["ibjjf_id"] == blue_id:
                blue_ordinal = result["ordinal"]
                blue_rating = result["rating"]
                blue_end_rating = blue_rating
                blue_match_count = result["match_count"]
                if OPEN_CLASS in weight and result["last_weight"] is not None:
                    blue_weight = result["last_weight"]

        if red_rating is not None and blue_rating is not None:
            if (
                red_weight != blue_weight
                and red_weight != "Unknown"
                and blue_weight != "Unknown"
            ):
                red_handicap, blue_handicap = weight_handicaps(
                    belt, red_weight, blue_weight
                )

            red_previous_matches = [
                m
                for m in matches[:i]
                if m["red_id"] == red_id or m["blue_id"] == red_id
            ]
            if len(red_previous_matches) > 0:
                red_match_count += len(red_previous_matches)

                red_last_match = red_previous_matches[-1]
                if (
                    red_last_match["red_id"] == red_id
                    and red_last_match["red_end_rating"] is not None
                ):
                    red_rating = red_last_match["red_end_rating"]
                if (
                    red_last_match["blue_id"] == red_id
                    and red_last_match["blue_end_rating"] is not None
                ):
                    red_rating = red_last_match["blue_end_rating"]

            blue_previous_matches = [
                m
                for m in matches[:i]
                if m["red_id"] == blue_id or m["blue_id"] == blue_id
            ]
            if len(blue_previous_matches) > 0:
                blue_match_count += len(blue_previous_matches)

                blue_last_match = blue_previous_matches[-1]
                if (
                    blue_last_match["blue_id"] == blue_id
                    and blue_last_match["blue_end_rating"] is not None
                ):
                    blue_rating = blue_last_match["blue_end_rating"]
                if (
                    blue_last_match["red_id"] == blue_id
                    and blue_last_match["red_end_rating"] is not None
                ):
                    blue_rating = blue_last_match["red_end_rating"]

            red_k_factor = compute_k_factor(red_match_count, False, age)
            blue_k_factor = compute_k_factor(blue_match_count, False, age)

            red_elo = EloCompetitor(red_rating + red_handicap, red_k_factor)
            blue_elo = EloCompetitor(blue_rating + blue_handicap, blue_k_factor)

            red_expected = red_elo.expected_score(blue_elo)
            blue_expected = blue_elo.expected_score(red_elo)

            if match_didnt_happen(match["red_note"], match["blue_note"]) or (
                not match["red_loser"] and not match["blue_loser"]
            ):
                red_end_rating = red_rating
                blue_end_rating = blue_rating
            else:
                if match["red_loser"] and match["blue_loser"]:
                    red_elo.tied(blue_elo)
                elif not match["red_loser"]:
                    red_elo.beat(blue_elo)
                else:
                    blue_elo.beat(red_elo)

                red_end_rating = red_elo.rating - red_handicap
                blue_end_rating = blue_elo.rating - blue_handicap

                # don't subtract points from winners
                if (red_end_rating < red_rating and not match["red_loser"]) or (
                    blue_end_rating < blue_rating and not match["blue_loser"]
                ):
                    red_end_rating = red_rating
                    blue_end_rating = blue_rating

                # don't let ratings go below 0
                if red_end_rating < 0:
                    red_end_rating = 0
                if blue_end_rating < 0:
                    blue_end_rating = 0

        match["red_ordinal"] = red_ordinal
        match["red_rating"] = red_rating
        match["red_expected"] = red_expected
        match["red_handicap"] = red_handicap
        match["red_weight"] = red_weight
        match["red_end_rating"] = red_end_rating

        match["blue_ordinal"] = blue_ordinal
        match["blue_rating"] = blue_rating
        match["blue_expected"] = blue_expected
        match["blue_handicap"] = blue_handicap
        match["blue_weight"] = blue_weight
        match["blue_end_rating"] = blue_end_rating


def parse_match(match, weight):
    when = parse_match_when(match, datetime.now().year)
    where, fight_num = parse_match_where(match)

    final = match.find("span", class_="tournament-category__final-label") is not None

    competitors = match.find_all("div", class_="match-card__competitor")
    if len(competitors) != 2:
        log.info("Invalid number of competitors:", len(competitors))
        return None

    red_competitor = match.find("div", class_="match-card__competitor--red")
    blue_competitor = [c for c in competitors if c != red_competitor][0]

    red_competitor_description = red_competitor.find(
        "span", class_="match-card__competitor-description"
    )
    red_child_description = red_competitor.find(
        "span", class_="match-card__child-description"
    )
    blue_competitor_description = blue_competitor.find(
        "span", class_="match-card__competitor-description"
    )
    blue_child_description = blue_competitor.find(
        "span", class_="match-card__child-description"
    )

    if (not red_competitor_description and not red_child_description) or (
        not blue_competitor_description and not blue_child_description
    ):
        return None

    red_bye, red_id, red_seed, red_loser, red_name, red_team, red_note = (
        False,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    blue_bye, blue_id, blue_seed, blue_loser, blue_name, blue_team, blue_note = (
        False,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    red_next_description = None
    blue_next_description = None

    if red_competitor_description:
        red_bye, red_id, red_seed, red_loser, red_name, red_team, red_note = (
            parse_competitor(red_competitor, red_competitor_description)
        )
        if red_seed is not None:
            try:
                red_seed = int(red_seed)
            except ValueError:
                red_seed = 0
    else:
        red_next = red_child_description.find_all(
            "div", class_="match-card__child-where"
        )
        if len(red_next) == 0:
            return None
        red_next_description = red_next[0].get_text(strip=True)

    if blue_competitor_description:
        blue_bye, blue_id, blue_seed, blue_loser, blue_name, blue_team, blue_note = (
            parse_competitor(blue_competitor, blue_competitor_description)
        )
        if blue_seed is not None:
            try:
                blue_seed = int(blue_seed)
            except ValueError:
                blue_seed = 0
    else:
        blue_next = blue_child_description.find_all(
            "div", class_="match-card__child-where"
        )
        if len(blue_next) == 0:
            return None
        blue_next_description = blue_next[0].get_text(strip=True)

    return {
        "final": final,
        "when": when,
        "where": where,
        "fight_num": fight_num,
        "red_bye": red_bye,
        "red_id": red_id,
        "red_seed": red_seed,
        "red_loser": red_loser,
        "red_name": red_name,
        "red_team": red_team,
        "red_note": red_note,
        "red_next_description": red_next_description,
        "red_ordinal": None,
        "red_rating": None,
        "red_end_rating": None,
        "red_expected": None,
        "red_handicap": 0,
        "red_weight": "Unknown" if OPEN_CLASS in weight else weight,
        "red_medal": None,
        "blue_bye": blue_bye,
        "blue_id": blue_id,
        "blue_seed": blue_seed,
        "blue_loser": blue_loser,
        "blue_name": blue_name,
        "blue_team": blue_team,
        "blue_note": blue_note,
        "blue_next_description": blue_next_description,
        "blue_ordinal": None,
        "blue_rating": None,
        "blue_end_rating": None,
        "blue_expected": None,
        "blue_handicap": 0,
        "blue_weight": "Unknown" if OPEN_CLASS in weight else weight,
        "blue_medal": None,
    }


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
            get_bracket_page(
                "https://www.bjjcompsystem.com" + link,
                datetime.now() - timedelta(minutes=2),
            ),
            "html.parser",
        )
    except Exception as e:
        return jsonify({"error": str(e)})

    results = []
    parsed_matches = []

    found = set()

    matches = soup.find_all("div", class_="tournament-category__match")

    for match in matches:
        for competitor in match.find_all("div", class_="match-card__competitor"):
            competitor_description = competitor.find(
                "span", class_="match-card__competitor-description"
            )

            if competitor_description:
                (
                    competitor_bye,
                    competitor_id,
                    competitor_seed,
                    _,
                    competitor_name,
                    competitor_team,
                    _,
                ) = parse_competitor(competitor, competitor_description)

                if competitor_bye:
                    continue

                if competitor_id in found:
                    continue

                found.add(competitor_id)

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
                        "match_count": None,
                        "rank": None,
                        "note": None,
                        "last_weight": None,
                    }
                )

    medals = parse_medals(soup)

    for match in matches:
        parsed_match = parse_match(match, weight)
        if parsed_match is not None:
            parsed_matches.append(parsed_match)

    parsed_matches.sort(key=lambda x: x["when"])

    for name, medal in medals.items():
        for match in parsed_matches[::-1]:
            if match["red_name"] == name:
                match["red_medal"] = medal
                break
            elif match["blue_name"] == name:
                match["blue_medal"] = medal
                break

    match_dates = [m["when"] for m in parsed_matches if m["when"]]
    earliest_match_date = (
        datetime.fromisoformat(match_dates[0]) if match_dates else datetime.now()
    )

    get_ratings(results, age, belt, weight, gender, gi, earliest_match_date, False)

    compute_match_ratings(parsed_matches, results, belt, weight, age)

    for result in results:
        last_match = next(
            (
                m
                for m in parsed_matches[::-1]
                if m["red_id"] == result["ibjjf_id"]
                or m["blue_id"] == result["ibjjf_id"]
            ),
            None,
        )
        if last_match:
            result["end_rating"] = (
                last_match["red_end_rating"]
                if last_match["red_id"] == result["ibjjf_id"]
                else last_match["blue_end_rating"]
            )
        else:
            result["end_rating"] = result["rating"]

        result["end_match_count"] = (result["match_count"] or 0) + len(
            [
                m
                for m in parsed_matches
                if m["red_id"] == result["ibjjf_id"]
                or m["blue_id"] == result["ibjjf_id"]
            ]
        )

    return jsonify(
        {
            "competitors": results,
            "matches": parsed_matches,
        }
    )


@brackets_route.route("/api/brackets/categories/<tournament_id>")
def categories(tournament_id):
    results = []

    for url, gender in [
        (
            f"https://www.bjjcompsystem.com/tournaments/{tournament_id}/categories?locale=en",
            "Male",
        ),
        (
            f"https://www.bjjcompsystem.com/tournaments/{tournament_id}/categories?gender_id=2&locale=en",
            "Female",
        ),
    ]:
        try:
            soup = BeautifulSoup(
                get_bracket_page(url, datetime.now() - timedelta(minutes=120)),
                "html.parser",
            )
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
