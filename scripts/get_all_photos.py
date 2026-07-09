#!/usr/bin/env python3

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

import argparse
from photos import save_instagram_profile_photo_to_s3, get_s3_client
from app import db, app
from models import Athlete
import time
import random

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get and upload missing Instagram profile photos to S3"
    )
    parser.add_argument(
        "--save-name",
        action="store_true",
        help="Also save athletes' personal names from Instagram when empty",
    )
    args = parser.parse_args()

    errfp = None

    with app.app_context():
        s3_client = get_s3_client()

        errors = 0

        for athlete in (
            db.session.query(Athlete)
            .filter(
                Athlete.instagram_profile.isnot(None),
                Athlete.instagram_profile != "",
                Athlete.profile_image_saved_at.is_(None),
            )
            .order_by(Athlete.name)
            .all()
        ):
            try:
                save_instagram_profile_photo_to_s3(
                    s3_client, athlete, save_name=args.save_name
                )
                db.session.commit()
                errors = 0
            except Exception as e:
                print(f"Athlete {athlete.name}: An error occurred: {e}")

                if errfp is None:
                    errfp = open("get_all_photos_errors.log", "a")
                errfp.write(
                    f"{athlete.id},{athlete.name},{athlete.instagram_profile},{str(e)}\n"
                )

                errors += 1

                if errors >= 15:
                    print("Too many errors, exiting.")
                    break

            time.sleep(random.uniform(3, 6))
