from flask import Blueprint, jsonify, request
import requests
import threading
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
from sqlalchemy.sql import func, or_, and_, tuple_
from sqlalchemy.orm import aliased
from extensions import db
from models import (
    AthleteRating,
    Athlete,
    MatchParticipant,
    Match,
    Division,
    BracketPage,
    Event,
    Medal,
    RegistrationLink,
    RegistrationLinkCompetitor,
    LiveRating,
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
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    ADULT,
    NON_ELITE_BELTS,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    rated_ages,
)
from elo import (
    compute_start_rating,
    EloCompetitor,
    weight_handicaps,
    match_didnt_happen,
    DEFAULT_RATINGS,
    compute_k_factor,
    CLOSEOUT_NOTE,
)
from photos import get_s3_client, get_public_photo_url

log = logging.getLogger("ibjjf")

brackets_route = Blueprint("brackets_route", __name__)

validlink = re.compile(r"^/tournaments/(\d+)/categories/\d+$")
validibjjfdblink = re.compile(
    r"^(https://www.ibjjfdb.com/ChampionshipResults/\d+/PublicRegistrations)(\?lang=[a-zA-Z-]*)?$"
)
weightre = re.compile(r"\s+\(.*\)$")


def format_division(divdata):
    return f"{divdata['belt']} / {divdata['age']} / {divdata['gender']} / {divdata['weight']}"


def parse_division(name):
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
        raise ValueError(f"{name}: No age found")

    weight_class = None
    for part in parts:
        try:
            weight_class = translate_weight(part)
            break
        except ValueError:
            pass
    if weight_class is None:
        raise ValueError(f"{name}: No weight class found")

    belt = None
    for part in parts:
        try:
            belt = translate_belt(part)
            break
        except ValueError:
            pass
    if belt is None:
        raise ValueError(f"{name}: No belt found")

    gender = None
    for part in parts:
        try:
            gender = translate_gender(part)
            break
        except ValueError:
            pass
    if gender is None:
        raise ValueError(f"{name}: No gender found")

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

    session = requests.Session()
    response = session.get(link, timeout=10)

    if response.status_code != 200:
        raise Exception(
            f"Request returned error {response.status_code}: {response.text}"
        )

    db.session.query(BracketPage).filter(BracketPage.link == link).delete()

    page = BracketPage(link=link, html=response.text, saved_at=datetime.now())
    db.session.add(page)
    db.session.commit()

    return response.content


def competitor_sort_key(competitor, rating_prop):
    if competitor["match_count"] <= 4:
        provisional_index = 0
    else:
        provisional_index = 1

    return (provisional_index, competitor[rating_prop] or -1)


def get_ratings(
    results,
    event_id,
    gi,
    rating_date,
    use_live_ratings,
    s3_client,
    elite_only=False,
):
    athlete_results = (
        db.session.query(
            Athlete.id,
            Athlete.ibjjf_id,
            Athlete.normalized_name,
            Athlete.name,
            Athlete.slug,
            Athlete.instagram_profile,
            Athlete.personal_name,
            Athlete.profile_image_saved_at,
            Athlete.country,
            Athlete.country_note,
            Athlete.country_note_pt,
        )
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
        athletes_by_id[athlete.ibjjf_id] = athlete
        athletes_by_name[athlete.normalized_name] = athlete

    for result in results:
        if result["ibjjf_id"] is not None and result["ibjjf_id"] in athletes_by_id:
            athlete = athletes_by_id[result["ibjjf_id"]]
            result["id"] = athlete.id
            result["name"] = athlete.name
            result["slug"] = athlete.slug
            result["instagram_profile"] = athlete.instagram_profile
            result["personal_name"] = athlete.personal_name
            result["profile_image_url"] = (
                get_public_photo_url(s3_client, athlete)
                if athlete.profile_image_saved_at
                else None
            )
            result["country"] = athlete.country
            result["country_note"] = athlete.country_note
            result["country_note_pt"] = athlete.country_note_pt
        elif normalize(result["name"]) in athletes_by_name:
            athlete = athletes_by_name[normalize(result["name"])]
            if result["ibjjf_id"] is None or athlete.ibjjf_id is None:
                result["id"] = athlete.id
            result["slug"] = athlete.slug
            result["instagram_profile"] = athlete.instagram_profile
            result["personal_name"] = athlete.personal_name
            result["profile_image_url"] = (
                get_public_photo_url(s3_client, athlete)
                if athlete.profile_image_saved_at
                else None
            )
            result["country"] = athlete.country
            result["country_note"] = athlete.country_note
            result["country_note_pt"] = athlete.country_note_pt

    JUVENILE_PERCENTILE_AGES = [JUVENILE_1, JUVENILE_2, JUVENILE]
    ADULT_PERCENTILE_AGES = [JUVENILE_1, JUVENILE_2, JUVENILE, ADULT]
    MASTER_PERCENTILE_AGES = [
        JUVENILE_1,
        JUVENILE_2,
        JUVENILE,
        ADULT,
        MASTER_1,
        MASTER_2,
        MASTER_3,
        MASTER_4,
        MASTER_5,
        MASTER_6,
        MASTER_7,
    ]

    # Build all valid (athlete_id, age, belt, gender, gi) combinations
    athlete_keys = []
    for result in results:
        if not result.get("id"):
            continue
        if result["age"] in JUVENILE_PERCENTILE_AGES:
            age_set = JUVENILE_PERCENTILE_AGES
        elif result["age"] in ADULT_PERCENTILE_AGES:
            age_set = ADULT_PERCENTILE_AGES
        else:
            age_set = MASTER_PERCENTILE_AGES
        for age in age_set:
            athlete_keys.append(
                (
                    result["id"],
                    age,
                    result["belt"],
                    result["gender"],
                    gi,
                )
            )

    # Run the query in batches of max 500 athlete_keys at a time
    percentile_rows = []
    batch_size = 500
    for i in range(0, len(athlete_keys), batch_size):
        batch = athlete_keys[i : i + batch_size]
        batch_rows = (
            db.session.query(
                AthleteRating.athlete_id,
                AthleteRating.age,
                AthleteRating.belt,
                AthleteRating.gender,
                AthleteRating.gi,
                func.min(AthleteRating.percentile).label("percentile"),
            )
            .filter(
                tuple_(
                    AthleteRating.athlete_id,
                    AthleteRating.age,
                    AthleteRating.belt,
                    AthleteRating.gender,
                    AthleteRating.gi,
                ).in_(batch),
                AthleteRating.percentile <= 0.11,
            )
            .group_by(
                AthleteRating.athlete_id,
                AthleteRating.age,
                AthleteRating.belt,
                AthleteRating.gender,
                AthleteRating.gi,
            )
            .all()
        )
        percentile_rows.extend(batch_rows)

    # For each athlete, pick the best percentile (lowest) from their valid ages
    percentiles_by_id = {}
    for result in results:
        if not result.get("id"):
            continue
        valid_ages = (
            JUVENILE_PERCENTILE_AGES
            if result["age"] in JUVENILE_PERCENTILE_AGES
            else (
                ADULT_PERCENTILE_AGES
                if result["age"] in ADULT_PERCENTILE_AGES
                else MASTER_PERCENTILE_AGES
            )
        )
        best_percentile = None
        for row in percentile_rows:
            if (
                row.athlete_id == result["id"]
                and row.belt == result["belt"]
                and row.gender == result["gender"]
                and row.gi == gi
                and row.age in valid_ages
            ):
                if best_percentile is None or row.percentile < best_percentile:
                    best_percentile = row.percentile
        percentiles_by_id[result["id"]] = best_percentile

    for result in results:
        result["percentile"] = percentiles_by_id.get(result["id"])

    if elite_only:
        results[:] = [
            result
            for result in results
            if result["percentile"] is not None
            and round(result["percentile"] * 100) <= 10
            and result["belt"] not in NON_ELITE_BELTS
        ]

    # get ranks from athlete_ratings if available
    ratings_results = (
        db.session.query(
            AthleteRating.athlete_id,
            AthleteRating.rank,
        )
        .filter(
            or_(
                and_(
                    AthleteRating.athlete_id == result["id"],
                    AthleteRating.age == result["age"],
                    AthleteRating.belt == result["belt"],
                    AthleteRating.weight == result["weight"],
                    AthleteRating.gender == result["gender"],
                    AthleteRating.gi == gi,
                )
                for result in results
                if result["id"]
            )
        )
        .all()
    )
    ranks_by_id = {r.athlete_id: r.rank for r in ratings_results}
    for result in results:
        result["rank"] = ranks_by_id.get(result["id"])

    # get rating and match_count from their most recent match
    ratings_by_id = {}
    notes_by_id = {}
    match_happened_at_by_id = {}
    for result in results:
        athlete_id = result.get("id")
        belt = result.get("belt")
        age = result.get("age")
        gender = result.get("gender")
        weight = result.get("weight")
        if not athlete_id:
            continue
        recent_matches_cte = (
            db.session.query(
                MatchParticipant.id,
                MatchParticipant.athlete_id,
                MatchParticipant.end_rating,
                MatchParticipant.end_match_count,
                Division.belt,
                Division.age,
                Match.happened_at.label("happened_at"),
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
                MatchParticipant.athlete_id == athlete_id,
                Division.gi == gi,
                Division.gender == gender,
                Match.happened_at < rating_date,
            )
            .cte("recent_matches_cte")
        )
        recent_matches = aliased(recent_matches_cte)
        match_result = (
            db.session.query(
                recent_matches.c.id,
                recent_matches.c.athlete_id,
                recent_matches.c.end_rating,
                recent_matches.c.end_match_count,
                recent_matches.c.belt,
                recent_matches.c.age,
                recent_matches.c.happened_at,
            )
            .select_from(recent_matches)
            .filter(recent_matches.c.row_num == 1)
            .first()
        )
        if match_result:
            same_or_higher_ages = age_order[age_order.index(age) :]
            division = Division(age=age, belt=belt, gi=gi, gender=gender, weight=weight)
            if match_result.belt != belt or match_result.age != age:
                last_match = (
                    db.session.query(MatchParticipant)
                    .join(Match)
                    .filter(
                        MatchParticipant.id == match_result.id,
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
                        MatchParticipant.athlete_id == match_result.athlete_id,
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
                    division,
                    last_match,
                    same_or_higher_age_match is not None,
                    match_result.end_match_count,
                )
                ratings_by_id[match_result.athlete_id] = (
                    adjusted_start_rating,
                    match_result.end_match_count,
                )
                notes_by_id[match_result.athlete_id] = note
                match_happened_at_by_id[match_result.athlete_id] = (
                    match_result.happened_at
                )
            else:
                ratings_by_id[match_result.athlete_id] = (
                    match_result.end_rating,
                    match_result.end_match_count,
                )
                match_happened_at_by_id[match_result.athlete_id] = (
                    match_result.happened_at
                )

    live_ratings_by_id = {}
    if use_live_ratings:
        # query all live_ratings for these athlete ids and gi which are before the rating date
        # this should only be relevant when an athlete has competed in one division but has another
        # on the same day (e.g. weight class but not open)
        # and we haven't recorded match results for that division yet.
        athlete_ids = list(match_happened_at_by_id.keys())
        live_ratings = (
            db.session.query(LiveRating)
            .filter(
                LiveRating.athlete_id.in_(athlete_ids),
                LiveRating.gi == gi,
                LiveRating.happened_at < rating_date,
                LiveRating.happened_at
                > datetime.now()
                - timedelta(days=3),  # only consider live ratings from the last 3 days
            )
            .all()
        )

        # for each athlete, find the newest live_rating with happened_at > match_happened_at
        for lr in live_ratings:
            athlete_id = lr.athlete_id
            match_happened_at = match_happened_at_by_id.get(athlete_id, None)
            if match_happened_at is None or lr.happened_at > match_happened_at:
                if (
                    athlete_id not in live_ratings_by_id
                    or lr.happened_at > live_ratings_by_id[athlete_id].happened_at
                ):
                    live_ratings_by_id[athlete_id] = lr

    for result in results:
        athlete_id = result["id"]
        if athlete_id in live_ratings_by_id:
            lr = live_ratings_by_id[athlete_id]
            result["rating"] = lr.rating
            result["match_count"] = lr.match_count
        elif athlete_id in ratings_by_id:
            result["rating"] = ratings_by_id[athlete_id][0]
            result["match_count"] = ratings_by_id[athlete_id][1]
        if athlete_id in notes_by_id:
            result["note"] = notes_by_id[athlete_id]
        if result["match_count"] is None:
            result["match_count"] = 0
        if result["rating"] is None:
            result["rating"] = DEFAULT_RATINGS[result["belt"]][result["age"]]

    # determine if all results are in a single division
    one_division = True
    first_division = None
    for result in results:
        current_division = (
            result["weight"],
            result["belt"],
            result["age"],
            result["gender"],
        )
        if first_division is None:
            first_division = current_division
        elif current_division != first_division:
            one_division = False
            break

    weight = ""
    belt = ""
    if first_division is not None and one_division:
        weight = first_division[0]
        belt = first_division[1]

    # get the last weight for competitors in open class
    if OPEN_CLASS in weight:
        if event_id is not None:
            # look at registration_link_competitors for the event name / athlete name first
            registration_weight_query = (
                db.session.query(
                    RegistrationLinkCompetitor.athlete_name,
                    Division.weight,
                )
                .join(RegistrationLink)
                .join(Division)
                .filter(
                    RegistrationLink.event_id == event_id,
                    RegistrationLinkCompetitor.athlete_name.in_(
                        [result["name"] for result in results]
                    ),
                )
            )

            last_weight_by_name = {}
            for last_weight in registration_weight_query.all():
                last_weight_by_name[last_weight.athlete_name] = last_weight.weight

            missing = False
            for result in results:
                if result["name"] in last_weight_by_name:
                    result["last_weight"] = last_weight_by_name[result["name"]]
                else:
                    missing = True
        else:
            missing = True

        if missing:
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
                    MatchParticipant.athlete_id.in_(
                        [result["id"] for result in results if result["id"]]
                    ),
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

    if elite_only:
        elite_sort(results)
    else:
        results.sort(key=lambda x: competitor_sort_key(x, "rating"), reverse=True)

        compute_ordinals(results, weight, belt)


def elite_sort(results):
    # sort by belt in descending order of belt rank, then age, then gender, then weight, then rating
    results.sort(
        key=lambda x: (
            belt_order.index(x["belt"]),
            -age_order.index(x["age"]),
            -gender_order.index(x["gender"]),
            -weight_class_order_all.index(x["weight"]),
            x["rating"] if x["rating"] is not None else -1,
        ),
        reverse=True,
    )


def compute_ordinals(results, weight, belt):
    # for each competitor, get the average handicap against the rest of the competitors and add it to their rating
    for result in results:
        result["adjusted_rating"] = result["rating"]

        if OPEN_CLASS in weight:
            if result["rating"] is not None and result["last_weight"] is not None:
                handicap_sum = 0
                count = 0
                for other in results:
                    if (
                        other["rating"] is not None
                        and other["last_weight"] is not None
                        and other != result
                    ):
                        handicap_plus, handicap_minus = weight_handicaps(
                            belt, result["last_weight"], other["last_weight"]
                        )
                        if handicap_plus > 0:
                            handicap_sum += handicap_plus
                        elif handicap_minus > 0:
                            handicap_sum -= handicap_minus
                        count += 1
                if count > 0:
                    log.debug(
                        f"Adjusting {result['name']} ({result['last_weight']}) by {handicap_sum / count} (handicap sum: {handicap_sum}, count: {count}), new rating: {result['adjusted_rating'] + handicap_sum / count}"
                    )
                    result["adjusted_rating"] += handicap_sum / count

    if OPEN_CLASS in weight:
        # sort results by adjusted ratings
        results.sort(
            key=lambda x: competitor_sort_key(x, "adjusted_rating"),
            reverse=True,
        )

    ordinal = 0
    ties = 0
    last_rating = None
    for result in results:
        result_rating = result["adjusted_rating"]
        if (
            last_rating is None
            or result_rating is None
            or round(result_rating) != last_rating
        ):
            ordinal += 1 + ties
            ties = 0
        else:
            ties += 1
        result["ordinal"] = ordinal
        last_rating = None if result_rating is None else round(result_rating)


def parse_registrations(soup):
    script_tag = soup.find_all("script")[-1]
    script_text = script_tag.get_text(strip=True)
    json_match = re.search(r"const\s+model\s*=\s*(\[[^;]+)", script_text)

    if not json_match:
        raise Exception("No data found.")

    json_text = json_match.group(1)
    json_data = json.loads(json_text)

    return json_data


def find_first_index(lst, predicate):
    for index, element in enumerate(lst):
        if predicate(element):
            return index
    return -1


def matches_names(item, *names):
    item_name = item.normalized_name.lower()
    for name in names:
        if item_name.startswith(name):
            return True
    return False


def bring_to_front(lst, *names):
    items_to_bring = [
        item
        for item in lst
        if matches_names(item, *names)
        and "15 anos" not in item.normalized_name
        and "kids" not in item.normalized_name
        and "criancas" not in item.normalized_name
    ]
    for item in items_to_bring:
        lst.remove(item)
    lst[0:0] = items_to_bring


def format_event_dates(start_date, end_date):
    if not start_date or not end_date:
        return ""
    if start_date == end_date:
        # Example: Oct 15
        return f"{start_date.strftime('%b')} {start_date.day}"
    if start_date.month == end_date.month and start_date.year == end_date.year:
        # Example: Oct 15 - 17
        return f"{start_date.strftime('%b')} {start_date.day} - {end_date.day}"
    else:
        # Example: Oct 28 - Nov 2
        return f"{start_date.strftime('%b')} {start_date.day} - {end_date.strftime('%b')} {end_date.day}"


@brackets_route.route("/api/brackets/registrations/links")
def registration_links():
    links = (
        db.session.query(RegistrationLink)
        .filter(RegistrationLink.hidden.isnot(True))
        .filter(RegistrationLink.event_start_date > datetime.now() + timedelta(days=1))
        .order_by(RegistrationLink.event_end_date, RegistrationLink.name)
        .all()
    )

    bring_to_front(
        links,
        "ibjjf crown ",
        "european ibjjf ",
        "pan ibjjf ",
        "world ibjjf ",
        "campeonato brasileiro ",
    )

    rows = []
    for link in links:
        rows.append(
            {
                "name": f"{link.name} ({format_event_dates(link.event_start_date, link.event_end_date)})",
                "link": link.link,
            }
        )

    return jsonify({"links": rows})


def is_gi(event_name):
    name = event_name.lower()
    return not ("no-gi" in name or "no gi" in name or "sem kimono" in name)


def save_competitors_thread(link_id, json_data, division_set):
    from app import app

    log = logging.getLogger("ibjjf")
    with app.app_context():
        try:
            save_competitors(link_id, json_data, division_set)
        except Exception as e:
            log.error(f"Error saving competitors: {e}")


def save_competitors(link_id, json_data, division_set):
    link = db.session.query(RegistrationLink).get(link_id)
    if link is not None:
        gi = is_gi(link.name)

        added_row = False
        for entry in json_data:
            division_name = entry["FriendlyName"]
            division_name_clean = weightre.sub("", division_name)

            try:
                current_divdata = parse_division(division_name_clean)

                if format_division(current_divdata) not in division_set:
                    continue

                db_division, added = get_db_division(gi, current_divdata)
                if added:
                    added_row = True
            except ValueError:
                log.debug(f"Invalid division name: {division_name_clean}")
                continue
            if db_division is not None:
                for competitor in entry["RegistrationCategories"]:
                    name = competitor["AthleteName"]
                    team = competitor["AcademyTeamName"]
                    if save_registration_link_competitor(link, db_division, name, team):
                        added_row = True
    if added_row:
        db.session.commit()


def normalize_registration_link(link):
    m = validibjjfdblink.search(link)
    if not m:
        raise ValueError(
            "Link should be in the format 'https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations'"
        )
    return m.group(1) + "?lang=en-US"


def import_registration_link(link, background):
    url = normalize_registration_link(link)

    link = (
        db.session.query(RegistrationLink).filter(RegistrationLink.link == url).first()
    )

    if not link:
        raise ValueError("Link not found")

    soup = BeautifulSoup(
        get_bracket_page(url, newer_than=datetime.now() - timedelta(minutes=10)),
        "html.parser",
    )

    updated_at = None
    for span in soup.find_all("span"):
        strong = span.find("strong")
        if strong and "Last Updated:" in strong.get_text():
            text = span.get_text().replace(strong.get_text(), "").strip()
            date_part = text.split("(")[0].strip()
            try:
                updated_at = datetime.strptime(date_part, "%b/%d/%Y %H:%M:%S")
            except Exception:
                try:
                    updated_at = datetime.strptime(date_part, "%B/%d/%Y %H:%M:%S")
                except Exception:
                    updated_at = None
            break

    json_data = parse_registrations(soup)

    if updated_at is not None:
        link.updated_at = updated_at
        db.session.commit()

    rows = []
    total_competitors = 0
    for entry in json_data:
        division_name = entry["FriendlyName"]
        division_name_clean = weightre.sub("", division_name)

        try:
            divdata = parse_division(division_name_clean)

            age_lower = divdata["age"].lower()
            if not (
                "master" in age_lower
                or "adult" in age_lower
                or "juven" in age_lower
                or "teen" in age_lower
            ):
                continue

            rows.append(format_division(divdata))
        except ValueError:
            log.debug(f"Invalid division name: {division_name_clean}")
            continue

        total_competitors += len(entry["RegistrationCategories"])

    if background:
        division_set = set(rows)
        thread = threading.Thread(
            target=save_competitors_thread, args=(link.id, json_data, division_set)
        )
        thread.start()
    else:
        save_competitors(link.id, json_data, set(rows))

    return {
        "categories": rows,
        "event_name": link.name,
        "total_competitors": total_competitors,
    }


def internal_registration_categories(link):
    db_link = (
        db.session.query(RegistrationLink).filter(RegistrationLink.link == link).first()
    )
    if not db_link:
        return jsonify({"error": "Link not found"}), 400

    divisions = []
    for competitor in (
        db.session.query(RegistrationLinkCompetitor.division_id)
        .filter(RegistrationLinkCompetitor.registration_link_id == db_link.id)
        .distinct()
        .all()
    ):
        division = db.session.get(Division, competitor.division_id)

        divisions.append(division)

    divisions.sort(
        key=lambda division: (
            belt_order.index(division.belt),
            age_order_all.index(division.age),
            gender_order.index(division.gender),
            weight_class_order_all.index(division.weight),
        )
    )

    rows = []
    for division in divisions:
        rows.append(
            format_division(
                {
                    "age": division.age,
                    "weight": division.weight,
                    "belt": division.belt,
                    "gender": division.gender,
                }
            )
        )

    total_competitors = (
        db.session.query(RegistrationLinkCompetitor)
        .filter(RegistrationLinkCompetitor.registration_link_id == db_link.id)
        .count()
    )

    return {
        "categories": rows,
        "event_name": db_link.name,
        "total_competitors": total_competitors,
    }


@brackets_route.route("/api/brackets/registrations/categories")
def registration_categories():
    link = request.args.get("link")

    if not link:
        return jsonify({"error": "Missing parameter"}), 400

    if link.startswith("internal:"):
        return jsonify(internal_registration_categories(link))
    try:
        data = import_registration_link(link, background=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)})

    return jsonify(data)


def get_db_division(gi, divdata):
    added_row = False

    if "Open Class" in divdata["weight"]:
        return None, False

    db_division = (
        db.session.query(Division)
        .filter(
            Division.gi == gi,
            Division.age == divdata["age"],
            Division.belt == divdata["belt"],
            Division.weight == divdata["weight"],
            Division.gender == divdata["gender"],
        )
        .first()
    )

    if db_division is None:
        db_division = Division(
            gi=gi,
            age=divdata["age"],
            belt=divdata["belt"],
            weight=divdata["weight"],
            gender=divdata["gender"],
        )
        db.session.add(db_division)
        added_row = True
        db.session.flush()

    return db_division, added_row


def save_registration_link_competitor(db_link, db_division, name, team):
    if db_link is None or db_division is None:
        return False

    updated = False

    competitor_entries = (
        db.session.query(RegistrationLinkCompetitor)
        .filter(
            RegistrationLinkCompetitor.registration_link_id == db_link.id,
            RegistrationLinkCompetitor.athlete_name == name,
        )
        .all()
    )

    if not competitor_entries or len(competitor_entries) > 1:
        if len(competitor_entries) > 1:
            for entry in competitor_entries:
                db.session.delete(entry)
        competitor_entry = RegistrationLinkCompetitor(
            registration_link_id=db_link.id,
            athlete_name=name,
            team_name=team,
            division_id=db_division.id,
        )
        db.session.add(competitor_entry)
        updated = True
    elif len(competitor_entries) == 1:
        competitor_entry = competitor_entries[0]
        if competitor_entry.division_id != db_division.id:
            competitor_entry.division_id = db_division.id
            updated = True
        if competitor_entry.team_name != team:
            competitor_entry.team_name = team
            updated = True

    if updated:
        db.session.flush()

    return updated


def internal_registration_competitors(link, divdata, gi):
    db_link = (
        db.session.query(RegistrationLink).filter(RegistrationLink.link == link).first()
    )

    if not db_link:
        raise ValueError("Link not found")

    db_division = (
        db.session.query(Division)
        .filter(
            Division.gi == gi,
            Division.age == divdata["age"],
            Division.belt == divdata["belt"],
            Division.weight == divdata["weight"],
            Division.gender == divdata["gender"],
        )
        .first()
    )

    if db_division is None:
        raise ValueError("Division not found")

    rows = []
    for competitor in (
        db.session.query(RegistrationLinkCompetitor)
        .filter(
            RegistrationLinkCompetitor.registration_link_id == db_link.id,
            RegistrationLinkCompetitor.division_id == db_division.id,
        )
        .all()
    ):
        rows.append(
            {
                "name": competitor.athlete_name,
                "team": competitor.team_name,
                "id": None,
                "ibjjf_id": None,
                "seed": 0,
                "rating": None,
                "match_count": None,
                "rank": None,
                "percentile": None,
                "note": None,
                "last_weight": None,
                "slug": None,
                "instagram_profile": None,
                "personal_name": None,
                "profile_image_url": None,
                "country": None,
                "country_note": None,
                "country_note_pt": None,
            }
        )

    return rows


@brackets_route.route("/api/brackets/registrations/competitors")
def registration_competitors():
    link = request.args.get("link")
    division = request.args.get("division")
    gi = request.args.get("gi")

    if not link or not division or not gi:
        return jsonify({"error": "Missing parameter"}), 400

    gi = gi.lower() == "true"

    s3_client = get_s3_client()

    if link.startswith("internal:"):
        try:
            divdata = parse_division(division)
            rows = internal_registration_competitors(link, divdata, gi)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        m = validibjjfdblink.search(link)
        if not m:
            return (
                jsonify(
                    {
                        "error": "Link should be in the format 'https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations'"
                    }
                ),
                400,
            )

        url = m.group(1) + "?lang=en-US"

        try:
            divdata = parse_division(division)

            soup = BeautifulSoup(
                get_bracket_page(
                    url, newer_than=datetime.now() - timedelta(minutes=10)
                ),
                "html.parser",
            )

            json_data = parse_registrations(soup)
        except Exception as e:
            return jsonify({"error": str(e)})

        rows = []
        for entry in json_data:
            division_name = entry["FriendlyName"]
            division_name = weightre.sub("", division_name)

            try:
                parsed = parse_division(division_name)
            except ValueError:
                log.debug(f"Invalid division name: {division_name}")
                continue

            age_lower = parsed["age"].lower()
            if not (
                "master" in age_lower
                or "adult" in age_lower
                or "juven" in age_lower
                or "teen" in age_lower
            ):
                continue

            if format_division(parsed) == division:
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
                            "percentile": None,
                            "note": None,
                            "last_weight": None,
                            "slug": None,
                            "instagram_profile": None,
                            "personal_name": None,
                            "profile_image_url": None,
                            "country": None,
                            "country_note": None,
                            "country_note_pt": None,
                            "age": divdata["age"],
                            "belt": divdata["belt"],
                            "weight": divdata["weight"],
                            "gender": divdata["gender"],
                            "gi": gi,
                        }
                    )

    get_ratings(
        rows,
        None,
        gi,
        datetime.now() + timedelta(days=1),
        False,
        s3_client,
    )

    return jsonify({"competitors": rows})


@brackets_route.route("/api/brackets/registrations/elites")
def registration_elites():
    link = request.args.get("link")
    min_tier = request.args.get("min_tier", default="3")

    # validate params
    if not link:
        return jsonify({"error": "Missing parameter"}), 400

    try:
        min_tier = int(min_tier)
        if min_tier not in (1, 2, 3):
            min_tier = 3
    except Exception:
        min_tier = 3

    # normalize link and lookup event to determine gi
    try:
        url = normalize_registration_link(link)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db_link = (
        db.session.query(RegistrationLink).filter(RegistrationLink.link == url).first()
    )
    if not db_link:
        return jsonify({"error": "Link not found"}), 400

    gi = is_gi(db_link.name)

    # pull page (cached) and parse registrations
    try:
        soup = BeautifulSoup(
            get_bracket_page(url, newer_than=datetime.now() - timedelta(minutes=10)),
            "html.parser",
        )
        json_data = parse_registrations(soup)
    except Exception as e:
        return jsonify({"error": str(e)})

    # Build competitors across all valid divisions and fill ratings per division
    s3_client = get_s3_client()

    rows = []

    for entry in json_data:
        division_name = entry["FriendlyName"]
        division_name = weightre.sub("", division_name)

        try:
            parsed = parse_division(division_name)
        except ValueError:
            log.debug(f"Invalid division name: {division_name}")
            continue

        age_lower = parsed["age"].lower()
        if not (
            "master" in age_lower
            or "adult" in age_lower
            or "juven" in age_lower
            or "teen" in age_lower
        ):
            continue

        # competitors for this division
        for competitor in entry["RegistrationCategories"]:
            team = competitor.get("AcademyTeamName")
            name = competitor.get("AthleteName")
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
                    "percentile": None,
                    "note": None,
                    "last_weight": None,
                    "slug": None,
                    "instagram_profile": None,
                    "instagram_profile_personal_name": None,
                    "profile_image_url": None,
                    "country": None,
                    "country_note": None,
                    "country_note_pt": None,
                    "age": parsed["age"],
                    "belt": parsed["belt"],
                    "weight": parsed["weight"],
                    "gender": parsed["gender"],
                    "gi": gi,
                }
            )

    if not rows:
        return jsonify({"elites": []})

    get_ratings(
        rows,
        None,
        gi,
        datetime.now() + timedelta(days=1),
        False,
        s3_client,
        elite_only=True,
    )

    elites = []
    for row in rows:
        # Build category string to return for clarity
        category = f"{row['belt']} / {row['age']} / {row['gender']} / {row['weight']}"

        elites.append(
            {
                "name": row["name"],
                "team": row["team"],
                "id": row["id"],
                "slug": row["slug"],
                "rating": row["rating"],
                "match_count": row["match_count"],
                "rank": row["rank"],
                "percentile": row["percentile"],
                "category": category,
                "belt": row["belt"],
                "age": row["age"],
                "gender": row["gender"],
                "weight": row["weight"],
                "gi": gi,
            }
        )

    return jsonify({"elites": elites})


def compute_match_ratings(matches, results, belt, weight, age):
    athlete_results = {}
    athlete_ratings = {}
    athlete_match_counts = {}
    athlete_percentiles = {}
    for result in results:
        ibjjf_id = result["ibjjf_id"]
        athlete_results[ibjjf_id] = result
        athlete_ratings[ibjjf_id] = result["rating"]
        athlete_match_counts[ibjjf_id] = result["match_count"]
        athlete_percentiles[ibjjf_id] = result["percentile"]

    for i in range(len(matches)):
        match = matches[i]

        red_id = match["red_id"]
        red_weight = match["red_weight"]
        red_ordinal = None
        red_rating = None
        red_end_rating = None
        red_match_count = None
        red_slug = None
        red_instagram_profile = None
        red_personal_name = None
        red_profile_image_url = None
        red_country = None
        red_country_note = None
        red_country_note_pt = None
        red_percentile = None
        red_name = match["red_name"]
        if red_id in athlete_results:
            if (
                OPEN_CLASS in weight
                and athlete_results[red_id]["last_weight"] is not None
            ):
                red_weight = athlete_results[red_id]["last_weight"]
            red_ordinal = athlete_results[red_id]["ordinal"]
            red_rating = athlete_ratings[red_id]
            red_end_rating = athlete_ratings[red_id]
            red_match_count = athlete_match_counts[red_id]
            red_name = athlete_results[red_id]["name"]
            red_slug = athlete_results[red_id]["slug"]
            red_instagram_profile = athlete_results[red_id]["instagram_profile"]
            red_personal_name = athlete_results[red_id]["personal_name"]
            red_profile_image_url = athlete_results[red_id]["profile_image_url"]
            red_country = athlete_results[red_id]["country"]
            red_country_note = athlete_results[red_id]["country_note"]
            red_country_note_pt = athlete_results[red_id]["country_note_pt"]
            red_percentile = athlete_percentiles[red_id]
        red_expected = None
        red_handicap = 0
        blue_id = match["blue_id"]
        blue_weight = match["blue_weight"]
        blue_ordinal = None
        blue_rating = None
        blue_end_rating = None
        blue_match_count = None
        blue_slug = None
        blue_instagram_profile = None
        blue_personal_name = None
        blue_profile_image_url = None
        blue_country = None
        blue_country_note = None
        blue_country_note_pt = None
        blue_percentile = None
        blue_name = match["blue_name"]
        if blue_id in athlete_results:
            if (
                OPEN_CLASS in weight
                and athlete_results[blue_id]["last_weight"] is not None
            ):
                blue_weight = athlete_results[blue_id]["last_weight"]
            blue_ordinal = athlete_results[blue_id]["ordinal"]
            blue_rating = athlete_ratings[blue_id]
            blue_end_rating = athlete_ratings[blue_id]
            blue_match_count = athlete_match_counts[blue_id]
            blue_name = athlete_results[blue_id]["name"]
            blue_slug = athlete_results[blue_id]["slug"]
            blue_instagram_profile = athlete_results[blue_id]["instagram_profile"]
            blue_personal_name = athlete_results[blue_id]["personal_name"]
            blue_profile_image_url = athlete_results[blue_id]["profile_image_url"]
            blue_country = athlete_results[blue_id]["country"]
            blue_country_note = athlete_results[blue_id]["country_note"]
            blue_country_note_pt = athlete_results[blue_id]["country_note_pt"]
            blue_percentile = athlete_percentiles[blue_id]
        blue_expected = None
        blue_handicap = 0

        if red_rating is not None and blue_rating is not None and age in rated_ages:
            if (
                red_weight != blue_weight
                and red_weight != "Unknown"
                and blue_weight != "Unknown"
            ):
                red_handicap, blue_handicap = weight_handicaps(
                    belt, red_weight, blue_weight
                )

            red_k_factor = compute_k_factor(red_match_count, False, age)
            blue_k_factor = compute_k_factor(blue_match_count, False, age)

            red_elo = EloCompetitor(red_rating + red_handicap, red_k_factor)
            blue_elo = EloCompetitor(blue_rating + blue_handicap, blue_k_factor)

            red_expected = red_elo.expected_score(blue_elo)
            blue_expected = blue_elo.expected_score(red_elo)

            if (
                not match_didnt_happen(match["red_note"], match["blue_note"])
                and not (not match["red_loser"] and not match["blue_loser"])
                and not (
                    match["red_loser"]
                    and match["blue_loser"]
                    and not match["red_note"]
                    and not match["blue_note"]
                )
            ):
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

                athlete_ratings[red_id] = red_end_rating
                athlete_ratings[blue_id] = blue_end_rating
                athlete_match_counts[red_id] = red_match_count + 1
                athlete_match_counts[blue_id] = blue_match_count + 1

        match["red_ordinal"] = red_ordinal
        match["red_rating"] = red_rating
        match["red_expected"] = red_expected
        match["red_handicap"] = red_handicap
        match["red_weight"] = red_weight
        match["red_end_rating"] = red_end_rating
        match["red_slug"] = red_slug
        match["red_instagram_profile"] = red_instagram_profile
        match["red_personal_name"] = red_personal_name
        match["red_profile_image_url"] = red_profile_image_url
        match["red_country"] = red_country
        match["red_country_note"] = red_country_note
        match["red_country_note_pt"] = red_country_note_pt
        match["red_percentile"] = red_percentile
        match["red_match_count"] = red_match_count
        match["red_name"] = red_name

        match["blue_ordinal"] = blue_ordinal
        match["blue_rating"] = blue_rating
        match["blue_expected"] = blue_expected
        match["blue_handicap"] = blue_handicap
        match["blue_weight"] = blue_weight
        match["blue_end_rating"] = blue_end_rating
        match["blue_match_count"] = blue_match_count
        match["blue_slug"] = blue_slug
        match["blue_instagram_profile"] = blue_instagram_profile
        match["blue_personal_name"] = blue_personal_name
        match["blue_profile_image_url"] = blue_profile_image_url
        match["blue_country"] = blue_country
        match["blue_country_note"] = blue_country_note
        match["blue_country_note_pt"] = blue_country_note_pt
        match["blue_percentile"] = blue_percentile
        match["blue_name"] = blue_name


def parse_match(match, weight):
    when = parse_match_when(match, datetime.now().year)
    where, fight_num = parse_match_where(match)

    matchnum = None
    card = match.find("div", class_="tournament-category__match-card")
    for classname in card.attrs["class"]:
        if classname.startswith("match-"):
            matchnum = classname.split("-")[1]
            break
    if matchnum is None:
        log.info("No match number found")
        return None

    try:
        matchnum = int(matchnum)
    except ValueError:
        log.info("Invalid match number:", matchnum)
        return None

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
        "match_num": matchnum,
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
        "red_match_count": None,
        "red_slug": None,
        "red_instagram_profile": None,
        "red_personal_name": None,
        "red_profile_image_url": None,
        "red_country": None,
        "red_country_note": None,
        "red_country_note_pt": None,
        "red_percentile": None,
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
        "blue_match_count": None,
        "blue_slug": None,
        "blue_instagram_profile": None,
        "blue_personal_name": None,
        "blue_profile_image_url": None,
        "blue_country": None,
        "blue_country_note": None,
        "blue_country_note_pt": None,
        "blue_percentile": None,
    }


def dq_earlier_matches(matches):
    for i in range(len(matches)):
        match = matches[i]

        if match_didnt_happen(match["red_note"], match["red_note"]):
            for j in range(i):
                earlier_match = matches[j]
                if earlier_match["red_id"] == match["red_id"]:
                    earlier_match["red_note"] = match["red_note"]
                elif earlier_match["blue_id"] == match["red_id"]:
                    earlier_match["blue_note"] = match["red_note"]
        if match_didnt_happen(match["blue_note"], match["blue_note"]):
            for j in range(i):
                earlier_match = matches[j]
                if earlier_match["red_id"] == match["blue_id"]:
                    earlier_match["red_note"] = match["blue_note"]
                elif earlier_match["blue_id"] == match["blue_id"]:
                    earlier_match["blue_note"] = match["blue_note"]


def update_live_ratings_thread(gi, results, division_id, last_match_whens):
    from app import app

    log = logging.getLogger("ibjjf")
    with app.app_context():
        try:
            update_live_ratings(gi, results, division_id, last_match_whens)
        except Exception as e:
            log.error(f"Error updating live ratings: {e}")


def update_live_ratings(gi, results, division_id, happened_at_by_id):
    athlete_ids = [
        r["id"]
        for r in results
        if r["id"] is not None
        and r["end_rating"] is not None
        and r["end_match_count"] is not None
    ]

    # delete existing ratings for these athletes which are more than 3 days old
    three_days_ago = datetime.now() - timedelta(days=3)
    db.session.query(LiveRating).filter(
        LiveRating.athlete_id.in_(athlete_ids), LiveRating.happened_at < three_days_ago
    ).delete()

    existing = (
        db.session.query(LiveRating)
        .filter(
            LiveRating.gi == gi,
            LiveRating.athlete_id.in_(athlete_ids),
            LiveRating.division_id == division_id,
        )
        .all()
    )
    existing_by_id = {}
    for rating in existing:
        if rating.athlete_id not in existing_by_id:
            existing_by_id[rating.athlete_id] = []
        existing_by_id[rating.athlete_id].append(rating)

    for result in results:
        if result["id"] is None:
            continue

        happened_at = happened_at_by_id.get(result["ibjjf_id"])
        if happened_at is None:
            continue

        happened_at_dt = datetime.fromisoformat(happened_at)

        deleted_existing = False

        existing_ratings = existing_by_id.get(result["id"])
        if existing_ratings is not None:
            # delete existing
            for rating in existing_ratings:
                db.session.delete(rating)
            deleted_existing = True

        if existing_ratings is None or deleted_existing:
            new_rating = LiveRating(
                gi=gi,
                athlete_id=result["id"],
                happened_at=happened_at_dt,
                division_id=division_id,
                rating=result["end_rating"],
                match_count=result["end_match_count"],
            )
            db.session.add(new_rating)

    db.session.commit()


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

    validlinkmatch = validlink.search(link)
    if not validlinkmatch:
        return jsonify({"error": "Invalid link"}), 400
    event_id = validlinkmatch.group(1)

    s3_client = get_s3_client()

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
                        "percentile": None,
                        "note": None,
                        "last_weight": None,
                        "next_where": None,
                        "next_when": None,
                        "slug": None,
                        "instagram_profile": None,
                        "personal_name": None,
                        "profile_image_url": None,
                        "country": None,
                        "country_note": None,
                        "country_note_pt": None,
                        "age": age,
                        "belt": belt,
                        "weight": weight,
                        "gender": gender,
                        "gi": gi,
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

    get_ratings(
        results,
        event_id,
        gi,
        earliest_match_date,
        True,
        s3_client,
    )

    compute_match_ratings(parsed_matches, results, belt, weight, age)

    dq_earlier_matches(parsed_matches)

    for result in results:
        if result["name"] in medals:
            result["medal"] = medals[result["name"]]

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
            result["end_match_count"] = (
                last_match["red_match_count"] + 1
                if last_match["red_id"] == result["ibjjf_id"]
                else last_match["blue_match_count"] + 1
            )

            if (
                not last_match["red_loser"]
                and not last_match["blue_loser"]
                and not (last_match["red_note"] or last_match["blue_note"])
            ):
                result["next_where"] = last_match["where"]
                result["next_when"] = last_match["when"]
        else:
            result["end_rating"] = result["rating"]
            result["end_match_count"] = result["match_count"]

        first_match = next(
            (
                m
                for m in parsed_matches
                if m["red_id"] == result["ibjjf_id"]
                or m["blue_id"] == result["ibjjf_id"]
            ),
            None,
        )
        if first_match:
            result["note"] = (
                first_match["red_note"]
                if first_match["red_id"] == result["ibjjf_id"]
                else first_match["blue_note"]
            ) or result["note"]

    final = next((m for m in parsed_matches if m["final"]), None)
    if final:
        if (
            (
                (final["blue_medal"] == "1" and final["red_medal"] == "2")
                or (final["red_medal"] == "1" and final["blue_medal"] == "2")
            )
            and final["red_team"] == final["blue_team"]
            and final["red_team"] is not None
        ):
            if final["red_medal"] == "1":
                if not final["blue_note"]:
                    final["blue_note"] = CLOSEOUT_NOTE
                else:
                    final["blue_note"] = f'{final["blue_note"]}, {CLOSEOUT_NOTE}'
            else:
                if not final["red_note"]:
                    final["red_note"] = CLOSEOUT_NOTE
                else:
                    final["red_note"] = f'{final["red_note"]}, {CLOSEOUT_NOTE}'

    last_match_whens = {}
    for m in parsed_matches:
        if m["red_id"] is not None:
            if m["red_id"] not in last_match_whens or (
                m["when"] and m["when"] > last_match_whens[m["red_id"]]
            ):
                last_match_whens[m["red_id"]] = m["when"]
        if m["blue_id"] is not None:
            if m["blue_id"] not in last_match_whens or (
                m["when"] and m["when"] > last_match_whens[m["blue_id"]]
            ):
                last_match_whens[m["blue_id"]] = m["when"]

    division = (
        db.session.query(Division)
        .filter(
            Division.gi == gi,
            Division.age == age,
            Division.belt == belt,
            Division.weight == weight,
            Division.gender == gender,
        )
        .first()
    )

    if len(last_match_whens) and division is not None:
        thread = threading.Thread(
            target=update_live_ratings_thread,
            args=(gi, results, division.id, last_match_whens),
        )
        thread.start()

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
                get_bracket_page(url, datetime.now() - timedelta(minutes=10)),
                "html.parser",
            )
        except Exception as e:
            return jsonify({"error": str(e)})

        categories = parse_categories(soup)

        for category in categories:
            try:
                category["age"] = translate_age_keep_juvenile(category["age"])
                category["belt"] = translate_belt(category["belt"])
                category["weight"] = translate_weight(category["weight"])
            except ValueError:
                continue
            category["gender"] = gender
            results.append(category)

    results = sorted(
        results,
        key=lambda x: (
            belt_order.index(x["belt"]),
            age_order_all.index(x["age"]),
            gender_order.index(x["gender"]),
            weight_class_order_all.index(x["weight"]),
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

    def sort_key(name):
        name = name.lower()

        if "kids" in name or "crianças" in name or "15 anos" in name:
            return (2, name)
        elif (
            "world ibjjf" in name
            or "european ibjjf" in name
            or "pan ibjjf" in name
            or "campeonato brasileiro" in name
        ):
            return (0, name)
        else:
            return (1, name)

    tournaments = sorted(tournaments, key=lambda x: sort_key(x["name"]))

    return jsonify({"events": tournaments})


@brackets_route.route("/api/brackets/archive/categories")
def archive_categories():
    event_name = request.args.get("event_name")

    if not event_name:
        return jsonify({"error": "Missing parameter"}), 400

    if event_name.startswith('"') and event_name.endswith('"'):
        event_name = event_name[1:-1]

    division_ids = (
        db.session.query(Match.division_id)
        .join(Event)
        .join(Division)
        .filter(Event.name == event_name)
        .filter(Division.age != JUVENILE)
        .all()
    )

    if not division_ids:
        return jsonify({"categories": []}), 200

    divisions = (
        db.session.query(Division)
        .filter(Division.id.in_([d[0] for d in division_ids]))
        .all()
    )

    divisions.sort(
        key=lambda x: (
            belt_order.index(x.belt),
            age_order_all.index(x.age),
            gender_order.index(x.gender),
            weight_class_order_all.index(x.weight),
        )
    )

    return jsonify(
        {
            "categories": [
                {
                    "age": division.age,
                    "belt": division.belt,
                    "weight": division.weight,
                    "gender": division.gender,
                }
                for division in divisions
            ],
        }
    )


@brackets_route.route("/api/brackets/archive/competitors")
def archive_competitors():
    event_name = request.args.get("event_name")
    age = request.args.get("age")
    belt = request.args.get("belt")
    weight = request.args.get("weight")
    gender = request.args.get("gender")
    gi = request.args.get("gi")

    if not event_name or not age or not belt or not weight or not gender or not gi:
        return jsonify({"error": "Missing parameter"}), 400

    gi = gi.lower() == "true"

    if event_name.startswith('"') and event_name.endswith('"'):
        event_name = event_name[1:-1]

    event = db.session.query(Event).filter(Event.name == event_name).first()

    if not event:
        return jsonify({"error": "Event not found"}), 404

    division = (
        db.session.query(Division)
        .filter(
            Division.age == age,
            Division.belt == belt,
            Division.weight == weight,
            Division.gender == gender,
            Division.gi == gi,
        )
        .first()
    )

    if not division:
        return jsonify({"error": "Division not found"}), 404

    matches = (
        db.session.query(Match)
        .filter(
            Match.event_id == event.id,
            Match.division_id == division.id,
        )
        .order_by(Match.happened_at)
        .all()
    )

    medals = (
        db.session.query(Medal)
        .filter(
            Medal.event_id == event.id,
            Medal.division_id == division.id,
        )
        .all()
    )

    medals_by_id = {}
    for medal in medals:
        medals_by_id[str(medal.athlete_id)] = str(medal.place)

    use_seeds = "idade 04 a 15 anos" in event_name or "(" not in event_name

    s3_client = get_s3_client()

    competitors = []
    parsed_matches = []
    for match in matches:
        red = [p for p in match.participants if p.red][0]
        blue = [p for p in match.participants if not p.red][0]

        red_weight = red.weight_for_open or weight
        blue_weight = blue.weight_for_open or weight

        # If weight is open class it means we don't know the actual weight
        if red_weight.startswith(OPEN_CLASS) or blue_weight.startswith(OPEN_CLASS):
            red_handicap, blue_handicap = 0, 0
            if red_weight.startswith(OPEN_CLASS):
                red_weight = None
            if blue_weight.startswith(OPEN_CLASS):
                blue_weight = None
        else:
            red_handicap, blue_handicap = weight_handicaps(
                belt, red_weight, blue_weight
            )

        blue_elo = EloCompetitor(blue.start_rating + blue_handicap, 32)
        red_elo = EloCompetitor(red.start_rating + red_handicap, 32)

        blue_note = blue.note
        if blue.rating_note == CLOSEOUT_NOTE:
            if not blue_note:
                blue_note = CLOSEOUT_NOTE
            else:
                blue_note = f"{blue_note}, {CLOSEOUT_NOTE}"
        red_note = red.note
        if red.rating_note == CLOSEOUT_NOTE:
            if not red_note:
                red_note = CLOSEOUT_NOTE
            else:
                red_note = f"{red_note}, {CLOSEOUT_NOTE}"

        parsed_matches.append(
            {
                "match_num": match.match_number,
                "final": False,
                "when": match.happened_at.isoformat(),
                "where": match.match_location,
                "fight_num": match.fight_number,
                "red_bye": False,
                "red_id": str(red.athlete_id),
                "red_seed": red.seed if use_seeds else None,
                "red_loser": not red.winner,
                "red_name": red.athlete.name,
                "red_team": red.team.name,
                "red_note": red_note,
                "red_next_description": None,
                "red_ordinal": None,
                "red_rating": red.start_rating,
                "red_end_rating": red.end_rating,
                "red_expected": red_elo.expected_score(blue_elo),
                "red_handicap": red_handicap,
                "red_weight": red_weight,
                "red_medal": None,
                "red_match_count": red.start_match_count,
                "red_slug": red.athlete.slug,
                "red_instagram_profile": red.athlete.instagram_profile,
                "red_personal_name": red.athlete.personal_name,
                "red_profile_image_url": (
                    get_public_photo_url(s3_client, red.athlete)
                    if red.athlete.profile_image_saved_at
                    else None
                ),
                "red_country": red.athlete.country,
                "red_country_note": red.athlete.country_note,
                "red_country_note_pt": red.athlete.country_note_pt,
                "blue_bye": False,
                "blue_id": str(blue.athlete_id),
                "blue_seed": blue.seed if use_seeds else None,
                "blue_loser": not blue.winner,
                "blue_name": blue.athlete.name,
                "blue_team": blue.team.name,
                "blue_note": blue_note,
                "blue_next_description": None,
                "blue_ordinal": None,
                "blue_rating": blue.start_rating,
                "blue_end_rating": blue.end_rating,
                "blue_expected": blue_elo.expected_score(red_elo),
                "blue_handicap": blue_handicap,
                "blue_weight": blue_weight,
                "blue_medal": None,
                "blue_match_count": blue.start_match_count,
                "blue_slug": blue.athlete.slug,
                "blue_instagram_profile": blue.athlete.instagram_profile,
                "blue_personal_name": blue.athlete.personal_name,
                "blue_profile_image_url": (
                    get_public_photo_url(s3_client, blue.athlete)
                    if blue.athlete.profile_image_saved_at
                    else None
                ),
                "blue_country": blue.athlete.country,
                "blue_country_note": blue.athlete.country_note,
                "blue_country_note_pt": blue.athlete.country_note_pt,
            }
        )

    if len(parsed_matches):
        parsed_matches[-1]["final"] = True

    for athlete_id, medal in medals_by_id.items():
        for match in parsed_matches[::-1]:
            if match["red_id"] == athlete_id:
                match["red_medal"] = medal
                break
            elif match["blue_id"] == athlete_id:
                match["blue_medal"] = medal
                break

    added_competitors = set()
    for match in parsed_matches:
        if match["red_id"] not in added_competitors:
            competitors.append(
                {
                    "id": match["red_id"],
                    "ibjjf_id": match["red_id"],
                    "seed": match["red_seed"],
                    "name": match["red_name"],
                    "team": match["red_team"],
                    "slug": match["red_slug"],
                    "instagram_profile": match["red_instagram_profile"],
                    "personal_name": match["red_personal_name"],
                    "profile_image_url": match["red_profile_image_url"],
                    "country": match["red_country"],
                    "country_note": match["red_country_note"],
                    "country_note_pt": match["red_country_note_pt"],
                    "rating": match["red_rating"],
                    "end_rating": match["red_end_rating"],
                    "match_count": match["red_match_count"],
                    "end_match_count": match["red_match_count"],
                    "rank": None,
                    "percentile": None,
                    "note": match["red_note"],
                    "last_weight": match["red_weight"],
                    "medal": match["red_medal"],
                    "next_where": None,
                    "next_when": None,
                    "age": age,
                    "belt": belt,
                    "weight": weight,
                    "gender": gender,
                    "gi": gi,
                }
            )
            added_competitors.add(match["red_id"])
        else:
            existing = [c for c in competitors if c["ibjjf_id"] == match["red_id"]][0]
            existing["end_rating"] = match["red_end_rating"]
            existing["end_match_count"] = match["red_match_count"]
            existing["medal"] = match["red_medal"]
        if match["blue_id"] not in added_competitors:
            competitors.append(
                {
                    "id": match["blue_id"],
                    "ibjjf_id": match["blue_id"],
                    "seed": match["blue_seed"],
                    "name": match["blue_name"],
                    "team": match["blue_team"],
                    "slug": match["blue_slug"],
                    "instagram_profile": match["blue_instagram_profile"],
                    "personal_name": match["blue_personal_name"],
                    "profile_image_url": match["blue_profile_image_url"],
                    "country": match["blue_country"],
                    "country_note": match["blue_country_note"],
                    "country_note_pt": match["blue_country_note_pt"],
                    "rating": match["blue_rating"],
                    "end_rating": match["blue_end_rating"],
                    "match_count": match["blue_match_count"],
                    "end_match_count": match["blue_match_count"],
                    "rank": None,
                    "percentile": None,
                    "note": match["blue_note"],
                    "last_weight": match["blue_weight"],
                    "medal": match["blue_medal"],
                    "next_where": None,
                    "next_when": None,
                    "belt": belt,
                    "age": age,
                    "weight": weight,
                    "gender": gender,
                    "gi": gi,
                }
            )
            added_competitors.add(match["blue_id"])
        else:
            existing = [c for c in competitors if c["ibjjf_id"] == match["blue_id"]][0]
            existing["end_rating"] = match["blue_end_rating"]
            existing["end_match_count"] = match["blue_match_count"]
            existing["medal"] = match["blue_medal"]

    competitors.sort(key=lambda x: competitor_sort_key(x, "rating"), reverse=True)

    compute_ordinals(competitors, weight, belt)

    ordinals_by_id = {}
    for competitor in competitors:
        ordinals_by_id[competitor["ibjjf_id"]] = competitor["ordinal"]

    for match in parsed_matches:
        if match["red_id"] in ordinals_by_id:
            match["red_ordinal"] = ordinals_by_id[match["red_id"]]
        if match["blue_id"] in ordinals_by_id:
            match["blue_ordinal"] = ordinals_by_id[match["blue_id"]]

    return jsonify(
        {
            "competitors": competitors,
            "matches": parsed_matches,
        }
    )
