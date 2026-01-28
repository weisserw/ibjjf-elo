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
        noninteractive = os.getenv("IMPORT_NONINTERACTIVE") == "1"
        parser = argparse.ArgumentParser(
            description="Pull tournament matches from bjjcompsystem.com"
        )
        parser.add_argument("tournament_id", type=str, help="The ID of the tournament")
        parser.add_argument(
            "tournament_name", type=str, help="The name of the tournament"
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
        parser.add_argument(
            "--retries",
            type=int,
            default=2,
            help="Number of retries for failed requests (default: 2)",
        )
        parser.add_argument(
            "--allow-errors",
            action="store_true",
            help="Don't abort on errors (default: False)",
        )
        parser.add_argument(
            "--incomplete",
            action="store_true",
            help="Tournament is incomplete; ignore unfinished matches (default: False)",
        )

        args = parser.parse_args()

        tournament_name_lower = args.tournament_name.lower()

        # Check for "no gi" or "no-gi" in the tournament name
        if (
            "no gi" in tournament_name_lower
            or "no-gi" in tournament_name_lower
            or "sem kimono" in tournament_name_lower
        ) and args.gi:
            warning = "Warning: This tournament name indicates it is no-gi, but you are importing it as gi."
            if noninteractive:
                print(warning)
            else:
                input(f"{warning} Press Enter to continue or Ctrl-C to abort.\n")
        elif (
            not (
                "no gi" in tournament_name_lower
                or "no-gi" in tournament_name_lower
                or "sem kimono" in tournament_name_lower
            )
            and not args.gi
        ):
            warning = "Warning: The tournament name does not indicate no-gi, but you are importing it as no-gi."
            if noninteractive:
                print(warning)
            else:
                input(f"{warning} Press Enter to continue or Ctrl-C to abort.\n")

        urls = [
            (
                f"https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories",
                "Male",
            ),
            (
                f"https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories?gender_id=2",
                "Female",
            ),
        ]

        output_file = f"{args.tournament_id}.{args.tournament_name.replace(' ', '_')}.{datetime.now().strftime('%Y%m%d%H%M')}.csv"

        with open(output_file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(headers)

            pull_tournament(
                file,
                writer,
                args.tournament_id,
                args.tournament_name,
                args.gi,
                urls,
                "https://www.bjjcompsystem.com",
                datetime.now().year,
                raise_on_error=not args.allow_errors,
                retries=args.retries,
                incomplete=args.incomplete,
            )
        print(f"Wrote data to {output_file}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
