#!/usr/bin/env python3

import sys
import os
from uuid import UUID

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from photos import save_instagram_profile_photo_to_s3, get_s3_client, init_chrome_driver
from app import db, app
from models import Athlete

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get and upload an athlete's Instagram profile photo to S3"
    )
    parser.add_argument("--athlete-id", type=str, help="Athlete ID")
    args = parser.parse_args()

    if not args.athlete_id:
        print("You must enter an Athlete ID.")
        sys.exit(1)

    with app.app_context():
        athlete = db.session.query(Athlete).filter_by(id=UUID(args.athlete_id)).first()

        if not athlete:
            print(f"Athlete with ID {args.athlete_id} not found.")
            sys.exit(1)

        if not athlete.instagram_profile:
            print(
                f"Athlete with ID {args.athlete_id} does not have an Instagram handle."
            )
            sys.exit(1)

        try:
            s3_client = get_s3_client()
            driver = init_chrome_driver()
            save_instagram_profile_photo_to_s3(s3_client, driver, athlete)

            db.session.commit()
        except Exception as e:
            print(f"An error occurred: {e}")
            sys.exit(1)
