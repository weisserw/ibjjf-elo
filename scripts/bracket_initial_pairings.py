"""Print initial seed pairings from a saved IBJJF bracket HTML file.

Usage:
    python3 bracket_initial_pairings.py example_bracket.html
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from bracket_audit import (  # noqa: E402
    first_round_slots_from_matches,
    parse_team_swaps,
)
from routes.brackets import parse_match  # noqa: E402


def initial_pairings(html: str) -> tuple[int, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    match_nodes = soup.find_all("div", class_="tournament-category__match")
    matches = [parse_match(match, "Unknown") for match in match_nodes]
    if not match_nodes or any(match is None for match in matches):
        raise ValueError("Live bracket parser could not parse every match")
    parsed = first_round_slots_from_matches(matches, parse_team_swaps(soup))
    pairings = [
        tuple("bye" if seed is None else str(seed) for seed in pair)
        for pair in parsed["slots"]
    ]
    return parsed["bracket_size"], pairings


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
