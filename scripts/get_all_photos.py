#!/usr/bin/env python3

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from photos import save_instagram_profile_photo_to_s3, get_s3_client, init_chrome_driver
from app import db, app
from models import Athlete

if __name__ == "__main__":
    with app.app_context():
        s3_client = get_s3_client()
        driver = init_chrome_driver()

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
                save_instagram_profile_photo_to_s3(s3_client, driver, athlete)
                db.session.commit()
            except Exception as e:
                print(f"Athlete {athlete.name}: An error occurred: {e}")
