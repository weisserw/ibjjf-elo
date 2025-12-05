import os
from flask import Blueprint, request, jsonify
from datetime import datetime
from sqlalchemy.sql import text
from extensions import db
from constants import (
    MALE,
    FEMALE,
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    JUVENILE,
    TEEN_1,
    TEEN_2,
    TEEN_3,
    GREY,
    YELLOW,
    YELLOW_GREY,
    ORANGE,
    GREEN,
    GREEN_ORANGE,
    WHITE,
    BLUE,
    PURPLE,
    BROWN,
    BLACK,
    ROOSTER,
    LIGHT_FEATHER,
    FEATHER,
    LIGHT,
    MIDDLE,
    MEDIUM_HEAVY,
    HEAVY,
    SUPER_HEAVY,
    ULTRA_HEAVY,
    OPEN_CLASS,
    OPEN_CLASS_LIGHT,
    OPEN_CLASS_HEAVY,
)
from models import Athlete, MatchParticipant, Division, Match, Event
from photos import get_public_photo_url, get_s3_client
from normalize import normalize
from collections import defaultdict
from time import time
from urllib.parse import quote

matches_route = Blueprint("matches_route", __name__)

MATCH_PAGE_SIZE = 12
ATHLETES_MATCH_PAGE_SIZE = 100

INITIAL_RATE_LIMIT = 15
RATE_LIMIT_WINDOW = 10
PENALTY_PERIOD = 60
client_requests = defaultdict(list)
client_penalties = {}


def rate_limit():
    client_ip = request.headers.get("CF-Connecting-IP")
    if not client_ip:
        client_ip = request.headers.get("DO-Connecting-IP")
        if not client_ip:
            return

    current_time = time()
    request_times = client_requests[client_ip]
    penalty_info = client_penalties.get(
        client_ip, {"rate_limit": INITIAL_RATE_LIMIT, "penalty_end": 0}
    )

    if current_time > penalty_info["penalty_end"]:
        penalty_info["rate_limit"] = INITIAL_RATE_LIMIT
        penalty_info["penalty_end"] = 0
        client_penalties[client_ip] = penalty_info

    while request_times and request_times[0] < current_time - RATE_LIMIT_WINDOW:
        request_times.pop(0)

    if len(request_times) >= penalty_info["rate_limit"]:
        penalty_info["rate_limit"] = max(1, penalty_info["rate_limit"] // 2)
        penalty_info["penalty_end"] = current_time + PENALTY_PERIOD
        client_penalties[client_ip] = penalty_info
        return jsonify({"error": "Too many requests"}), 429

    request_times.append(current_time)


matches_route.before_request(rate_limit)


def name_components(name):
    return [
        n
        for n in name.strip().split()
        if n.lower() not in ["jr.", "sr.", "jr", "sr", "2nd", "3rd", "ii", "iii"]
        and not n.startswith('"')
    ]


def get_search_name(full_name, personal_name):
    if personal_name:
        names = name_components(personal_name)
        if len(names):
            return " ".join(names[:2])

    names = name_components(full_name)
    return " ".join(names[:2])


@matches_route.route("/api/matches")
def matches():
    gi = request.args.get("gi")
    athlete_id = request.args.get("athlete_id")
    athlete_name = request.args.get("athlete_name")
    athlete_name2 = request.args.get("athlete_name2")
    event_name = request.args.get("event_name")
    gender_male = request.args.get("gender_male")
    gender_female = request.args.get("gender_female")
    age_adult = request.args.get("age_adult")
    age_master1 = request.args.get("age_master1")
    age_master2 = request.args.get("age_master2")
    age_master3 = request.args.get("age_master3")
    age_master4 = request.args.get("age_master4")
    age_master5 = request.args.get("age_master5")
    age_master6 = request.args.get("age_master6")
    age_master7 = request.args.get("age_master7")
    age_juvenile = request.args.get("age_juvenile")
    age_teen = request.args.get("age_teen")
    belt_grey = request.args.get("belt_grey")
    belt_yellow = request.args.get("belt_yellow")
    belt_orange = request.args.get("belt_orange")
    belt_green = request.args.get("belt_green")
    belt_white = request.args.get("belt_white")
    belt_blue = request.args.get("belt_blue")
    belt_purple = request.args.get("belt_purple")
    belt_brown = request.args.get("belt_brown")
    belt_black = request.args.get("belt_black")
    weight_rooster = request.args.get("weight_rooster")
    weight_light_feather = request.args.get("weight_light_feather")
    weight_feather = request.args.get("weight_feather")
    weight_light = request.args.get("weight_light")
    weight_middle = request.args.get("weight_middle")
    weight_medium_heavy = request.args.get("weight_medium_heavy")
    weight_heavy = request.args.get("weight_heavy")
    weight_super_heavy = request.args.get("weight_super_heavy")
    weight_ultra_heavy = request.args.get("weight_ultra_heavy")
    weight_open_class = request.args.get("weight_open_class")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    mat_number = request.args.get("mat_number")
    rating_start = request.args.get("rating_start")
    rating_end = request.args.get("rating_end")
    page = request.args.get("page") or 1

    if gi is None:
        return jsonify({"error": "Missing mandatory query parameter"}), 400

    try:
        page = int(page)
        if page < 1:
            raise ValueError()
    except ValueError:
        return jsonify({"error": "Invalid page number"}), 400

    if gi:
        gi = gi.lower() == "true"
    if gender_male:
        gender_male = gender_male.lower() == "true"
    if gender_female:
        gender_female = gender_female.lower() == "true"
    if age_adult:
        age_adult = age_adult.lower() == "true"
    if age_master1:
        age_master1 = age_master1.lower() == "true"
    if age_master2:
        age_master2 = age_master2.lower() == "true"
    if age_master3:
        age_master3 = age_master3.lower() == "true"
    if age_master4:
        age_master4 = age_master4.lower() == "true"
    if age_master5:
        age_master5 = age_master5.lower() == "true"
    if age_master6:
        age_master6 = age_master6.lower() == "true"
    if age_master7:
        age_master7 = age_master7.lower() == "true"
    if age_juvenile:
        age_juvenile = age_juvenile.lower() == "true"
    if age_teen:
        age_teen = age_teen.lower() == "true"
    if belt_grey:
        belt_grey = belt_grey.lower() == "true"
    if belt_yellow:
        belt_yellow = belt_yellow.lower() == "true"
    if belt_orange:
        belt_orange = belt_orange.lower() == "true"
    if belt_green:
        belt_green = belt_green.lower() == "true"
    if belt_white:
        belt_white = belt_white.lower() == "true"
    if belt_blue:
        belt_blue = belt_blue.lower() == "true"
    if belt_purple:
        belt_purple = belt_purple.lower() == "true"
    if belt_brown:
        belt_brown = belt_brown.lower() == "true"
    if belt_black:
        belt_black = belt_black.lower() == "true"
    if weight_rooster:
        weight_rooster = weight_rooster.lower() == "true"
    if weight_light_feather:
        weight_light_feather = weight_light_feather.lower() == "true"
    if weight_feather:
        weight_feather = weight_feather.lower() == "true"
    if weight_light:
        weight_light = weight_light.lower() == "true"
    if weight_middle:
        weight_middle = weight_middle.lower() == "true"
    if weight_medium_heavy:
        weight_medium_heavy = weight_medium_heavy.lower() == "true"
    if weight_heavy:
        weight_heavy = weight_heavy.lower() == "true"
    if weight_super_heavy:
        weight_super_heavy = weight_super_heavy.lower() == "true"
    if weight_ultra_heavy:
        weight_ultra_heavy = weight_ultra_heavy.lower() == "true"
    if weight_open_class:
        weight_open_class = weight_open_class.lower() == "true"

    params = {"gi": gi}

    filters = ""

    if athlete_id:
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND mp.athlete_id = :athlete_id
        )
        """
        if os.environ.get("DATABASE_URL"):
            params["athlete_id"] = athlete_id
        else:
            params["athlete_id"] = athlete_id.replace("-", "")

    def add_athlete_name_filter(f, name, variable):
        exact = name.strip().startswith('"') and name.strip().endswith('"')
        if exact:
            name = name.strip()[1:-1]
            f += f"""AND EXISTS (
                SELECT 1
                FROM athletes a
                JOIN match_participants mp ON a.id = mp.athlete_id
                WHERE mp.match_id = m.id
                AND a.normalized_name = :{variable}
            )
            """
            params[variable] = normalize(name)
        elif os.getenv("DATABASE_URL"):
            # Use full-text search
            search_terms = " & ".join([term + ":*" for term in normalize(name).split()])
            f += f"""AND EXISTS (
                    SELECT 1
                    FROM athletes a
                    JOIN match_participants mp ON a.id = mp.athlete_id
                    WHERE mp.match_id = m.id
                    AND (
                        a.normalized_name_tsvector @@ to_tsquery('simple', :{variable})
                        OR a.normalized_personal_name_tsvector @@ to_tsquery('simple', :{variable})
                    )
                )"""
            params[variable] = search_terms
        else:
            # Fallback to LIKE search
            for index, name_part in enumerate(normalize(name).split()):
                f += f"""
                AND EXISTS (
                    SELECT 1
                    FROM athletes a
                    JOIN match_participants mp ON a.id = mp.athlete_id
                    WHERE mp.match_id = m.id
                    AND a.normalized_name LIKE :{variable}_{index}
                )"""
                params[f"{variable}_{index}"] = f"%{name_part}%"
        return f

    if athlete_name:
        filters = add_athlete_name_filter(filters, athlete_name, "athlete_name")
    if athlete_name2:
        filters = add_athlete_name_filter(filters, athlete_name2, "athlete_name2")

    if event_name:
        operator = "LIKE"
        exact = event_name.strip().startswith('"') and event_name.strip().endswith('"')
        if exact:
            operator = "="
            event_name = event_name.strip()[1:-1]
        filters += f"AND e.normalized_name {operator} :event_name\n"
        if exact:
            params["event_name"] = normalize(event_name)
        else:
            params["event_name"] = f"%{normalize(event_name)}%"

    genders = []
    if gender_male:
        genders.append(MALE)
    if gender_female:
        genders.append(FEMALE)
    if len(genders):
        filters += "AND d.gender IN (" + ", ".join(f"'{g}'" for g in genders) + ")\n"

    ages = []
    if age_adult:
        ages.append(ADULT)
    if age_master1:
        ages.append(MASTER_1)
    if age_master2:
        ages.append(MASTER_2)
    if age_master3:
        ages.append(MASTER_3)
    if age_master4:
        ages.append(MASTER_4)
    if age_master5:
        ages.append(MASTER_5)
    if age_master6:
        ages.append(MASTER_6)
    if age_master7:
        ages.append(MASTER_7)
    if age_juvenile:
        ages.append(JUVENILE)
    if age_teen:
        ages.append(TEEN_1)
        ages.append(TEEN_2)
        ages.append(TEEN_3)
    if len(ages):
        filters += "AND d.age IN (" + ", ".join(f"'{a}'" for a in ages) + ")\n"

    belts = []
    if belt_grey:
        belts.append(GREY)
        belts.append(YELLOW_GREY)
    if belt_yellow:
        belts.append(YELLOW)
        belts.append(YELLOW_GREY)
    if belt_orange:
        belts.append(ORANGE)
        belts.append(GREEN_ORANGE)
    if belt_green:
        belts.append(GREEN)
        belts.append(GREEN_ORANGE)
    if belt_white:
        belts.append(WHITE)
    if belt_blue:
        belts.append(BLUE)
    if belt_purple:
        belts.append(PURPLE)
    if belt_brown:
        belts.append(BROWN)
    if belt_black:
        belts.append(BLACK)
    if len(belts):
        filters += "AND d.belt IN (" + ", ".join(f"'{b}'" for b in belts) + ")\n"

    weights = []
    if weight_rooster:
        weights.append(ROOSTER)
    if weight_light_feather:
        weights.append(LIGHT_FEATHER)
    if weight_feather:
        weights.append(FEATHER)
    if weight_light:
        weights.append(LIGHT)
    if weight_middle:
        weights.append(MIDDLE)
    if weight_medium_heavy:
        weights.append(MEDIUM_HEAVY)
    if weight_heavy:
        weights.append(HEAVY)
    if weight_super_heavy:
        weights.append(SUPER_HEAVY)
    if weight_ultra_heavy:
        weights.append(ULTRA_HEAVY)
    if weight_open_class:
        weights.append(OPEN_CLASS)
        weights.append(OPEN_CLASS_LIGHT)
        weights.append(OPEN_CLASS_HEAVY)
    if len(weights):
        filters += "AND d.weight IN (" + ", ".join(f"'{w}'" for w in weights) + ")\n"

    if date_start:
        filters += "AND m.happened_at >= :date_start\n"
        params["date_start"] = datetime.fromisoformat(date_start)
    if date_end:
        filters += "AND m.happened_at <= :date_end\n"
        params["date_end"] = datetime.fromisoformat(date_end)
    if mat_number is not None:
        filters += """AND m.match_location IS NOT NULL AND m.match_location LIKE :mat_number
        """
        params["mat_number"] = f"% {mat_number}"

    if rating_start is not None:
        rating_start_int = int(rating_start)
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating >= :rating_start OR mp.end_rating >= :rating_start)
        )
        """
        params["rating_start"] = rating_start_int
    if rating_end is not None:
        rating_end_int = int(rating_end)
        filters += """AND EXISTS (
            SELECT 1
            FROM match_participants mp
            WHERE mp.match_id = m.id AND (mp.start_rating <= :rating_end OR mp.end_rating <= :rating_end)
        )
        """
        params["rating_end"] = rating_end_int

    sql = f"""
        SELECT m.id, m.happened_at, d.gi, d.gender, d.age, d.belt, d.weight, e.name as event_name, e.ibjjf_id,
            mp.id as participant_id, mp.winner, mp.start_rating, mp.end_rating,
            a.id as athlete_id, a.name, a.slug, a.country, a.country_note, a.country_note_pt, a.instagram_profile, a.personal_name, a.profile_image_saved_at,
            mp.note, m.rated, mp.rating_note, mp.weight_for_open, mp.start_match_count, mp.end_match_count, m.match_location, m.video_link
        FROM matches m
        JOIN divisions d ON m.division_id = d.id
        JOIN events e ON m.event_id = e.id
        JOIN match_participants mp ON m.id = mp.match_id
        JOIN athletes a ON mp.athlete_id = a.id
        WHERE d.gi = :gi
        {filters}
    """

    page_size = MATCH_PAGE_SIZE
    if athlete_name and athlete_name2 and athlete_name != athlete_name2:
        page_size = ATHLETES_MATCH_PAGE_SIZE

    # get one extra match to determine if there are more pages
    params["limit"] = (page_size + 1) * 2
    params["offset"] = (page - 1) * page_size * 2

    results = db.session.execute(
        text(
            f"""
        {sql}
        ORDER BY m.happened_at DESC, m.id DESC
        LIMIT :limit OFFSET :offset
        """
        ),
        params,
    )

    s3_client = get_s3_client()

    event_ids = set()
    response = []
    current_match = None
    for result in results:
        row = result._mapping

        if current_match is None or current_match.id != row["id"]:
            division = Division(
                gi=row["gi"],
                gender=row["gender"],
                age=row["age"],
                belt=row["belt"],
                weight=row["weight"],
            )
            event = Event(name=row["event_name"], ibjjf_id=row["ibjjf_id"])

            # sqlite returns a string for datetime fields, but postgres returns a datetime object
            if isinstance(row["happened_at"], str):
                happened_at = datetime.fromisoformat(row["happened_at"])
            else:
                happened_at = row["happened_at"]

            current_match = Match(
                id=row["id"],
                happened_at=happened_at,
                division=division,
                event=event,
                rated=row["rated"],
                match_location=row["match_location"],
                video_link=row["video_link"],
            )

        current_match.participants.append(
            MatchParticipant(
                id=row["participant_id"],
                winner=row["winner"],
                start_rating=row["start_rating"],
                end_rating=row["end_rating"],
                athlete=Athlete(
                    id=row["athlete_id"],
                    name=row["name"],
                    slug=row["slug"],
                    country=row["country"],
                    country_note=row["country_note"],
                    country_note_pt=row["country_note_pt"],
                    instagram_profile=row["instagram_profile"],
                    personal_name=row["personal_name"],
                    profile_image_saved_at=row["profile_image_saved_at"],
                ),
                note=row["note"],
                weight_for_open=row["weight_for_open"],
                rating_note=row["rating_note"],
                start_match_count=row["start_match_count"],
                end_match_count=row["end_match_count"],
            )
        )

        if len(current_match.participants) == 2:
            winner = None
            loser = None
            for participant in current_match.participants:
                if participant.winner:
                    winner = participant
                else:
                    loser = participant

            if winner is None or loser is None:
                winner = current_match.participants[0]
                loser = current_match.participants[1]

            event_ids.add(current_match.event.ibjjf_id)

            response.append(
                {
                    "id": current_match.id,
                    "videoLink": current_match.video_link,
                    "winner": winner.athlete.name,
                    "winnerSlug": winner.athlete.slug,
                    "winnerId": winner.athlete.id,
                    "winnerStartRating": round(winner.start_rating),
                    "winnerEndRating": round(winner.end_rating),
                    "winnerWeightForOpen": winner.weight_for_open,
                    "winnerStartMatchCount": winner.start_match_count,
                    "winnerEndMatchCount": winner.end_match_count,
                    "winnerCountry": winner.athlete.country,
                    "winnerCountryNote": winner.athlete.country_note,
                    "winnerCountryNotePt": winner.athlete.country_note_pt,
                    "winnerInstagramProfile": winner.athlete.instagram_profile,
                    "winnerPersonalName": winner.athlete.personal_name,
                    "winnerProfileImageUrl": (
                        get_public_photo_url(s3_client, winner.athlete)
                        if winner.athlete.profile_image_saved_at
                        else None
                    ),
                    "loser": loser.athlete.name,
                    "loserSlug": loser.athlete.slug,
                    "loserId": loser.athlete.id,
                    "loserStartRating": round(loser.start_rating),
                    "loserEndRating": round(loser.end_rating),
                    "loserWeightForOpen": loser.weight_for_open,
                    "loserStartMatchCount": loser.start_match_count,
                    "loserEndMatchCount": loser.end_match_count,
                    "loserCountry": loser.athlete.country,
                    "loserCountryNote": loser.athlete.country_note,
                    "loserCountryNotePt": loser.athlete.country_note_pt,
                    "loserInstagramProfile": loser.athlete.instagram_profile,
                    "loserPersonalName": loser.athlete.personal_name,
                    "loserProfileImageUrl": (
                        get_public_photo_url(s3_client, loser.athlete)
                        if loser.athlete.profile_image_saved_at
                        else None
                    ),
                    "event": current_match.event.name,
                    "age": current_match.division.age,
                    "gender": current_match.division.gender,
                    "belt": current_match.division.belt,
                    "weight": current_match.division.weight,
                    "date": current_match.happened_at.isoformat(),
                    "rated": current_match.rated,
                    "notes": loser.note or winner.note,
                    "winnerRatingNote": winner.rating_note,
                    "loserRatingNote": loser.rating_note,
                    "matchLocation": current_match.match_location,
                    "event_ibjjf_id": current_match.event.ibjjf_id,
                    "date_happened_at": current_match.happened_at,
                }
            )

    totalPages = page + 1
    if len(response) <= page_size:
        totalPages -= 1

    if len(response) > page_size:
        response = response[:page_size]

    # Fill query results with livestream links
    tournament_days = {}
    live_streams = {}

    if len(event_ids):
        # Build parameterized IN clause for event_ids
        event_id_params = {f"eid_{i}": eid for i, eid in enumerate(event_ids)}
        event_id_placeholders = ", ".join([f":eid_{i}" for i in range(len(event_ids))])

        event_results = db.session.execute(
            text(
                f"""
            SELECT e.ibjjf_id, MIN(m.happened_at) AS min_date
            FROM events e
            JOIN matches m ON e.id = m.event_id
            WHERE e.ibjjf_id IN ({event_id_placeholders})
            GROUP BY e.ibjjf_id
            """
            ),
            event_id_params,
        )
        for ibjjf_id, min_date in event_results:
            min_date_date = min_date
            if isinstance(min_date, str):
                min_date_date = datetime.fromisoformat(min_date)
            tournament_days[ibjjf_id] = min_date_date.date()

        live_streams = {
            (event_id, day_number, mat_number): (link, start_hour, start_minute)
            for event_id, day_number, mat_number, link, start_hour, start_minute in db.session.execute(
                text(
                    f"""
                SELECT event_id, day_number, mat_number, link, start_hour, start_minute
                FROM live_streams
                WHERE event_id IN ({event_id_placeholders})
                """
                ),
                event_id_params,
            )
        }

        flo_event_tags = {
            event_id: tag
            for event_id, tag in db.session.execute(
                text(
                    f"""
                SELECT event_id, tag
                FROM flo_event_tags
                WHERE event_id IN ({event_id_placeholders})
                """
                ),
                event_id_params,
            )
        }

        for match in response:
            if match["videoLink"] is None:
                if match["event_ibjjf_id"] in flo_event_tags:
                    tag = flo_event_tags[match["event_ibjjf_id"]]
                    winner_last_name = get_search_name(
                        match["winner"], match["winnerPersonalName"]
                    )
                    loser_last_name = get_search_name(
                        match["loser"], match["loserPersonalName"]
                    )
                    match["videoLink"] = (
                        f"https://www.flograppling.com/events/{tag}/videos?openInBrowser=1&search={quote(winner_last_name)}%20vs%20{quote(loser_last_name)}"
                    )
                elif len(live_streams):
                    event_start_day = tournament_days.get(match["event_ibjjf_id"])
                    if event_start_day:
                        match_day = match["date_happened_at"].date()
                        match_hour = match["date_happened_at"].hour
                        match_minute = match["date_happened_at"].minute
                        day_number = (match_day - event_start_day).days + 1
                        mat_number = match["matchLocation"]
                        mat_number_int = None
                        if mat_number:
                            try:
                                mat_number_int = int(mat_number.split()[-1])
                            except ValueError:
                                mat_number_int = None
                        if mat_number_int is not None:
                            livestream_info = live_streams.get(
                                (match["event_ibjjf_id"], day_number, mat_number_int)
                            )
                            if livestream_info:
                                link, start_hour, start_minute = livestream_info

                                match_minutes = match_hour * 60 + match_minute
                                start_minutes = start_hour * 60 + start_minute
                                time_offset_mins = match_minutes - start_minutes
                                link += "&t=" + str(time_offset_mins * 60) + "s"

                                match["videoLink"] = link

            del match["event_ibjjf_id"]
            del match["date_happened_at"]

    return jsonify({"rows": response, "totalPages": totalPages})
