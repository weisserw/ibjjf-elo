#!/usr/bin/env python3
"""Fetch recent IBJJF YouTube match uploads into youtube_match_videos."""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402

import youtube_match_import_lib as lib  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("auto", "rss", "channel"),
        default="auto",
        help="YouTube metadata source. Default: auto.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="Number of YouTube channel pages to fetch for auto/channel source. Default: 2.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    with app.app_context():
        inserted, updated = lib.update_youtube_match_videos(
            db.session, source=args.source, max_pages=args.pages
        )
        print(f"Inserted {inserted} new YouTube match videos.")
        print(f"Updated {updated} existing YouTube match videos.")


if __name__ == "__main__":
    main()
