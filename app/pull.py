import time
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime
from bs4 import BeautifulSoup
import re
from elo import WINNER_NOT_RECORDED


class InternalServerError(Exception):
    """Custom exception for handling internal server errors."""

    pass


def rate_limit_get(session, url, limit, retries):
    if limit:
        time.sleep(limit)
    if retries is None:
        retries = 0
    count = 1
    while True:
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 500:
                raise InternalServerError(f"Server error for {url}: {resp.status_code}")
            return resp
        except requests.exceptions.ConnectionError:
            if count > retries:
                resp = requests.Response()
                resp.status_code = 503
                resp.reason = "Service Unavailable"
                return resp
            print(f"Connection error, retrying in {30 * count} seconds", flush=True)
            time.sleep(30 * count)
            count += 1
        except requests.exceptions.Timeout:
            if count > retries:
                resp = requests.Response()
                resp.status_code = 504
                resp.reason = "Gateway Timeout"
                return resp
            print(f"Timeout error, retrying in {30 * count} seconds", flush=True)
            time.sleep(30 * count)
            count += 1
        except InternalServerError:
            if count > retries:
                resp = requests.Response()
                resp.status_code = 500
                resp.reason = "Internal Server Error"
                return resp
            print(f"Internal server error, retrying in {30 * count}", flush=True)
            time.sleep(30 * count)
            count += 1
    return None


headers = [
    "Tournament ID",
    "Tournament Name",
    "Link",
    "Gi",
    "Gender",
    "Age",
    "Belt",
    "Weight",
    "Date",
    "Red ID",
    "Red Seed",
    "Red Winner",
    "Red Name",
    "Red Team",
    "Red Note",
    "Red Medal",
    "Blue ID",
    "Blue Seed",
    "Blue Winner",
    "Blue Name",
    "Blue Team",
    "Blue Note",
    "Blue Medal",
    "Match Number",
]


def parse_categories(soup):
    categories = soup.find_all("li", class_="categories-grid__category")

    results = []
    for category in categories:
        link = category.find("a")["href"]
        age = category.find("div", class_="category-card__age-division").get_text(
            strip=True
        )
        belt = category.find("span", class_="category-card__belt-label").get_text(
            strip=True
        )
        weight = category.find("span", class_="category-card__weight-label").get_text(
            strip=True
        )

        results.append({"link": link, "age": age, "belt": belt, "weight": weight})

    return results


def parse_match_where(match):
    match_where = match.find("div", class_="bracket-match-header__where")
    if not match_where:
        return None, None

    fight_num_node = match_where.find("span", class_="bracket-match-header__fight")
    if fight_num_node:
        fight_num_match = re.search(
            r"(FIGHT|LUTA) (\d+):", fight_num_node.get_text(strip=True), re.IGNORECASE
        )
        if fight_num_match:
            fight_num = int(fight_num_match.group(2))
        else:
            fight_num = None

    match_location = "".join(
        t for t in match_where.contents if isinstance(t, str)
    ).strip()

    return match_location, fight_num


def parse_match_when(match, year):
    match_when = match.find("div", class_="bracket-match-header__when")
    if match_when:
        match_datetime = match_when.get_text(strip=True)

        if re.search(r"^(mon|tue|wed|thu|fri|sat|sun)\s", match_datetime, re.I):
            format = "%m/%d %I:%M %p"
        else:
            format = "%d/%m %I:%M %p"

        match_datetime = re.sub(
            r"^(mon|tue|wed|thu|fri|sat|sun|seg|ter|qua|qui|sex|sáb|sab|dom)\s|(at|às)\s",
            "",
            match_datetime,
            flags=re.I,
        )

        match_datetime_parsed = datetime.strptime(match_datetime, format)
        match_datetime_parsed = match_datetime_parsed.replace(year=year)
        match_datetime_iso = match_datetime_parsed.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        match_datetime_iso = ""

    return match_datetime_iso


def parse_competitor(competitor, competitor_description):
    if competitor_description.find("div", class_="match-card__bye"):
        return True, None, None, None, None, None, None

    competitor_id = competitor["id"].split("-")[-1]
    competitor_seed = competitor.find(
        "span", class_="match-card__competitor-n"
    ).get_text(strip=True)
    competitor_loser = "match-competitor--loser" in competitor_description["class"]
    competitor_name = competitor.find(
        "div", class_="match-card__competitor-name"
    ).get_text(strip=True)
    competitor_team = competitor.find("div", class_="match-card__club-name").get_text(
        strip=True
    )
    competitor_note = competitor_description.find(
        "i", class_="match-card__disqualification"
    )
    competitor_note = competitor_note["title"] if competitor_note else ""

    return (
        False,
        competitor_id,
        competitor_seed,
        competitor_loser,
        competitor_name,
        competitor_team,
        competitor_note,
    )


def parse_medals(soup):
    ret = {}

    podiums = soup.find_all("div", class_="podium__step")

    for podium in podiums:
        name = podium.find("div", "podium__competitor-name").get_text(strip=True)
        place = podium.find("span", "podium__place").get_text(strip=True)
        if not name or not place:
            continue
        ret[name] = place

    return ret


def pull_tournament(
    file,
    writer,
    tournament_id,
    tournament_name,
    gi,
    urls,
    base_url,
    year,
    limit=None,
    raise_on_error=True,
    retries=None,
    incomplete=False,
):
    total_matches = 0
    total_defaults = 0
    total_categories = 0

    s = requests.Session()
    if not raise_on_error:
        s.mount(base_url, HTTPAdapter(max_retries=0))

    unfinished = []

    for url, gender in urls:
        print(f"Fetching data for {gender} categories from {url}", flush=True)
        response = rate_limit_get(s, url, limit, retries)

        if response.status_code != 200:
            if raise_on_error:
                raise Exception(
                    f"Failed to retrieve data for {url}: {response.status_code}"
                )
            print(
                f"Failed to retrieve data for {url}: {response.status_code}", flush=True
            )
            continue

        soup = BeautifulSoup(response.content, "html.parser")

        categories = parse_categories(soup)

        for category in categories:
            category_matches = 0
            category_defaults = 0

            link = category["link"]
            age = category["age"]
            belt = category["belt"]
            weight = category["weight"]

            total_categories += 1

            print(
                f"Fetching data for {age} / {belt} / {weight} from {link}", flush=True
            )

            categoryurl = f"{base_url}{link}"
            response = rate_limit_get(s, categoryurl, limit, retries)
            if response.status_code != 200:
                if raise_on_error:
                    raise Exception(
                        f"Failed to retrieve data for {url}: {response.status_code}"
                    )
                print(
                    f"Failed to retrieve data for {categoryurl}: {response.status_code}",
                    flush=True,
                )
                continue

            category_soup = BeautifulSoup(response.content, "html.parser")

            medals = parse_medals(category_soup)

            matches = category_soup.find_all("div", class_="tournament-category__match")

            num_matches = len(matches)

            for match in matches:
                match_datetime_iso = parse_match_when(match, year)

                matchnum = ""
                card = match.find("div", class_="tournament-category__match-card")
                for classname in card.attrs["class"]:
                    if classname.startswith("match-"):
                        matchnum = classname.split("-")[1]
                        break

                red_competitor = match.find("div", class_="match-card__competitor--red")
                blue_competitor = [
                    c
                    for c in match.find_all("div", class_="match-card__competitor")
                    if c != red_competitor
                ][0]

                red_competitor_description = red_competitor.find(
                    "span", class_="match-card__competitor-description"
                )
                blue_competitor_description = blue_competitor.find(
                    "span", class_="match-card__competitor-description"
                )

                if not red_competitor_description or not blue_competitor_description:
                    continue

                (
                    red_bye,
                    red_competitor_id,
                    red_competitor_seed,
                    red_competitor_loser,
                    red_competitor_name,
                    red_competitor_team,
                    red_competitor_note,
                ) = parse_competitor(red_competitor, red_competitor_description)
                if red_bye:
                    continue

                (
                    blue_bye,
                    blue_competitor_id,
                    blue_competitor_seed,
                    blue_competitor_loser,
                    blue_competitor_name,
                    blue_competitor_team,
                    blue_competitor_note,
                ) = parse_competitor(blue_competitor, blue_competitor_description)

                if blue_bye:
                    if num_matches == 1 and not red_competitor_loser:  # default gold
                        writer.writerow(
                            [
                                tournament_id,
                                tournament_name,
                                link,
                                "true" if gi else "false",
                                gender,
                                age,
                                belt,
                                weight,
                                match_datetime_iso,
                                red_competitor_id,
                                red_competitor_seed,
                                "true",
                                red_competitor_name,
                                red_competitor_team,
                                red_competitor_note,
                                "1",
                                "DEFAULT_GOLD",
                                "",
                                "",
                                "",
                                "",
                                "",
                                "",
                            ]
                        )
                        file.flush()
                        category_defaults += 1
                        total_defaults += 1
                    continue

                if (
                    not incomplete
                    and not red_competitor_loser
                    and not blue_competitor_loser
                ):
                    red_competitor_note = WINNER_NOT_RECORDED
                    blue_competitor_loser = True
                    unfinished.append(
                        (
                            gender,
                            age,
                            belt,
                            weight,
                            red_competitor_name,
                            blue_competitor_name,
                        )
                    )

                writer.writerow(
                    [
                        tournament_id,
                        tournament_name,
                        link,
                        "true" if gi else "false",
                        gender,
                        age,
                        belt,
                        weight,
                        match_datetime_iso,
                        red_competitor_id,
                        red_competitor_seed,
                        "false" if red_competitor_loser else "true",
                        red_competitor_name,
                        red_competitor_team,
                        red_competitor_note,
                        medals.get(red_competitor_name, ""),
                        blue_competitor_id,
                        blue_competitor_seed,
                        "false" if blue_competitor_loser else "true",
                        blue_competitor_name,
                        blue_competitor_team,
                        blue_competitor_note,
                        medals.get(blue_competitor_name, ""),
                        matchnum,
                    ]
                )
                file.flush()

                category_matches += 1
                if not incomplete or (red_competitor_loser or blue_competitor_loser):
                    total_matches += 1

            print(
                f"Recorded {category_matches} matches and {category_defaults} default golds for {age} / {belt} / {weight}",
                flush=True,
            )
    print(
        f"Total matches recorded: {total_matches}, Total default golds recorded: {total_defaults}, Total divisions processed: {total_categories}",
        flush=True,
    )

    if len(unfinished):
        print("!!!Warning!!!: Unfinished matches detected:")

        unfinished_by_division = {}

        for (
            gender,
            age,
            belt,
            weight,
            red_competitor_name,
            blue_competitor_name,
        ) in unfinished:
            division = f"{belt} / {age} / {gender} / {weight}"
            if division not in unfinished_by_division:
                unfinished_by_division[division] = []
            unfinished_by_division[division].append(
                f"{red_competitor_name} vs {blue_competitor_name}"
            )
        for division, matches in unfinished_by_division.items():
            if len(matches) > 1:
                print(f"{division}: {len(matches)} matches")
            else:
                print(f"{division}: {matches[0]}")

        print("!!! These matches will be recorded as unrated in the database !!!")
