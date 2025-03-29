#!/usr/bin/env python3

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
import csv
import traceback
from datetime import datetime

from pull import headers, pull_tournament


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Pull tournament matches from archive.org"
        )
        parser.add_argument("tournament_id", type=str, help="The ID of the tournament")
        parser.add_argument(
            "tournament_name", type=str, help="The name of the tournament"
        )
        parser.add_argument(
            "year",
            type=int,
            help="The year of the tournament",
        )
        parser.add_argument(
            "url",
            type=str,
            help="The URL for the tournament on archive.org",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--nogi",
            action="store_false",
            dest="gi",
            help="Specifies a no-gi tournament",
        )
        group.add_argument(
            "--gi", action="store_true", dest="gi", help="Specifies a gi tournament"
        )
        args = parser.parse_args()

        tournament_name_lower = args.tournament_name.lower()

        # Check for "no gi" or "no-gi" in the tournament name
        if (
            "no gi" in tournament_name_lower
            or "no-gi" in tournament_name_lower
            or "sem kimono" in tournament_name_lower
        ) and args.gi:
            input(
                "Warning: This tournament name indicates it is no-gi, but you are importing it as gi. Press Enter to continue or Ctrl-C to abort.\n"
            )
        elif (
            not (
                "no gi" in tournament_name_lower
                or "no-gi" in tournament_name_lower
                or "sem kimono" in tournament_name_lower
            )
            and not args.gi
        ):
            input(
                "Warning: The tournament name does not indicate no-gi, but you are importing it as no-gi. Press Enter to continue or Ctrl-C to abort.\n"
            )

        output_file = f"{args.tournament_id}.{args.tournament_name.replace(' ', '_')}.{datetime.now().strftime('%Y%m%d%H%M')}.csv"

        with open(output_file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(headers)

            urls = [
                (args.url, "Male"),
                (args.url + "?gender_id=2", "Female"),
            ]

            pull_tournament(
                file,
                writer,
                args.tournament_id,
                args.tournament_name,
                args.gi,
                urls,
                "https://web.archive.org",
                args.year,
                5,
                False,
                incomplete=True,
            )
        print(f"Wrote data to {output_file}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
