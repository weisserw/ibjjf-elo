#!/usr/bin/env python3

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import db, app
from models import Athlete
from normalize import normalize

if __name__ == "__main__":
    errfp = None

    with app.app_context():
        for athlete in (
            db.session.query(Athlete)
            .filter(
                Athlete.personal_name.isnot(None),
            )
            .order_by(Athlete.name)
            .all()
        ):
            athlete.normalized_personal_name = normalize(athlete.personal_name)
            print(
                f"Athlete {athlete.name} ({athlete.id}): normalized personal name set to '{athlete.normalized_personal_name}'"
            )

        db.session.commit()
