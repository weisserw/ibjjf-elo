#!/usr/bin/env python

import sys
import os
import csv
from uuid import UUID

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import db, app
from models import Athlete
from normalize import normalize


def to_null(val):
    return val.strip() if val and val.strip() else None


def coalesce(arg, default):
    return arg if arg is not None else default


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: import_instagram_names.py <instagram_names.csv>")
        sys.exit(1)
    csv_path = sys.argv[1]
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        cnt = 0
        with app.app_context():
            for row in reader:
                id = row["id"].strip()
                personal_name = to_null(row.get("personal_name", ""))
                if personal_name:
                    personal_name = (
                        personal_name.replace("”", '"')
                        .replace("“", '"')
                        .replace("‘", "'")
                        .replace("’", "'")
                    )
                athlete = db.session.get(Athlete, UUID(id))
                if not athlete:
                    print(f"No athlete found for id: {id}")
                    continue
                if coalesce(personal_name, "") != coalesce(athlete.personal_name, ""):
                    athlete.personal_name = personal_name
                    athlete.normalized_personal_name = normalize(personal_name)
                    print(
                        f"Updated {id} / {athlete.name}: personal_name={personal_name}"
                    )
                    cnt += 1
                    if cnt % 100 == 0:
                        db.session.commit()
            db.session.commit()
    print("Import complete.")
