"""Print initial seed pairings from a saved IBJJF bracket HTML file.

Usage:
    python3 bracket_initial_pairings.py example_bracket.html
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup


MATCH_CLASS_RE = re.compile(r"match-(\d+)$")
SEED_RE = re.compile(r"^\s*(\d+)\b")


def parse_match_number(card) -> int | None:
    for class_name in card.get("class", []):
        match = MATCH_CLASS_RE.fullmatch(class_name)
        if match:
            return int(match.group(1))
    return None


def parse_swaps(soup: BeautifulSoup) -> dict[int, int]:
    swaps: dict[int, int] = {}

    for swap_list in soup.select("ul.tournament-category__swap"):
        for item in swap_list.find_all("li", recursive=False):
            seeds = []
            for span in item.find_all("span"):
                match = SEED_RE.match(span.get_text(strip=True))
                if match:
                    seeds.append(int(match.group(1)))

            if len(seeds) >= 2:
                left, right = seeds[0], seeds[1]
                swaps[left] = right
                swaps[right] = left

    return swaps


def parse_competitor_slot(competitor, swaps: dict[int, int]) -> str:
    if competitor.find("div", class_="match-card__bye"):
        return "bye"

    seed = competitor.find("span", class_="match-card__competitor-n")
    if not seed:
        return ""

    seed_text = seed.get_text(strip=True)
    if not seed_text:
        return ""
    if not seed_text.isdigit():
        return ""

    seed_number = int(seed_text)
    return str(swaps.get(seed_number, seed_number))


def is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def parse_cards(soup: BeautifulSoup) -> list[tuple[int, list[str]]]:
    swaps = parse_swaps(soup)
    matches: list[tuple[int, list[str]]] = []

    for card in soup.find_all("div", class_="tournament-category__match-card"):
        match_number = parse_match_number(card)
        if match_number is None:
            continue

        competitors = card.find_all("div", class_="match-card__competitor")[:2]
        slots = [parse_competitor_slot(competitor, swaps) for competitor in competitors]
        matches.append((match_number, slots))

    return matches


def initial_pairings(html: str) -> tuple[int, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    matches = sorted(parse_cards(soup), key=lambda match: match[0])

    bracket_size = len(matches) + 1
    if not is_power_of_two(bracket_size):
        raise ValueError(
            f"Expected match count + 1 to be a power of two, got {bracket_size}"
        )

    expected_numbers = list(range(1, bracket_size))
    actual_numbers = [match_number for match_number, _ in matches]
    if actual_numbers != expected_numbers:
        raise ValueError(
            "Expected match numbers 1 through "
            f"{bracket_size - 1}, got {actual_numbers[:5]}...{actual_numbers[-5:]}"
        )

    first_round = matches[: bracket_size // 2]
    pairings: list[tuple[str, str]] = []
    for _, slots in first_round:
        if len(slots) != 2 or not slots[0] or not slots[1]:
            continue
        pairings.append((slots[0], slots[1]))

    return bracket_size, pairings


def count_seed_numbers(pairings: list[tuple[str, str]]) -> int:
    return sum(1 for pairing in pairings for slot in pairing if slot != "bye")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the initial seed pairings from an IBJJF bracket HTML file."
    )
    parser.add_argument("html_file", type=Path)
    args = parser.parse_args()

    _, pairings = initial_pairings(args.html_file.read_text(encoding="utf-8"))

    print(f"{count_seed_numbers(pairings)}:")
    print()
    for left, right in pairings:
        print(f"{left},{right}")


if __name__ == "__main__":
    main()
