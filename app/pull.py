import time
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime
from bs4 import BeautifulSoup
import re


class InternalServerError(Exception):
    """Custom exception for handling internal server errors."""

    pass


def rate_limit_get(session, url, limit, raise_on_error, retries):
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
        except requests.exceptions.ConnectionError:
            if raise_on_error and count > retries:
                raise
            print(f"Connection error, retrying in {30 * count} seconds", flush=True)
            time.sleep(30 * count)
            count += 1
        except requests.exceptions.Timeout:
            if raise_on_error and count > retries:
                raise
            print(f"Timeout error, retrying in {30 * count} seconds", flush=True)
            time.sleep(30 * count)
            count += 1
        except InternalServerError:
            if raise_on_error and count > retries:
                raise
            print(f"Internal server error, retrying in {30 * count}", flush=True)
            time.sleep(30 * count)
            count += 1


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
    "Blue ID",
    "Blue Seed",
    "Blue Winner",
    "Blue Name",
    "Blue Team",
    "Blue Note",
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
):
    total_matches = 0
    total_defaults = 0
    total_categories = 0

    s = requests.Session()
    if not raise_on_error:
        s.mount(base_url, HTTPAdapter(max_retries=0))

    for url, gender in urls:
        print(f"Fetching data for {gender} categories from {url}", flush=True)
        response = rate_limit_get(s, url, limit, raise_on_error, retries)

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
            response = rate_limit_get(s, categoryurl, limit, raise_on_error, retries)
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
            matches = category_soup.find_all("div", class_="tournament-category__match")

            num_matches = len(matches)

            for match in matches:
                match_when = match.find("div", class_="bracket-match-header__when")
                if match_when:
                    match_datetime = match_when.get_text(strip=True)

                    if re.search(
                        r"^(mon|tue|wed|thu|fri|sat|sun)\s", match_datetime, re.I
                    ):
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
                    match_datetime_iso = match_datetime_parsed.strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    )
                else:
                    match_datetime_iso = ""
                red_competitor = match.find("div", class_="match-card__competitor--red")
                blue_competitor = match.find_all(
                    "div", class_="match-card__competitor"
                )[1]

                red_competitor_description = red_competitor.find(
                    "span", class_="match-card__competitor-description"
                )
                blue_competitor_description = blue_competitor.find(
                    "span", class_="match-card__competitor-description"
                )

                if not red_competitor_description or not blue_competitor_description:
                    continue

                if red_competitor_description.find("div", class_="match-card__bye"):
                    continue

                red_competitor_id = red_competitor["id"].split("-")[-1]
                red_competitor_seed = red_competitor.find(
                    "span", class_="match-card__competitor-n"
                ).get_text(strip=True)
                red_competitor_loser = (
                    "match-competitor--loser" in red_competitor_description["class"]
                )
                red_competitor_name = red_competitor.find(
                    "div", class_="match-card__competitor-name"
                ).get_text(strip=True)
                red_competitor_team = red_competitor.find(
                    "div", class_="match-card__club-name"
                ).get_text(strip=True)
                red_competitor_note = red_competitor_description.find(
                    "i", class_="match-card__disqualification"
                )
                red_competitor_note = (
                    red_competitor_note["title"] if red_competitor_note else ""
                )

                if blue_competitor_description.find("div", class_="match-card__bye"):
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
                                "DEFAULT_GOLD",
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

                blue_competitor_id = blue_competitor["id"].split("-")[-1]
                blue_competitor_seed = blue_competitor.find(
                    "span", class_="match-card__competitor-n"
                ).get_text(strip=True)
                blue_competitor_loser = (
                    "match-competitor--loser" in blue_competitor_description["class"]
                )
                blue_competitor_name = blue_competitor.find(
                    "div", class_="match-card__competitor-name"
                ).get_text(strip=True)
                blue_competitor_team = blue_competitor.find(
                    "div", class_="match-card__club-name"
                ).get_text(strip=True)
                blue_competitor_note = blue_competitor_description.find(
                    "i", class_="match-card__disqualification"
                )
                blue_competitor_note = (
                    blue_competitor_note["title"] if blue_competitor_note else ""
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
                        blue_competitor_id,
                        blue_competitor_seed,
                        "false" if blue_competitor_loser else "true",
                        blue_competitor_name,
                        blue_competitor_team,
                        blue_competitor_note,
                    ]
                )
                file.flush()

                category_matches += 1
                total_matches += 1

            print(
                f"Recorded {category_matches} matches and {category_defaults} default golds for {age} / {belt} / {weight}",
                flush=True,
            )
    print(
        f"Total matches recorded: {total_matches}, Total default golds recorded: {total_defaults}, Total divisions processed: {total_categories}",
        flush=True,
    )
