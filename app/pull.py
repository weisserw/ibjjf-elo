import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup


def rate_limit_get(url):
    count = 0
    response = requests.get(url)
    while response.status_code == 429:
        print(f"Rate limited, waiting {10 * (2 ** count)} seconds")
        time.sleep(10 * (2**count))
        count += 1
        response = requests.get(url)

    return response


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


def pull_tournament(
    file, writer, tournament_id, tournament_name, gi, urls, base_url, year
):
    total_matches = 0
    total_defaults = 0
    total_categories = 0

    for url, gender in urls:
        print(f"Fetching data for {gender} categories from {url}")
        response = rate_limit_get(url)

        if response.status_code != 200:
            print(f"Failed to retrieve data for {url}: {response.status_code}")
            return

        soup = BeautifulSoup(response.content, "html.parser")

        categories = soup.find_all("li", class_="categories-grid__category")

        for category in categories:
            category_matches = 0
            category_defaults = 0

            link = category.find("a")["href"]
            age = category.find("div", class_="category-card__age-division").get_text(
                strip=True
            )
            belt = category.find("span", class_="category-card__belt-label").get_text(
                strip=True
            )
            weight = category.find(
                "span", class_="category-card__weight-label"
            ).get_text(strip=True)

            age_lower = age.lower()

            if not (
                age_lower.startswith("master")
                or age_lower.startswith("juvenil")
                or age_lower.startswith("adult")
            ):
                continue

            total_categories += 1

            print(f"Fetching data for {age} / {belt} / {weight} from {link}")

            categoryurl = f"{base_url}{link}"
            response = rate_limit_get(categoryurl)
            if response.status_code != 200:
                print(
                    f"Failed to retrieve data for {categoryurl}: {response.status_code}"
                )
                return

            category_soup = BeautifulSoup(response.content, "html.parser")
            matches = category_soup.find_all("div", class_="tournament-category__match")

            num_matches = len(matches)

            for match in matches:
                match_when = match.find("div", class_="bracket-match-header__when")
                if match_when:
                    match_datetime = match_when.get_text(strip=True)
                    match_datetime_parsed = datetime.strptime(
                        match_datetime, "%a %m/%d at %I:%M %p"
                    )
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
                f"Recorded {category_matches} matches and {category_defaults} default golds for {age} / {belt} / {weight}"
            )
    print(
        f"Total matches recorded: {total_matches}, Total default golds recorded: {total_defaults}, Total divisions processed: {total_categories}"
    )
