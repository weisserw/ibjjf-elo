#!/usr/bin/env python3

import sys
import os
import argparse
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))

from ratings import recompute_all_ratings
from constants import (
    MALE, FEMALE,
    ADULT, MASTER_1, MASTER_2, MASTER_3, MASTER_4, MASTER_5, MASTER_6, MASTER_7, JUVENILE_1, JUVENILE_2
)
from app import db, app

def main():
    parser = argparse.ArgumentParser(description='Recompute ratings with optional filters.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--nogi', action='store_false', dest='gi', help='Use this flag to indicate no gi.')
    group.add_argument('--gi', action='store_true', dest='gi', help='Use this flag to indicate gi.')
    parser.add_argument('--gender', type=str, help='Filter by gender.')
    parser.add_argument('--age', type=str, help='Filter by age.')
    parser.add_argument('--start-date', type=str, help='Don\'t rate matches earlier than date.')

    args = parser.parse_args()

    if args.gender and args.gender not in (MALE, FEMALE):
        print(f"Invalid gender. Must be one of {MALE}, {FEMALE}")
        return -1
    if args.age and args.age not in (ADULT, MASTER_1, MASTER_2, MASTER_3, MASTER_4, MASTER_5, MASTER_6, MASTER_7, JUVENILE_1, JUVENILE_2):
        print(f"Invalid age. Must be one of {ADULT}, {MASTER_1}, {MASTER_2}, {MASTER_3}, {MASTER_4}, {MASTER_5}, {MASTER_6}, {MASTER_7}, {JUVENILE_1}, {JUVENILE_2}")
        return -1

    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        except ValueError:
            try:
                start_date = datetime.strptime(args.start_date, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                print("Invalid start date format. Must be either YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss")
                return -1

    with app.app_context():
        count = recompute_all_ratings(db, args.gi, gender=args.gender, age=args.age, start_date=start_date)

        db.session.commit()
        print(f"Computed ratings for {count} matches")

    return 0

if __name__ == '__main__':
    sys.exit(main())